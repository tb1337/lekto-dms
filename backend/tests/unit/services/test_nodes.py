"""OCR, pages and parse nodes on the fakes: derivatives, outcomes, failures."""

import json
import tempfile
from pathlib import Path

import pytest

from papiq.adapters.outbound.memory import FakeOcr, FakePageRenderer, FakeParser
from papiq.adapters.outbound.memory.processing import FAKE_PDF, FAKE_READING
from papiq.core.domain.documents import Document
from papiq.core.domain.locations import Box
from papiq.core.domain.pipeline import Lane, Node, NodeRun, Outcome
from papiq.core.domain.reading import PageReading, PageWords, ReadWord, reading_from_json
from papiq.core.domain.users import User
from papiq.core.ports.ocr import OcrResult
from papiq.core.services.nodes import OcrNode, PagesNode, ParseNode, has_text
from papiq.core.services.objects import (
    archive_key,
    legacy_text_key,
    load_text,
    original_key,
    page_key,
    preview_key,
    reading_key,
    structure_key,
    text_key,
)
from papiq.core.services.pipeline import PipelineService
from tests.builders import SAMPLES, incoming
from tests.unit.services.support import World


class NotPdfa(FakeOcr):
    def __init__(self, note: str | None = None) -> None:
        super().__init__()
        self.note = note

    async def make_archive(
        self, source: Path, target: Path, *, media_type: str, vision: bool = False
    ) -> OcrResult:
        await super().make_archive(source, target, media_type=media_type)
        return OcrResult(pages=1, engine="fake-ocr 1", pdfa=False, note=self.note)


class Unsigned(FakeOcr):
    """PDF/A, but the original's signature is not in the archive."""

    async def make_archive(
        self, source: Path, target: Path, *, media_type: str, vision: bool = False
    ) -> OcrResult:
        await super().make_archive(source, target, media_type=media_type)
        return OcrResult(pages=1, engine="fake-ocr 1", pdfa=True, note="signature not carried")


def pipeline(
    world: World,
    *,
    ocr: FakeOcr | None = None,
    text: str = "Rechnung",
    pages: FakePageRenderer | None = None,
) -> PipelineService:
    store = world.object_store
    return world.pipeline(
        {
            Node.OCR: OcrNode(store, ocr or FakeOcr()),
            Node.PAGES: PagesNode(store, pages or FakePageRenderer()),
            Node.PARSE: ParseNode(store, FakeParser(text)),
        }
    )


async def ingest(world: World, service: PipelineService, sample: str) -> tuple[User, Document]:
    owner = await world.user()
    data = (SAMPLES / sample).read_bytes()
    document = await service.receive(owner.id, incoming(data), filename=sample)
    await world.drain(service)
    return owner, await world.documents.get(owner.id, document.id)


@pytest.mark.parametrize("sample", ["scan.pdf", "photo.jpg"])
async def test_ocr_pages_and_parse_store_their_derivatives(world: World, sample: str) -> None:
    owner, document = await ingest(world, pipeline(world, pages=FakePageRenderer(2)), sample)
    assert document.lane is Lane.GREEN
    assert document.page_count == 2
    store = world.object_store
    assert await store.get(archive_key(document.id)) == FAKE_PDF
    assert store.content_type(archive_key(document.id)) == "application/pdf"
    assert store.content_type(preview_key(document.id)) == "image/webp"
    for number in (1, 2):
        assert store.content_type(page_key(document.id, number)) == "image/webp"
    assert not await store.exists(page_key(document.id, 3))
    assert await store.get(text_key(document.id)) == b"Rechnung"
    assert store.content_type(structure_key(document.id)) == "application/json"

    log = {
        entry.node: entry for entry in await world.documents.processing_log(owner.id, document.id)
    }
    ocr, pages, parse = log[Node.OCR].result, log[Node.PAGES].result, log[Node.PARSE].result
    assert ocr.input == {"original": original_key(document.sha256)}
    assert ocr.output == {
        "archive": archive_key(document.id),
        "pages": 1,
        "pdfa": True,
        "readings": [FAKE_READING.to_json()],  # how well it read the scan or image
    }
    assert ocr.model_version == "fake-ocr 1"
    assert pages.input == {"original": original_key(document.sha256)}
    assert pages.output == {
        "pages": 2,
        "first_page": page_key(document.id, 1),
        "preview": preview_key(document.id),
    }
    assert pages.model_version == "fake-pages 1"
    assert parse.input == {"archive": archive_key(document.id)}
    assert parse.output["characters"] == len("Rechnung")
    assert parse.model_version == "fake-parser 1"


async def logged(world: World, owner: User, document: Document, node: Node) -> NodeRun:
    """The log entry of `node`."""
    log = await world.documents.processing_log(owner.id, document.id)
    return next(entry for entry in log if entry.node is node)


async def test_a_damaged_file_goes_red_at_once(world: World) -> None:
    ocr, pages = FakeOcr(), FakePageRenderer()
    owner, document = await ingest(world, pipeline(world, ocr=ocr, pages=pages), "damaged.pdf")
    assert document.lane is Lane.RED
    assert document.page_count is None
    # OCR and the pages run side by side; whichever comes first fails and stops the rest.
    failed = document.processing.failed()
    assert failed and set(failed) <= {Node.OCR, Node.PAGES}
    assert 1 <= len(ocr.calls) + len(pages.calls) <= 2
    log = await world.documents.processing_log(owner.id, document.id)
    for node in failed:
        entry = next(entry for entry in log if entry.node is node)
        assert entry.result.reason == "the file is damaged or not a valid document"
    assert not await world.object_store.exists(archive_key(document.id))


async def test_an_archive_that_is_not_pdfa_is_uncertain(world: World) -> None:
    owner, document = await ingest(world, pipeline(world, ocr=NotPdfa()), "scan.pdf")
    assert document.lane is Lane.YELLOW
    assert document.processing.outcomes[Node.OCR] is Outcome.UNCERTAIN
    entry = await logged(world, owner, document, Node.OCR)
    assert entry.node is Node.OCR
    assert entry.result.reason == "the archive could not be made PDF/A"
    assert "note" not in entry.result.output


async def test_the_engines_reason_for_a_plain_pdf_is_in_the_log(world: World) -> None:
    note = "not PDF/A: Setting Overprint Mode to 1 not permitted in PDF/A-2"
    owner, document = await ingest(world, pipeline(world, ocr=NotPdfa(note)), "scan.pdf")
    assert document.lane is Lane.YELLOW
    entry = await logged(world, owner, document, Node.OCR)
    assert entry.result.reason == f"the archive could not be made PDF/A: {note}"
    assert entry.result.output["note"] == note


async def test_a_signature_left_out_of_the_archive_is_ok_with_a_note(world: World) -> None:
    owner, document = await ingest(world, pipeline(world, ocr=Unsigned()), "scan.pdf")
    assert document.lane is Lane.GREEN
    entry = await logged(world, owner, document, Node.OCR)
    assert entry.node is Node.OCR and entry.result.outcome is Outcome.OK
    assert entry.result.reason == "signature not carried"
    assert entry.result.output["note"] == "signature not carried"


async def test_a_document_without_text_goes_red(world: World) -> None:
    owner, document = await ingest(world, pipeline(world, text="\n\f\n  \n"), "blank.pdf")
    assert document.lane is Lane.RED
    assert document.processing.failed() == (Node.PARSE,)
    entry = (await world.documents.processing_log(owner.id, document.id))[-1]
    assert entry.result.reason == "no text recognised: the pages are blank or hold only pictures"
    assert await world.object_store.exists(text_key(document.id))  # kept for inspection


async def test_the_markdown_of_before_goes_once_the_text_is_read_again(world: World) -> None:
    """A document parsed before 0.2 kept Docling's Markdown; it is read until the document is
    parsed again, then removed."""
    store = world.object_store
    service = pipeline(world)
    owner, document = await ingest(world, service, "scan.pdf")
    read = await load_text(store, document.id)
    await store.delete(text_key(document.id))
    await store.put(legacy_text_key(document.id), b"# Docling", content_type="text/markdown")
    assert await load_text(store, document.id) == b"# Docling"
    await service.reprocess_from(owner.id, document.id, Node.PARSE)
    await world.drain(service)
    assert await load_text(store, document.id) == read
    assert not await store.exists(legacy_text_key(document.id))
    entry = await logged(world, owner, document, Node.PARSE)
    assert entry.result.output["text"] == text_key(document.id)


WORDS = (
    PageWords(
        1,
        (
            ReadWord("Datum", 95, Box(0.1, 0.2, 0.1, 0.01), 0.012),
            ReadWord("24.06.2022", 96, Box(0.3, 0.2, 0.15, 0.01), 0.012),
            ReadWord("j", 12),  # without a box: no quote finds it
        ),
    ),
)


async def test_the_words_tesseract_read_are_kept_beside_the_archive(world: World) -> None:
    """Replaced with every archive; gone with one whose pages were not recognised."""
    store = world.object_store
    reading = PageReading.of(1, WORDS[0].words)
    service = pipeline(world, ocr=FakeOcr(readings=[reading], words=WORDS))
    owner, document = await ingest(world, service, "scan.pdf")
    key = reading_key(document.id)
    assert store.content_type(key) == "application/json"
    assert reading_from_json(json.loads(await store.get(key))) == {1: WORDS[0].words[:2]}
    entry = await logged(world, owner, document, Node.OCR)
    assert entry.result.output["readings"] == [reading.to_json()]
    await OcrNode(store, FakeOcr()).run(document)
    assert not await store.exists(key)


async def test_reprocessing_from_parse_reuses_the_archive(world: World) -> None:
    ocr = FakeOcr()
    service = pipeline(world, ocr=ocr)
    owner, document = await ingest(world, service, "scan.pdf")
    await service.reprocess_from(owner.id, document.id, Node.PARSE)
    await world.drain(service)
    assert len(ocr.calls) == 1
    assert (await world.documents.get(owner.id, document.id)).lane is Lane.GREEN


async def test_work_directories_are_removed(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    await ingest(world, pipeline(world), "scan.pdf")
    await ingest(world, pipeline(world), "damaged.pdf")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", False), ("  \n\f\n", False), ("--- | ---", False), ("4711", True), ("Ä", True)],
)
def test_has_text(text: str, expected: bool) -> None:
    assert has_text(text) is expected
