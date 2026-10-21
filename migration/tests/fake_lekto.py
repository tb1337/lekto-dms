"""A small stand-in for the Lekto API: the endpoints the migration uses, in memory. The real API
is exercised by the flow tests in the backend's test suite."""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import HTTP
from typing import Any, cast
from uuid import uuid4

import httpx2

TOKEN = "lekto-test-key"
PREFIX = "/api/v1"
ADMIN: dict[str, Any] = {"id": "admin-id", "username": "root", "role": "admin", "active": True}


@dataclass
class FakeLekto:
    users: dict[str, dict[str, Any]] = field(default_factory=lambda: {ADMIN["id"]: dict(ADMIN)})
    contacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    document_types: dict[str, dict[str, Any]] = field(default_factory=dict)
    tags: dict[str, dict[str, Any]] = field(default_factory=dict)
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    spaces: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {f"personal:{ADMIN['id']}": _personal(ADMIN["id"])}
    )
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    scope: str = "read_write"
    role: str = "admin"
    ticks: int = 1  # polls until a document's pipeline is through
    lanes: dict[str, str] = field(default_factory=dict)  # file name -> lane (default green)
    errors: dict[str, tuple[int, int]] = field(default_factory=dict)  # file name -> (status, times)
    log: list[tuple[str, str]] = field(default_factory=list)
    texts: dict[str, str] = field(default_factory=dict)  # file name -> the archive's text
    advice: dict[str, str] = field(default_factory=dict)  # file name -> reading advice
    aligned: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # PATCH confirm=false
    uploads: list[dict[str, str]] = field(default_factory=list)
    after_upload: Callable[[int], None] | None = None
    refuse: dict[str, int] = field(default_factory=dict)  # "POST /users" -> status
    lose_answer: set[str] = field(default_factory=set)  # names created, but the answer is lost
    _polls: dict[str, int] = field(default_factory=dict)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def writes(self) -> list[tuple[str, str]]:
        return [entry for entry in self.log if entry[0] != "GET"]

    # --- routing -----------------------------------------------------------------------------

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.log.append((request.method, request.url.path))
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return _problem(401, "authentication is required")
        path = request.url.path.removeprefix(PREFIX)
        method = request.method
        if path == "/auth/me":
            return httpx2.Response(
                200,
                json={"user": {**ADMIN, "role": self.role}, "token_scope": self.scope},
            )
        if method != "GET" and self.scope != "read_write":
            return _problem(403, "this API token may only read")
        body = (
            json.loads(request.content)
            if request.content and "json" in request.headers.get("content-type", "")
            else {}
        )
        simple = {
            "/users": self.users,
            "/contacts": self.contacts,
            "/document-types": self.document_types,
            "/tags": self.tags,
            "/fields": self.fields,
            "/spaces": self.spaces,
        }
        if path in simple:
            store = simple[path]
            if path == "/tags" and method == "GET" and "scope" in request.url.params:
                scope = request.url.params["scope"]
                store = {k: v for k, v in store.items() if v.get("scope", "document") == scope}
            return self._collection(path, store, method, body)
        if found := re.fullmatch(r"/(contacts|document-types|tags)/([^/]+)", path):
            store = {
                "contacts": self.contacts,
                "document-types": self.document_types,
                "tags": self.tags,
            }[found[1]]
            if method == "PATCH" and found[2] in store:
                for key in ("group_ids", "parent_id", "name"):
                    if key in body:
                        store[found[2]][key] = body[key]
                return httpx2.Response(200, json=store[found[2]])
        if found := re.fullmatch(r"/(users|fields)/([^/]+)", path):
            store = self.users if found[1] == "users" else self.fields
            if method == "PATCH" and found[2] in store:
                if "active" in body:
                    store[found[2]]["active"] = body["active"]
                if "choices" in body:
                    store[found[2]]["choices"] = body["choices"]
                return httpx2.Response(200, json=store[found[2]])
        if found := re.fullmatch(r"/spaces/([^/]+)/members/([^/]+)", path):
            space = self.spaces[found[1]]
            if found[2] == space["personal_of"] and body.get("role") != "edit":
                return _problem(422, "the user of a personal space edits it")
            if found[2] not in self.users or not self.users[found[2]]["active"]:
                return _problem(404, "user not found")
            space["members"] = [m for m in space["members"] if m["user_id"] != found[2]]
            space["members"].append({"user_id": found[2], "role": body["role"]})
            return httpx2.Response(200, json=space)
        if path == "/documents" and method == "POST":
            return self._upload(request)
        if path == "/documents" and method == "GET":
            items = list(self.documents.values())
            return httpx2.Response(200, json={"items": items, "next_cursor": None})
        if found := re.fullmatch(r"/documents/([^/]+)(/[a-z-]+)?", path):
            document = self.documents.get(found[1])
            if document is None:
                return _problem(404, "document not found")
            return self._document(document, method, found[2] or "", request, body)
        return _problem(404, f"unknown {method} {path}")

    def _collection(
        self, path: str, store: dict[str, dict[str, Any]], method: str, body: dict[str, Any]
    ) -> httpx2.Response:
        if method == "GET":
            return httpx2.Response(200, json=list(store.values()))
        if method != "POST":
            return _problem(405, "method not allowed")
        if f"POST {path}" in self.refuse:
            return _problem(self.refuse[f"POST {path}"], "refused")
        name = str(body.get("username") or body.get("name"))
        scope = body.get("scope", "document")  # tags: names are unique per scope
        if any(
            (item.get("username") or item["name"]).casefold() == name.casefold()
            and (path != "/tags" or item.get("scope", "document") == scope)
            and (path != "/spaces" or item.get("personal_of") is None)
            for item in store.values()
        ):
            return _problem(409, f"{name} exists")
        id = uuid4().hex
        if path == "/users":
            item = {"id": id, "username": name, "role": "user", "active": True}
            self.spaces[f"personal:{id}"] = _personal(id)
        elif path == "/spaces":
            members = body.get("members") or [{"user_id": ADMIN["id"], "role": "edit"}]
            for member in members:
                user = self.users.get(member["user_id"])
                if user is None or not user["active"]:
                    return _problem(404, "user not found")
            if not any(member["role"] == "edit" for member in members):
                return _problem(422, "a space keeps one editor")
            item = {"id": id, "name": name, "personal_of": None, "members": list(members)}
        elif path == "/fields":
            item = {
                "id": id,
                "name": name,
                "data_type": body["data_type"],
                "choices": body.get("choices", []),
                "document_type_ids": None,
            }
        elif path == "/tags":
            item = {
                "id": id,
                "name": name,
                "scope": body.get("scope", "document"),
                "parent_id": body.get("parent_id"),
            }
        elif path in ("/contacts", "/document-types"):
            item = {"id": id, "name": name, "group_ids": []}
        else:
            item = {"id": id, "name": name}
        store[id] = item
        if name in self.lose_answer:
            self.lose_answer.discard(name)
            return _problem(503, "lost")
        return httpx2.Response(201, json=item)

    # --- documents ---------------------------------------------------------------------------

    def _upload(self, request: httpx2.Request) -> httpx2.Response:
        message = BytesParser(policy=HTTP).parsebytes(
            b"Content-Type: "
            + request.headers["content-type"].encode()
            + b"\r\n\r\n"
            + request.content
        )
        fields: dict[str, str] = {}
        content = b""
        filename = ""
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name == "file":
                filename = part.get_filename() or ""
                content = cast("bytes", part.get_payload(decode=True))
            else:
                fields[str(name)] = cast("bytes", part.get_payload(decode=True)).decode()
        self.uploads.append({**fields, "filename": filename})
        status, times = self.errors.get(filename, (0, 0))
        if times > 0:
            self.errors[filename] = (status, times - 1)
            return _problem(status, f"injected failure {status}")
        uploader = fields.get("uploaded_by", ADMIN["id"])
        if uploader in self.users and not self.users[uploader]["active"]:
            return _problem(404, "user not found")
        space = fields.get("space_id", f"personal:{uploader}")
        sha256 = hashlib.sha256(content).hexdigest()
        roles = {
            id: member["role"]
            for id, item in self.spaces.items()
            for member in item["members"]
            if member["user_id"] == uploader
        }

        def readable(existing: dict[str, Any]) -> bool:
            role = roles.get(existing["space_id"])
            return role == "edit" or (role == "read" and existing["lane"] == "green")

        for existing in self.documents.values():
            blocks = existing["space_id"] == space or readable(existing)
            if existing["sha256"] == sha256 and blocks:
                response = _problem(409, "Lekto has this file already")
                body = json.loads(response.content)
                body["existing_document_id"] = existing["id"]
                return httpx2.Response(409, json=body)
        if not content.startswith(b"%PDF") and not content.startswith(b"\xff\xd8"):
            return _problem(415, "unsupported file type")
        metadata = json.loads(fields.get("metadata", "{}"))
        id = uuid4().hex
        self.documents[id] = {
            "id": id,
            "title": metadata.get("title", filename),
            "original_filename": filename,
            "media_type": "application/pdf",
            "channel": fields.get("channel", "api"),
            "sha256": sha256,
            "uploaded_by": uploader,
            "space_id": space,
            "contact_id": metadata.get("contact_id"),
            "document_type_id": metadata.get("document_type_id"),
            "topic_id": None,
            "tag_ids": sorted(metadata.get("tag_ids", [])),
            "document_date": metadata.get("document_date"),
            "fields": metadata.get("fields", {}),
            "_metadata": fields.get("metadata", "{}"),
            "created_at": metadata.get("created_at") or datetime.now(UTC).isoformat(),
            "lane": None,
            "processing": {"status": "processing", "run": 1, "nodes": _nodes({"receive": "ok"})},
            "_lane": "yellow" if metadata.get("review") else self.lanes.get(filename, "green"),
            "_log": [
                {
                    "node": "receive",
                    "outcome": "ok",
                    "reason": None,
                    "output": {"imported": metadata} if metadata else {},
                }
            ],
            "_text": self.texts.get(filename, f"{metadata.get('title', filename)} text " * 50),
        }
        if self.after_upload is not None:
            self.after_upload(len(self.uploads))
        return httpx2.Response(202, json={"id": id, "status_url": f"{PREFIX}/documents/{id}"})

    def _document(
        self,
        document: dict[str, Any],
        method: str,
        sub: str,
        request: httpx2.Request,
        body: dict[str, Any],
    ) -> httpx2.Response:
        if sub == "/log" and method == "GET":
            return httpx2.Response(200, json=document["_log"])
        if sub == "/text" and method == "GET":
            text = document["_text"]
            return httpx2.Response(
                200,
                json={"text": text, "offset": 0, "total_length": len(text), "next_offset": None},
            )
        if sub == "/reading" and method == "GET":
            advice = self.advice.get(document["original_filename"])
            return httpx2.Response(200, json={"vision": False, "pages": [], "advice": advice})
        if sub == "/move" and method == "POST":
            if any(
                other["space_id"] == body["space_id"] and other["sha256"] == document["sha256"]
                for other in self.documents.values()
                if other is not document
            ):
                return _problem(409, "the space holds this file already")
            document["space_id"] = body["space_id"]
            return httpx2.Response(204)
        if sub in ("", "/dry-run") and method in ("PATCH", "POST"):
            if request.url.params.get("confirm") != "false" or self.role != "admin":
                return _problem(403, "only admins align documents")
            if document["channel"] != "migration":
                return _problem(422, "only a document of the channel 'migration'")
            after = self._public(document) | {k: v for k, v in body.items() if k != "fields"}
            fields = dict(document["fields"])
            for key, value in (body.get("fields") or {}).items():
                if value is None:
                    fields.pop(key, None)
                else:
                    fields[key] = value
            after["fields"] = fields
            if "tag_ids" in body:
                after["tag_ids"] = sorted(body["tag_ids"])
            if sub == "/dry-run":
                return httpx2.Response(200, json={"document": after, "changed": [], "rules": []})
            self.aligned.append((document["id"], body))
            document.update(after)
            return httpx2.Response(200, json={**after, "rules": []})
        if sub == "" and method == "GET":
            return httpx2.Response(200, json=self._poll(document))
        return _problem(404, f"unknown {method} {sub}")

    def _public(self, document: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in document.items() if not key.startswith("_")}

    def _poll(self, document: dict[str, Any]) -> dict[str, Any]:
        id = document["id"]
        self._polls[id] = self._polls.get(id, 0) + 1
        if self.ticks >= 0 and self._polls[id] > self.ticks:
            lane = document["_lane"]
            document["lane"] = lane
            if lane == "green":
                document["processing"] = {
                    "status": "completed",
                    "run": 1,
                    "nodes": _nodes(dict.fromkeys(NODES, "ok")),
                }
            elif lane == "yellow":
                outcomes = dict.fromkeys(NODES[:-1], "ok") | {"judge": "uncertain"}
                document["processing"] = {"status": "review", "run": 1, "nodes": _nodes(outcomes)}
                reasons = [r["reason"] for r in json.loads(document["_metadata"]).get("review", [])]
                document["_log"].append(
                    {"node": "judge", "outcome": "uncertain", "reason": "; ".join(reasons)}
                )
            else:
                document["processing"] = {
                    "status": "failed",
                    "run": 1,
                    "nodes": _nodes(
                        {"receive": "ok", "ocr": "ok", "pages": "ok", "parse": "failed"}
                    ),
                }
                document["_log"].append(
                    {"node": "parse", "outcome": "failed", "reason": "no text recognised"}
                )
        return {key: value for key, value in document.items() if not key.startswith("_")}


NODES = (
    "receive",
    "ocr",
    "pages",
    "parse",
    "signal_llm",
    "signal_classifier",
    "signal_neighbours",
    "signal_facts",
    "judge",
    "fields",
    "apply_rules",
    "file",
)


def _nodes(outcomes: dict[str, str]) -> list[dict[str, Any]]:
    """`processing.nodes` as the API answers it: done nodes with their outcome, the rest
    waiting."""
    return [
        {
            "node": node,
            "status": "done" if node in outcomes else "waiting",
            "outcome": outcomes.get(node),
            "started_at": None,
            "finished_at": None,
        }
        for node in NODES
    ]


def _personal(user_id: str) -> dict[str, Any]:
    return {
        "id": f"personal:{user_id}",
        "name": "Personal",
        "personal_of": user_id,
        "members": [{"user_id": user_id, "role": "edit"}],
    }


def _problem(status: int, detail: str) -> httpx2.Response:
    return httpx2.Response(
        status,
        json={"title": "error", "status": status, "detail": detail},
        headers={"content-type": "application/problem+json"},
    )
