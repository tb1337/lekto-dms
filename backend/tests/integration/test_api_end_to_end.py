"""Milestone M3 end to end: documents arrive through the REST API, the worker processes them
with OCRmyPDF and the layout text, progress arrives as server-sent events. Real API server
(Uvicorn) and worker, in two set-ups: SQLite with the filesystem, Postgres with S3 (Garage)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import httpx2
import pytest

from lekto.adapters.inbound.rest import PREFIX
from lekto.adapters.outbound.ocrmypdf import OcrmypdfEngine
from lekto.adapters.outbound.pdfium import LayoutParser, PdfiumPageRenderer
from lekto.adapters.outbound.sql import Database
from lekto.core.domain.spaces import SpaceRole
from lekto.core.domain.users import User
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.ocr import OcrResult, VisionModel
from lekto.core.services.objects import archive_key, preview_key, structure_key, text_key
from tests import builders, probes
from tests.api import Stream, auth, listen, until
from tests.builders import DEFAULT_SETTINGS, SAMPLES
from tests.integration.e2e import DOCUMENTS, TUNING, System, running_system

pytestmark = probes.requires_ocr


class Interruptible:
    """OCR that can be made to time out, to break a node on purpose."""

    def __init__(self, engine: OcrmypdfEngine) -> None:
        self.engine = engine
        self.broken = False

    @property
    def vision(self) -> VisionModel | None:
        return self.engine.vision

    async def make_archive(
        self, source: Path, target: Path, *, media_type: str, vision: bool = False
    ) -> OcrResult:
        if self.broken:
            raise TimeoutError("ocrmypdf did not finish within 0.001 s")
        return await self.engine.make_archive(source, target, media_type=media_type, vision=vision)


class ApiSystem(System):
    processing = 180.0  # OCRmyPDF takes its time

    async def upload_sample(self, user: User, sample: str, **data: str) -> httpx2.Response:
        files = {"file": (sample, (SAMPLES / sample).read_bytes(), "application/octet-stream")}
        return await self.client.post(DOCUMENTS, files=files, data=data, headers=auth(user))


@pytest.fixture
def ocr() -> Interruptible:
    return Interruptible(
        OcrmypdfEngine(
            languages=["deu", "eng"],
            timeout=timedelta(minutes=5),
            vision_timeout=DEFAULT_SETTINGS.vlm_timeout,
        )
    )


@pytest.fixture
async def system(
    stores: tuple[Database, ObjectStore], ocr: Interruptible
) -> AsyncIterator[ApiSystem]:
    settings = TUNING.model_copy(update={"node_max_attempts": 1})  # a broken node fails at once
    async with running_system(
        ApiSystem, stores, settings, ocr=ocr, parser=LayoutParser(), pages=PdfiumPageRenderer()
    ) as system:
        yield system


async def test_documents_go_through_the_api(
    system: ApiSystem, ocr: Interruptible, object_store: ObjectStore
) -> None:
    owner, reader, stranger = await system.user(), await system.user(), await system.user()
    async with system.container.unit_of_work() as uow:
        shared = builders.space(owner, "Household")
        shared.set_member(reader.id, SpaceRole.READ)
        await uow.spaces.add(shared)
        await uow.commit()

    streams = {user.id: Stream() for user in (owner, reader, stranger)}
    listeners = [
        asyncio.create_task(listen(system.client, user, streams[user.id]))
        for user in (owner, reader, stranger)
    ]
    for stream in streams.values():
        await asyncio.wait_for(stream.ready.wait(), timeout=10)

    # A scan into the shared space and a photo into the owner's default space.
    scan = await system.upload_sample(owner, "scan.pdf", space_id=str(shared.id))
    photo = await system.upload_sample(owner, "photo.jpg")
    assert (scan.status_code, photo.status_code) == (202, 202)
    ids = {"scan": scan.json()["id"], "photo": photo.json()["id"]}
    for name, key in ids.items():
        status = await system.settled(owner, key)
        assert status["lane"] == "green", (name, status)
        assert await object_store.get(archive_key(key))
        assert (await object_store.get(preview_key(key)))[8:12] == b"WEBP"
        text = " ".join((await object_store.get(text_key(key))).decode().split())
        assert "Rechnung Nummer 4711" in text, name
        assert await object_store.exists(structure_key(key))

    # A duplicate of the same owner is rejected.
    again = await system.upload_sample(owner, "scan.pdf")
    assert again.status_code == 409
    assert again.json()["existing_document_id"] == ids["scan"]

    # Progress by SSE, only for those who may read the document.
    own = streams[owner.id]
    await until(lambda: own.types().count("document.lane_changed") == 2, timeout=10)
    assert own.documents() == set(ids.values())
    lanes = {e["document_id"]: e["new"] for e in own.events if e["type"] == "document.lane_changed"}
    assert lanes == dict.fromkeys(ids.values(), "green")
    shared_stream = streams[reader.id]
    await until(lambda: "document.lane_changed" in shared_stream.types(), timeout=10)
    assert shared_stream.documents() == {ids["scan"]}
    assert "document.received" not in shared_stream.types()  # hidden while processing
    assert streams[stranger.id].events == []

    # A node broken on purpose fails, is retried alone, and reprocessing works.
    ocr.broken = True
    born_digital = await system.upload_sample(owner, "text.pdf")
    url, id = born_digital.json()["status_url"], born_digital.json()["id"]
    failed = await system.settled(owner, id, idle=True)
    outcomes = {n["node"]: n["outcome"] for n in failed["processing"]["nodes"]}
    assert (failed["lane"], outcomes["ocr"]) == ("red", "failed")
    ocr.broken = False
    retried = await system.client.post(f"{url}/retry", headers=auth(owner))
    assert retried.status_code == 202
    assert (await system.settled(owner, id))["lane"] == "green"
    reprocess = await system.client.post(
        f"{url}/reprocess", json={"from_node": "parse"}, headers=auth(owner)
    )
    assert reprocess.status_code == 202
    assert (await system.settled(owner, id))["lane"] == "green"
    log = (await system.client.get(f"{url}/log", headers=auth(owner))).json()
    runs = [(entry["node"], entry["run"], entry["outcome"]) for entry in log]
    # The pages run beside the OCR: in the first run if they got there before it failed, else
    # after the retry, before or after the OCR. Their place in the log is a matter of timing.
    # The signals, too, run side by side; the judge comes after all of them.
    chain = [run for run in runs if run[0] != "pages"]
    assert chain[:4] == [
        ("receive", 1, "ok"),
        ("ocr", 1, "failed"),
        ("ocr", 2, "ok"),
        ("parse", 2, "ok"),
    ]
    signals = {"signal_llm", "signal_classifier", "signal_neighbours", "signal_facts"}
    assert {node for node, _, _ in chain[4:8]} == signals
    assert chain[8] == ("judge", 2, "ok")
    assert [outcome for node, _, outcome in runs if node == "pages"][:1] == ["ok"]
    assert ("parse", 3, "ok") in runs

    health = await system.client.get(f"{PREFIX}/health")
    assert health.json()["status"] == "ok"
    for listener in listeners:
        listener.cancel()
