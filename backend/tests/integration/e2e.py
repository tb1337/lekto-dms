"""What the end-to-end tests share: the running system, a real API server (Uvicorn) and worker
as the commands start them over a database and an object store, and fakes for OCR and parsing
that bring the text of a test."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar

import httpx2

from lekto.adapters.inbound.rest import PREFIX
from lekto.adapters.outbound.sql import Database, SqlEventBus, SqlUnitOfWorkFactory, SqlWakeup
from lekto.composition.api import build_app
from lekto.composition.container import Container, Services, build_memory_container, build_services
from lekto.composition.settings import Settings
from lekto.composition.worker import build_worker
from lekto.core.domain.users import Role, User
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.ocr import OcrResult
from lekto.core.ports.parser import ParseResult
from tests import builders
from tests.api import auth, issue_token, serving, until

DOCUMENTS = f"{PREFIX}/documents"
POLL = timedelta(milliseconds=50)
TUNING = Settings.model_construct(worker_poll_interval=POLL, events_poll_interval=POLL)
"""The shipped defaults, with a worker and an event dispatch that look for work often."""


class TextOcr:
    """OCR that keeps the file as it is: the archive holds the text line for the parser."""

    vision = None

    async def make_archive(
        self, source: Path, target: Path, *, media_type: str, vision: bool = False
    ) -> OcrResult:
        target.write_bytes(source.read_bytes())
        return OcrResult(pages=1, engine="text-ocr 1", pdfa=True)


class TextParser:
    """A parser that takes the text of a document from a line of the file: `%text: …`."""

    async def parse(self, source: Path, *, text: Path, structure: Path) -> ParseResult:
        data = source.read_bytes()
        content = next(
            line.removeprefix(b"%text: ").decode()
            for line in data.splitlines()
            if line.startswith(b"%text: ")
        )
        text.write_text(content, encoding="utf-8")
        structure.write_text(json.dumps({"text": content}), encoding="utf-8")
        return ParseResult(pages=1, parser="text-parser 1")


def text_pdf(text: str) -> bytes:
    """A file that `TextOcr` and `TextParser` take for a PDF with `text`."""
    return f"%PDF-1.7\n%text: {text}\n%%EOF\n".encode()


@dataclass
class System:
    """The running system: its container and services, a client of its API, its database."""

    container: Container
    services: Services
    client: httpx2.AsyncClient
    database: Database

    processing: ClassVar[float] = 60.0  # seconds a document may take

    async def user(self, role: Role = Role.USER) -> User:
        """A user with default space and an API token (`auth`)."""
        user = await builders.seed_user(self.container.unit_of_work, role=role)
        await issue_token(self.services.auth, user)
        return user

    async def post(self, user: User, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """Create a resource below the API prefix: expect 201, return the body."""
        response = await self.client.post(f"{PREFIX}{path}", json=body, headers=auth(user))
        assert response.status_code == 201, response.text
        created: dict[str, Any] = response.json()
        return created

    async def upload(self, user: User, text: str, **data: str) -> str:
        """Upload a `text_pdf` as `document.pdf`; the new document's id."""
        files = {"file": ("document.pdf", text_pdf(text), "application/pdf")}
        response = await self.client.post(DOCUMENTS, files=files, data=data, headers=auth(user))
        assert response.status_code == 202, response.text
        return str(response.json()["id"])

    async def document(self, user: User, id: str) -> dict[str, Any]:
        response = await self.client.get(f"{DOCUMENTS}/{id}", headers=auth(user))
        assert response.status_code == 200, response.text
        document: dict[str, Any] = response.json()
        return document

    async def settled(self, user: User, id: str, *, idle: bool = False) -> dict[str, Any]:
        """The document once processing has ended (it has a lane); with `idle`, also once no
        node is running any more: a node that fails ends the run red while the nodes beside
        it (the page images beside OCR) still finish, and a retry meanwhile races their
        result."""
        document: dict[str, Any] = {}

        async def ended() -> bool:
            document.update(await self.document(user, id))
            running = any(node["status"] == "running" for node in document["processing"]["nodes"])
            return document["lane"] is not None and not (idle and running)

        await until(ended, self.processing, every=0.2, what=f"the processing of {id}")
        return document


@asynccontextmanager
async def running_system[S: System](
    kind: type[S],
    stores: tuple[Database, ObjectStore],
    settings: Settings = TUNING,
    **adapters: Any,
) -> AsyncIterator[S]:
    """The API server and the worker over the database and the object store of `stores`; the
    other adapters are the memory container's unless `adapters` replaces them. Classification
    is skipped. The worker has to shut down cleanly."""
    database, object_store = stores
    wakeup = SqlWakeup(database)
    container = replace(
        build_memory_container(),
        unit_of_work=SqlUnitOfWorkFactory(database),
        event_bus=SqlEventBus(database, retry=builders.EVENT_RETRY),
        wakeup=wakeup,  # the memory container's would signal commits of another database
        object_store=object_store,
        **adapters,
    )
    services = build_services(container, settings)
    builders.skip_classification(services.pipeline)
    worker = build_worker(container, settings, services)
    app = build_app(container, settings, services)
    running = asyncio.create_task(worker.run())
    try:
        async with serving(app) as url, httpx2.AsyncClient(base_url=url, timeout=30) as client:
            yield kind(container, services, client, database)
    finally:
        worker.stop()
        await asyncio.wait_for(running, timeout=60)
        await wakeup.aclose()
