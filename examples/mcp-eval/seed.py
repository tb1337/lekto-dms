"""Load the example documents into a Lekto instance of its own, with what the manifest says.

    python seed.py --url http://localhost:8010 --token lekto_...

The token is an admin's (scope read_write). Creates the contacts, document types and fields the
manifest names, then uploads every file of `examples/documents/files` as taken over from
another system (channel `migration`): its contact, type, date, title and fields come from the
manifest, so the manifest is the truth the tasks are checked against. Standard library only.
Never point it at an instance with real documents.
"""

import argparse
import json
import mimetypes
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from manifest import EXAMPLES, documents

PERIOD = re.compile(r"^\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DuplicateError(Exception):
    """The file lies in Lekto already (409): the manifest's duplicates are meant to be one."""


class Api:
    def __init__(self, url: str, token: str) -> None:
        self.base = url.rstrip("/") + "/api/v1"
        self.token = token

    def call(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Authorization": f"Bearer {self.token}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        return self._send(urllib.request.Request(self.base + path, data, headers, method=method))

    def upload(self, file: Path, metadata: dict[str, Any]) -> Any:
        boundary = uuid.uuid4().hex
        media_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        parts = [
            _part(boundary, "channel", b"migration"),
            _part(boundary, "metadata", json.dumps(metadata).encode()),
            _part(boundary, "file", file.read_bytes(), filename=file.name, media_type=media_type),
        ]
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        return self._send(
            urllib.request.Request(self.base + "/documents", body, headers, method="POST")
        )

    def _send(self, request: urllib.request.Request) -> Any:
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read()
        except urllib.error.HTTPError as error:
            if error.code == 409 and request.full_url.endswith("/documents"):
                raise DuplicateError from None
            problem = f"{request.method} {request.full_url}: {error.code} {error.read()!r}"
            raise SystemExit(problem) from None
        return json.loads(text) if text else None


def _part(
    boundary: str, name: str, data: bytes, *, filename: str | None = None, media_type: str = ""
) -> bytes:
    disposition = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
    head = f"--{boundary}\r\nContent-Disposition: {disposition}\r\n"
    if media_type:
        head += f"Content-Type: {media_type}\r\n"
    return head.encode() + b"\r\n" + data + b"\r\n"


def field_type(values: list[Any]) -> str:
    """The data type a field's values in the manifest have."""
    if all(isinstance(value, dict) and set(value) == {"amount", "currency"} for value in values):
        return "amount"
    if all(isinstance(value, str) and PERIOD.match(value) for value in values):
        return "period"
    if all(isinstance(value, str) and DAY.match(value) for value in values):
        return "date"
    return "text"


def field_value(kind: str, value: Any) -> Any:
    if kind == "period":
        start, end = value.split("/")
        return {"start": start, "end": end}
    return value


def seed(api: Api, manifest: list[dict[str, Any]]) -> None:
    known_contacts = {item["name"]: item["id"] for item in api.call("GET", "/contacts")}
    known_types = {item["name"]: item["id"] for item in api.call("GET", "/document-types")}
    known_fields = {item["name"]: item for item in api.call("GET", "/fields")}
    contacts = {doc["contact"] for doc in manifest if doc.get("contact")}
    for name in sorted(contacts - set(known_contacts)):
        known_contacts[name] = api.call("POST", "/contacts", {"name": name})["id"]
    types = {doc["document_type"] for doc in manifest if doc.get("document_type")}
    for name in sorted(types - set(known_types)):
        known_types[name] = api.call("POST", "/document-types", {"name": name})["id"]
    values: dict[str, list[Any]] = {}
    for doc in manifest:
        for name, value in (doc.get("fields") or {}).items():
            values.setdefault(name, []).append(value)
    kinds = {name: field_type(found) for name, found in values.items()}
    for name in sorted(set(kinds) - set(known_fields)):
        known_fields[name] = api.call("POST", "/fields", {"name": name, "data_type": kinds[name]})
    seen = {item["original_filename"] for item in _all_documents(api)}
    for number, doc in enumerate(manifest, 1):
        if doc["file"] in seen:
            continue
        metadata: dict[str, Any] = {
            "title": doc.get("title"),
            "contact_id": known_contacts.get(doc.get("contact") or ""),
            "document_type_id": known_types.get(doc.get("document_type") or ""),
            "document_date": doc.get("document_date"),
            "fields": {
                known_fields[name]["id"]: field_value(kinds[name], value)
                for name, value in (doc.get("fields") or {}).items()
            },
        }
        try:
            api.upload(EXAMPLES / "files" / doc["file"], {k: v for k, v in metadata.items() if v})
        except DuplicateError:
            print(f"{number}/{len(manifest)} {doc['file']}: a duplicate, left out", file=sys.stderr)
            continue
        print(f"{number}/{len(manifest)} {doc['file']}", file=sys.stderr)


def _all_documents(api: Api) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = api.call("GET", f"/documents?limit=100&offset={offset}")["items"]
        found += page
        if len(page) < 100:
            return found
        offset += 100


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--url", required=True, help="the Lekto instance, e.g. http://localhost:8010"
    )
    parser.add_argument("--token", required=True, help="an admin's API token (read_write)")
    parser.add_argument("--documents", type=int, help="a fixed sample of so many (default: all)")
    arguments = parser.parse_args()
    seed(Api(arguments.url, arguments.token), documents(arguments.documents))


if __name__ == "__main__":
    main()
