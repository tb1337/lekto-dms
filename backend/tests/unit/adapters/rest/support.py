"""What the REST tests share: the app and its client, requests, uploads and the scene of the
permission matrix (its actors and documents: `test_permission_matrix`). The MCP tests use them too.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2
from fastapi import FastAPI

from lekto.adapters.inbound.mcp import McpEndpoint
from lekto.adapters.inbound.rest import MCP_PATH, PREFIX, create_app
from lekto.adapters.inbound.rest.auth import CSRF_HEADER
from lekto.adapters.outbound.memory import ManualClock
from lekto.composition.api import api_context
from lekto.composition.container import Container, Services
from lekto.core.domain.identity import TokenScope
from lekto.core.domain.ids import DocumentId
from lekto.core.domain.pipeline import Node
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import Role, User
from lekto.core.services.objects import archive_key, preview_key
from tests import builders
from tests.api import auth, bearer, issue_token
from tests.builders import PASSWORD, SAMPLES, UNCERTAIN, Returns

MAX_UPLOAD = 1024 * 1024


def make_app(
    container: Container,
    services: Services,
    *,
    max_upload: int = MAX_UPLOAD,
    poll: timedelta = timedelta(milliseconds=20),
    cookie_secure: bool = True,
    recheck: timedelta = timedelta(seconds=30),
    mcp: bool = False,
    text_max: int = builders.DEFAULT_SETTINGS.mcp_text_max,
    ui_directory: Path | None = None,
) -> FastAPI:
    """The app as `composition.api` builds it from the shipped settings, with what a test
    changes."""
    context = replace(
        api_context(container, builders.DEFAULT_SETTINGS, services),
        max_upload_size=max_upload,
        events_poll_interval=poll,
        cookie_secure=cookie_secure,
        stream_recheck_interval=recheck,
        text_max=text_max,
        ui_directory=ui_directory,
    )
    mounts = [McpEndpoint(context, path=MCP_PATH)] if mcp else []
    return create_app(context, mounts)


@dataclass
class Session:
    """A signed-in browser: its client holds the cookie; `headers` carry the CSRF token."""

    client: httpx2.AsyncClient
    csrf_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {CSRF_HEADER: self.csrf_token}


@dataclass
class Api:
    container: Container
    services: Services
    app: FastAPI
    client: httpx2.AsyncClient
    clock: ManualClock

    async def user(self, name: str | None = None, role: Role = Role.USER) -> User:
        """A user with default space, password `PASSWORD` and an API token (`auth`)."""
        container = self.container
        user = await builders.seed_account(
            container.unit_of_work, container.password_hasher, name, role=role
        )
        await issue_token(self.services.auth, user)
        return user

    async def admin(self, name: str | None = None) -> User:
        return await self.user(name, Role.ADMIN)

    def new_client(self) -> httpx2.AsyncClient:
        transport = httpx2.ASGITransport(app=self.app)
        return httpx2.AsyncClient(transport=transport, base_url="https://lekto")

    @asynccontextmanager
    async def sign_in(self, user: User, password: str = PASSWORD) -> AsyncIterator[Session]:
        """A new client (browser) signed in as `user`."""
        async with self.new_client() as client:
            response = await client.post(
                f"{PREFIX}/auth/login", json={"username": user.username, "password": password}
            )
            assert response.status_code == 200, response.text
            yield Session(client, response.json()["csrf_token"])

    async def drain(self) -> None:
        await builders.drain(self.services.pipeline)


DOCUMENTS = f"{PREFIX}/documents"
FILENAME = "Bill 2026.pdf"  # the name `upload` gives a file

type Files = dict[str, tuple[str, bytes, str]]


async def post(api: Api, path: str, body: Any, headers: dict[str, str]) -> Any:
    """Create a resource below the API prefix: expect 201, return the body."""
    response = await api.client.post(f"{PREFIX}{path}", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def file_part(filename: str, content: bytes) -> Files:
    """The file part of an upload; its content type is not read, the content decides."""
    return {"file": (filename, content, "application/octet-stream")}


def sample_file(name: str = "scan.pdf") -> Files:
    """A sample of the processing contracts as the file part of an upload, under its name."""
    return file_part(name, (SAMPLES / name).read_bytes())


def unique_pdf(name: str) -> bytes:
    """The sample scan with a comment, so that every upload is a file of its own."""
    return (SAMPLES / "scan.pdf").read_bytes().rstrip() + f"\n%{name}\n%%EOF\n".encode()


async def upload(
    api: Api,
    headers: dict[str, str],
    *,
    content: bytes | None = None,
    filename: str = FILENAME,
    space: str | None = None,
    drain: bool = True,
) -> str:
    """Upload `content` (default: the sample scan) and let the pipeline run unless `drain` is
    false; the new document's id."""
    if content is None:
        content = (SAMPLES / "scan.pdf").read_bytes()
    data = {} if space is None else {"space_id": space}
    response = await api.client.post(
        DOCUMENTS, files=file_part(filename, content), data=data, headers=headers
    )
    assert response.status_code == 202, response.text
    if drain:
        await api.drain()
    return str(response.json()["id"])


ACTORS = [
    "owner",
    "reader",
    "writer",
    "stranger",
    "admin",
    "read_token",
    "expired_token",
    "revoked_token",
    "deactivated",
    "deactivated_admin",
]
DENIED = {"expired_token": 401, "revoked_token": 401, "deactivated": 401, "deactivated_admin": 401}


@dataclass
class Scene:
    api: Api
    headers: dict[str, dict[str, str]]
    owner: User
    shared: Space
    own_space: Space  # another space of the owner, target for moving
    green: str
    yellow: str
    processing: str
    contact: str

    def document(self, which: str) -> str:
        return str(getattr(self, which))


async def build_scene(api: Api) -> Scene:
    owner, reader, writer = await api.user("owner"), await api.user("reader"), await api.user()
    stranger, admin = await api.user("stranger"), await api.admin("admin")
    gone = await api.user("deactivated")
    retired = await api.admin("retired")
    spaces = api.services.spaces
    shared = await spaces.create(owner.id, "Shared")
    for user, level in [(reader, SpaceRole.READ), (writer, SpaceRole.EDIT)]:
        await spaces.set_member(owner.id, shared.id, user.id, level)
    await spaces.set_member(owner.id, shared.id, gone.id, SpaceRole.EDIT)
    own_space = await spaces.create(owner.id, "Private")

    async def put(name: str, *, drain: bool = True) -> str:
        return await upload(
            api,
            auth(owner),
            content=unique_pdf(name),
            filename=f"{name}.pdf",
            space=str(shared.id),
            drain=drain,
        )

    green = await put("green")
    yellow = await put("yellow")
    await api.services.pipeline.reprocess_from(owner.id, DocumentId(UUID(yellow)), Node.JUDGE)
    pipeline = api.services.pipeline
    # yellow: the classification is uncertain
    judge = pipeline.replace_executor(Node.JUDGE, Returns(UNCERTAIN))
    await api.drain()
    pipeline.replace_executor(Node.JUDGE, judge)
    processing = await put("new", drain=False)
    for id in (green, yellow):
        document = DocumentId(UUID(id))
        await api.container.object_store.put(archive_key(document), b"%PDF", content_type="x")
        await api.container.object_store.put(preview_key(document), b"RIFF", content_type="x")
    contact = await api.services.master_data.create_contact(admin.id, "ACME")

    _, read_token = await api.services.auth.create_api_token(owner.id, "r", TokenScope.READ)
    _, expired = await api.services.auth.create_api_token(
        owner.id, "e", TokenScope.READ_WRITE, expires_at=api.clock.now() + timedelta(seconds=1)
    )
    revoked_token, revoked = await api.services.auth.create_api_token(
        owner.id, "x", TokenScope.READ_WRITE
    )
    await api.services.auth.revoke_api_token(owner.id, revoked_token.id)
    api.clock.advance(timedelta(seconds=1))
    await api.services.users.update(admin.id, gone.id, active=False)
    await api.services.users.update(admin.id, retired.id, active=False)
    headers = {
        "owner": auth(owner),
        "reader": auth(reader),
        "writer": auth(writer),
        "stranger": auth(stranger),
        "admin": auth(admin),
        "read_token": bearer(read_token),
        "expired_token": bearer(expired),
        "revoked_token": bearer(revoked),
        "deactivated": auth(gone),
        "deactivated_admin": auth(retired),
    }
    return Scene(api, headers, owner, shared, own_space, green, yellow, processing, str(contact.id))


async def indexed_scene(api: Api) -> Scene:
    """The scene with its documents in the search index."""
    scene = await build_scene(api)
    indexing = api.services.indexing
    assert indexing is not None
    await indexing.reconcile()
    await builders.drain(indexing)
    return scene
