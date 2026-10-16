"""Reading a document with the vision language model: only when a person asks, from OCR on,
logged with what was sent; and the advice to ask for it."""

from datetime import timedelta
from pathlib import Path

import pytest

from papiq.adapters.outbound.memory import FAKE_VISION, FakeOcr, FakePageRenderer, FakeParser
from papiq.adapters.outbound.memory.processing import FAKE_READING
from papiq.core.domain.documents import Document
from papiq.core.domain.errors import (
    InvalidTransitionError,
    LanguageModelError,
    NotFoundError,
)
from papiq.core.domain.pipeline import Lane, Node, NodeRun, Outcome, ProcessingStatus
from papiq.core.domain.reading import PageReading, VisionAdvice
from papiq.core.domain.users import Role, User
from papiq.core.ports import OcrResult
from papiq.core.services.nodes import NO_VISION_MODEL, OcrNode, PagesNode, ParseNode
from papiq.core.services.objects import archive_key, exchanges_key, original_key
from papiq.core.services.pipeline import PipelineService
from tests.builders import incoming
from tests.contracts.processing import SAMPLES
from tests.unit.services.conftest import World


def pipeline(world: World, ocr: FakeOcr, text: str = "Rechnung") -> PipelineService:
    store = world.object_store
    return world.pipeline(
        {
            Node.OCR: OcrNode(store, ocr),
            Node.PAGES: PagesNode(store, FakePageRenderer()),
            Node.PARSE: ParseNode(store, FakeParser(text)),
        },
        vision=ocr.vision,
    )


async def ingest(
    world: World, service: PipelineService, sample: str = "scan.pdf"
) -> tuple[User, Document]:
    owner = await world.user()
    data = (SAMPLES / sample).read_bytes()
    document = await service.receive(owner.id, incoming(data), filename=sample)
    await world.drain(service)
    return owner, await world.documents.get(owner.id, document.id)


async def ocr_runs(world: World, owner: User, document: Document) -> list[NodeRun]:
    log = await world.documents.processing_log(owner.id, document.id)
    return [entry for entry in log if entry.node is Node.OCR]


async def test_the_model_reads_only_when_a_person_asks(world: World) -> None:
    ocr = FakeOcr(vision=FAKE_VISION)
    service = pipeline(world, ocr)
    owner, document = await ingest(world, service)
    assert (document.processing.vision, ocr.vision_calls) == (False, [])

    asked = await service.read_with_vision(owner.id, document.id)
    assert asked.processing.vision
    assert asked.processing.run == document.processing.run + 1
    assert asked.processing.status is ProcessingStatus.PROCESSING
    await world.drain(service)
    document = await world.documents.get(owner.id, document.id)
    assert document.processing.status is ProcessingStatus.COMPLETED
    assert len(ocr.vision_calls) == 1

    _, read = await ocr_runs(world, owner, document)
    assert read.run == asked.processing.run
    assert read.result.outcome is Outcome.OK
    assert read.result.input == {"original": original_key(document.sha256), "vision": True}
    assert read.result.output == {
        "archive": archive_key(document.id),
        "pages": 1,
        "pdfa": True,
        "readings": [FAKE_READING.to_json()],
        "vision": {
            "model": "fake-vlm",
            "endpoint": "vlm.example:443",
            "prompt": "read-fake",
            "calls": 1,
        },
        # Per call, as the model nodes log theirs.
        "tokens": [
            {
                "prompt": 1500,
                "completion": 100,
                "usage": {"prompt_tokens": 1500, "completion_tokens": 100},
            }
        ],
    }
    assert read.result.reason == (
        "every page was read by the vision language model fake-vlm (vlm.example:443)"
    )
    assert read.result.model_version == "fake-ocr 1, vision language model fake-vlm"
    # What was sent is kept like the language model's prompts.
    assert await world.object_store.exists(exchanges_key(document.id, Node.OCR))
    (exchange,) = await world.documents.exchanges(owner.id, document.id, Node.OCR)
    assert exchange.run == asked.processing.run
    (call,) = exchange.calls
    assert (call.model, call.usage["prompt_tokens"]) == ("fake-vlm", 1500)


async def test_reprocessing_reads_with_tesseract_again(world: World) -> None:
    ocr = FakeOcr(vision=FAKE_VISION)
    service = pipeline(world, ocr)
    owner, document = await ingest(world, service)
    await service.read_with_vision(owner.id, document.id)
    await world.drain(service)
    again = await service.reprocess_from(owner.id, document.id, Node.OCR)
    assert not again.processing.vision
    await world.drain(service)
    assert len(ocr.vision_calls) == 1
    *_, last = await ocr_runs(world, owner, document)
    assert "vision" not in last.result.output


class Flaky(FakeOcr):
    """The vision model fails once, then reads."""

    failures = 1

    async def make_archive(
        self, source: Path, target: Path, *, media_type: str, vision: bool = False
    ) -> OcrResult:
        if vision and self.failures:
            self.failures -= 1
            raise LanguageModelError("HTTP 502: the model is down")
        return await super().make_archive(source, target, media_type=media_type, vision=vision)


async def test_a_retry_after_the_model_failed_asks_it_again(world: World) -> None:
    ocr = Flaky(vision=FAKE_VISION)
    service = pipeline(world, ocr)
    owner, document = await ingest(world, service)
    await service.read_with_vision(owner.id, document.id)
    await world.drain(service)
    world.clock.advance(timedelta(minutes=10))
    await world.drain(service)
    document = await world.documents.get(owner.id, document.id)
    assert document.processing.status is ProcessingStatus.COMPLETED
    assert document.processing.vision
    assert len(ocr.vision_calls) == 1
    *_, last = await ocr_runs(world, owner, document)
    assert last.result.input["vision"] is True


async def test_without_a_model_nobody_can_ask_for_it(world: World) -> None:
    service = pipeline(world, FakeOcr())
    owner, document = await ingest(world, service)
    with pytest.raises(InvalidTransitionError, match="no vision language model is configured"):
        await service.read_with_vision(owner.id, document.id)


async def test_a_model_configured_away_fails_the_ocr(world: World) -> None:
    """Asked for while there was one; the worker that runs the OCR has none."""
    owner, document = await ingest(world, pipeline(world, FakeOcr(vision=FAKE_VISION)))
    await pipeline(world, FakeOcr(vision=FAKE_VISION)).read_with_vision(owner.id, document.id)
    without = pipeline(world, FakeOcr())
    await world.drain(without)
    document = await world.documents.get(owner.id, document.id)
    assert document.lane is Lane.RED
    *_, last = await ocr_runs(world, owner, document)
    assert (last.result.outcome, last.result.reason) == (Outcome.FAILED, NO_VISION_MODEL)


async def test_the_owner_and_admins_ask_for_the_model(world: World) -> None:
    service = pipeline(world, FakeOcr(vision=FAKE_VISION))
    _, document = await ingest(world, service)
    stranger = await world.user()
    with pytest.raises(NotFoundError):
        await service.read_with_vision(stranger.id, document.id)
    with pytest.raises(NotFoundError):
        await service.reading(stranger.id, document.id)
    admin = await world.user(role=Role.ADMIN)
    assert (await service.read_with_vision(admin.id, document.id)).processing.vision


async def test_no_text_advises_the_model(world: World) -> None:
    service = pipeline(world, FakeOcr(vision=FAKE_VISION), text="")
    owner, document = await ingest(world, service)
    assert document.lane is Lane.RED
    reading = await service.reading(owner.id, document.id)
    assert reading.advice is VisionAdvice.NO_TEXT
    assert (reading.vision, reading.pages, reading.poor) == (False, (FAKE_READING,), ())
    # Once the model has read it, reading again would change nothing.
    await service.read_with_vision(owner.id, document.id)
    await world.drain(service)
    after = await service.reading(owner.id, document.id)
    assert (after.vision, after.advice) == (True, None)


class PoorAndPlain(FakeOcr):
    """A poorly read page, and an archive that is not PDF/A: the document waits for a person."""

    async def make_archive(
        self, source: Path, target: Path, *, media_type: str, vision: bool = False
    ) -> OcrResult:
        await super().make_archive(source, target, media_type=media_type, vision=vision)
        readings = (
            PageReading(page=1, words=40, unsure=2),
            PageReading(page=2, words=50, unsure=9),
        )
        return OcrResult(pages=2, engine="fake-ocr 1", pdfa=False, readings=readings)


async def test_a_poorly_read_page_advises_the_model_while_a_person_must_look(
    world: World,
) -> None:
    service = pipeline(world, PoorAndPlain(vision=FAKE_VISION))
    owner, document = await ingest(world, service)
    assert document.lane is Lane.YELLOW
    reading = await service.reading(owner.id, document.id)
    assert reading.poor == (2,)
    assert reading.advice is VisionAdvice.POOR_PAGE


async def test_a_green_document_gets_no_advice(world: World) -> None:
    poor = FakeOcr([PageReading(page=1, words=50, unsure=20)], vision=FAKE_VISION)
    service = pipeline(world, poor)
    owner, document = await ingest(world, service)
    assert document.lane is Lane.GREEN
    reading = await service.reading(owner.id, document.id)
    assert (reading.poor, reading.advice) == ((1,), None)
