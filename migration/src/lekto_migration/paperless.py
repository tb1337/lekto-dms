"""Reading Paperless-ngx through its REST API. Only GET requests, nothing is written. Server
errors and a dropped connection are repeated a few times, as towards Lekto."""

import asyncio
import hashlib
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2

from lekto_migration.lekto import DELAYS, RETRY_STATUS

API_VERSION = "10"
DOCUMENT_FIELDS = ",".join(
    [
        "id",
        "title",
        "created",
        "added",
        "modified",
        "owner",
        "correspondent",
        "document_type",
        "storage_path",
        "tags",
        "custom_fields",
        "archive_serial_number",
        "notes",
        "permissions",
        "original_file_name",
        "mime_type",
        "versions",
        "root_document",
        "deleted_at",
    ]
)
# Things Lekto has no counterpart for; only counted.
COUNTED = ("saved_views", "workflows", "mail_rules", "mail_accounts", "share_links", "trash")


class PaperlessError(Exception):
    pass


class _UnavailableError(PaperlessError):
    """A failure that may pass: a server error or a dropped connection."""


_SHA256 = re.compile(r"[0-9a-f]{64}")


def checksum(document: dict[str, Any]) -> str | None:
    """Paperless keeps the SHA-256 of the original per version; the root version is the file."""
    for version in document.get("versions") or []:
        value = str(version.get("checksum") or "")
        if version.get("is_root") and _SHA256.fullmatch(value):
            return value
    return None


@dataclass
class Snapshot:
    """Everything the migration reads from Paperless."""

    version: str
    users: list[dict[str, Any]]
    groups: list[dict[str, Any]]
    correspondents: list[dict[str, Any]]
    document_types: list[dict[str, Any]]
    tags: list[dict[str, Any]]
    custom_fields: list[dict[str, Any]]
    storage_paths: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    counted: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Download:
    sha256: str
    size: int


class Paperless:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        delays: tuple[float, ...] = DELAYS,
    ) -> None:
        self._client = httpx2.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Token {token}",
                "Accept": f"application/json; version={API_VERSION}",
            },
            timeout=httpx2.Timeout(60.0, connect=10.0),
            transport=transport,
        )
        self.version = "unknown"
        self._sleep = sleep
        self._delays = delays

    async def close(self) -> None:
        await self._client.aclose()

    async def _retrying[T](self, once: Callable[[], Awaitable[T]]) -> T:
        """`once`, repeated after each of the delays while it fails in a way that may pass."""
        for delay in self._delays:
            try:
                return await once()
            except _UnavailableError:
                await self._sleep(delay)
        return await once()

    async def _get(self, path: str, **params: Any) -> httpx2.Response:
        return await self._retrying(lambda: self._get_once(path, params))

    async def _get_once(self, path: str, params: dict[str, Any]) -> httpx2.Response:
        try:
            response = await self._client.get(path, params=params)
        except httpx2.TransportError as error:
            raise _UnavailableError(f"Paperless is not reachable: {type(error).__name__}") from None
        except httpx2.HTTPError as error:
            raise PaperlessError(f"Paperless is not reachable: {type(error).__name__}") from None
        if response.status_code == 401 or response.status_code == 403:
            raise PaperlessError(f"Paperless refused the API key ({response.status_code})")
        if response.status_code in RETRY_STATUS:
            raise _UnavailableError(f"GET {path}: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise PaperlessError(f"GET {path}: HTTP {response.status_code}")
        self.version = response.headers.get("x-version", self.version)
        return response

    async def pages(self, path: str, **params: Any) -> AsyncIterator[dict[str, Any]]:
        """Every result of a list endpoint, page by page."""
        page = 1
        while True:
            data = (await self._get(path, page=page, page_size=100, **params)).json()
            for item in data["results"]:
                yield item
            if not data.get("next"):
                return
            page += 1

    async def all(self, path: str, **params: Any) -> list[dict[str, Any]]:
        return [item async for item in self.pages(path, **params)]

    async def count(self, path: str) -> int:
        return int((await self._get(path, page_size=1)).json()["count"])

    async def snapshot(self, *, limit: int | None = None) -> Snapshot:
        documents = await self.all(
            "/api/documents/", ordering="id", full_perms="true", fields=DOCUMENT_FIELDS
        )
        if limit is not None:
            documents = documents[:limit]
        snapshot = Snapshot(
            version="",
            users=await self.all("/api/users/"),
            groups=await self.all("/api/groups/"),
            correspondents=await self.all("/api/correspondents/"),
            document_types=await self.all("/api/document_types/"),
            tags=await self.all("/api/tags/"),
            custom_fields=await self.all("/api/custom_fields/"),
            storage_paths=await self.all("/api/storage_paths/"),
            documents=documents,
        )
        for name in COUNTED:
            try:
                snapshot.counted[name] = await self.count(f"/api/{name}/")
            except PaperlessError:
                snapshot.counted[name] = -1  # this Paperless has no such endpoint
        snapshot.version = self.version
        return snapshot

    async def contents(self, ids: set[int]) -> dict[int, str]:
        """The text Paperless recognised, by document; read only for the comparison."""
        found: dict[int, str] = {}
        async for item in self.pages("/api/documents/", ordering="id", fields="id,content"):
            if int(item["id"]) in ids:
                found[int(item["id"])] = str(item.get("content") or "")
        return found

    async def download_original(self, id: int, target: Path) -> Download:
        """The original file of a document, written to `target`; its SHA-256 and size."""
        return await self._retrying(lambda: self._download_once(id, target))

    async def _download_once(self, id: int, target: Path) -> Download:
        digest, size = hashlib.sha256(), 0
        try:
            async with self._client.stream(
                "GET", f"/api/documents/{id}/download/", params={"original": "true"}
            ) as response:
                if response.status_code >= 400:
                    reason = f"download of document {id}: HTTP {response.status_code}"
                    if response.status_code in RETRY_STATUS:
                        raise _UnavailableError(reason)
                    raise PaperlessError(reason)
                with target.open("wb") as out:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                        out.write(chunk)
        except httpx2.TransportError as error:
            raise _UnavailableError(f"download of document {id}: {type(error).__name__}") from None
        except httpx2.HTTPError as error:
            raise PaperlessError(f"download of document {id}: {type(error).__name__}") from None
        return Download(digest.hexdigest(), size)
