"""Writing to Lekto through its REST API, with an admin's API token. Nothing else is used."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

import httpx2

API = "/api/v1"
RETRY_STATUS = {500, 502, 503, 504}
DELAYS = (1.0, 3.0, 10.0)


class ApiError(Exception):
    """A request Lekto refused. `existing` is the document a duplicate upload collided with."""

    def __init__(self, status: int, detail: str, existing: str | None = None) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail
        self.existing = existing


class Lekto:
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
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx2.Timeout(300.0, connect=10.0),
            transport=transport,
        )
        self._sleep = sleep
        self._delays = delays

    async def close(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        upload: tuple[Path, str] | None = None,
    ) -> Any:
        """The decoded JSON answer (None for 204). Server errors and a dropped connection are
        repeated a few times; every other refusal is an `ApiError`."""
        for attempt in range(len(self._delays) + 1):
            try:
                if upload is None:
                    response = await self._client.request(
                        method, API + path, json=json, params=params
                    )
                else:
                    path_, filename = upload
                    with path_.open("rb") as handle:
                        response = await self._client.request(
                            method,
                            API + path,
                            data=data,
                            files={"file": (filename, handle, "application/octet-stream")},
                        )
            except httpx2.TransportError as error:
                if attempt == len(self._delays):
                    raise ApiError(0, f"Lekto is not reachable: {type(error).__name__}") from None
                await self._sleep(self._delays[attempt])
                continue
            if response.status_code in RETRY_STATUS and attempt < len(self._delays):
                await self._sleep(self._delays[attempt])
                continue
            if response.status_code == 429 and attempt < len(self._delays):
                await self._sleep(_wait(response.headers.get("retry-after")))
                continue
            if response.status_code >= 400:
                raise _error(response)
            return None if response.status_code == 204 else response.json()
        raise AssertionError("unreachable")

    async def _object(self, method: str, path: str, **arguments: Any) -> dict[str, Any]:
        return cast("dict[str, Any]", await self.request(method, path, **arguments))

    # --- reading -----------------------------------------------------------------------------

    async def me(self) -> dict[str, Any]:
        return await self._object("GET", "/auth/me")

    async def items(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", await self.request("GET", path, params=params))

    async def documents(self, *, cursor: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"all_users": "true", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        return await self._object("GET", "/documents", params=params)

    async def document(self, id: str) -> dict[str, Any]:
        return await self._object("GET", f"/documents/{id}")

    async def log(self, id: str) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", await self.request("GET", f"/documents/{id}/log"))

    async def text(self, id: str) -> str:
        """The whole text of a document's archive, piece by piece."""
        pieces, offset = [], 0
        while True:
            piece = await self._object("GET", f"/documents/{id}/text", params={"offset": offset})
            pieces.append(str(piece["text"]))
            if piece.get("next_offset") is None:
                return "".join(pieces)
            offset = int(piece["next_offset"])

    async def reading(self, id: str) -> dict[str, Any]:
        return await self._object("GET", f"/documents/{id}/reading")

    # --- writing -----------------------------------------------------------------------------

    async def create_user(self, username: str) -> dict[str, Any]:
        return await self._object("POST", "/users", json={"username": username})

    async def set_active(self, id: str, active: bool) -> dict[str, Any]:
        return await self._object("PATCH", f"/users/{id}", json={"active": active})

    async def profile(self, id: str) -> dict[str, Any]:
        return await self._object("GET", f"/users/{id}/profile")

    async def change_profile(self, id: str, changes: dict[str, Any]) -> dict[str, Any]:
        return await self._object("PATCH", f"/users/{id}/profile", json=changes)

    async def create_named(self, path: str, name: str) -> dict[str, Any]:
        return await self._object("POST", path, json={"name": name})

    async def create_tag(self, name: str, scope: str, parent_id: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name, "scope": scope}
        if parent_id is not None:
            body["parent_id"] = parent_id
        return await self._object("POST", "/tags", json=body)

    async def set_groups(self, path: str, id: str, group_ids: list[str]) -> dict[str, Any]:
        """The groups of a contact (`/contacts`) or a document type (`/document-types`)."""
        return await self._object("PATCH", f"{path}/{id}", json={"group_ids": group_ids})

    async def create_field(
        self, name: str, data_type: str, choices: tuple[str, ...]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name, "data_type": data_type}
        if choices:
            body["choices"] = list(choices)
        return await self._object("POST", "/fields", json=body)

    async def set_choices(self, id: str, choices: list[str]) -> dict[str, Any]:
        return await self._object("PATCH", f"/fields/{id}", json={"choices": choices})

    async def create_space(self, name: str, members: dict[str, str]) -> dict[str, Any]:
        """A shared space with `members` (user id -> `read` or `edit`); the executing admin
        is not one of them."""
        body = {"name": name, "members": [{"user_id": u, "role": r} for u, r in members.items()]}
        return await self._object("POST", "/spaces", json=body)

    async def set_member(self, space_id: str, user_id: str, role: str) -> dict[str, Any]:
        return await self._object(
            "PUT", f"/spaces/{space_id}/members/{user_id}", json={"role": role}
        )

    async def upload(self, path: Path, filename: str, fields: dict[str, str]) -> dict[str, Any]:
        return await self._object("POST", "/documents", data=fields, upload=(path, filename))

    async def align(self, id: str, changes: dict[str, Any], *, dry_run: bool = False) -> Any:
        """Change a migrated document like its source without confirming it; with `dry_run`,
        what would happen (the rules included)."""
        if dry_run:
            return await self._object(
                "POST", f"/documents/{id}/dry-run", json=changes, params={"confirm": "false"}
            )
        return await self._object(
            "PATCH", f"/documents/{id}", json=changes, params={"confirm": "false"}
        )

    async def move(self, id: str, space_id: str) -> Any:
        return await self.request("POST", f"/documents/{id}/move", json={"space_id": space_id})


def _wait(header: str | None) -> float:
    """Seconds to wait for a `Retry-After` header; five if it is not a plain number."""
    try:
        return min(max(float(header or "5"), 0.0), 60.0)
    except ValueError:
        return 5.0


def _error(response: httpx2.Response) -> ApiError:
    detail, existing = response.text[:300], None
    try:
        body = response.json()
        detail = str(body.get("detail") or body.get("title") or detail)
        existing = body.get("existing_document_id")
    except (ValueError, AttributeError):
        pass
    return ApiError(response.status_code, detail, existing)
