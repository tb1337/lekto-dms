"""The technical pipeline nodes after receive: OCR, page images and parsing.

Each node downloads its input into a temporary directory, runs the port (which does the heavy
work outside the event loop) and uploads the derivatives. Derivatives are keyed by document, so
reprocessing replaces them.
"""

import asyncio
import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from papiq.core.domain import media_types
from papiq.core.domain.documents import Document
from papiq.core.domain.exchanges import ModelCall
from papiq.core.domain.json_value import JsonObject
from papiq.core.domain.pipeline import Node, NodeResult, Outcome
from papiq.core.domain.reading import NO_TEXT_REASON, readings_to_json
from papiq.core.ports import DocumentParser, ObjectStore, Ocr, PageRenderer, UnitOfWork
from papiq.core.ports.ocr import VisionReading
from papiq.core.ports.pages import PAGE_MEDIA_TYPE, PREVIEW_FILE
from papiq.core.services.exchanges import keep_calls
from papiq.core.services.objects import (
    archive_key,
    legacy_text_key,
    original_key,
    page_key,
    preview_key,
    structure_key,
    text_key,
)

# Markdown without any letter or digit has no text; comments are placeholders (`<!-- image -->`).
_WORD = re.compile(r"\w")


class OcrNode:
    """Archive PDF with text layer. A damaged or encrypted file fails at once
    (UnprocessableDocumentError, see PipelineService); an archive that is not PDF/A is
    uncertain, with the engine's reason. An archive that is PDF/A but differs from what was
    asked (a signature not carried over) is OK with the engine's note as reason. How well each
    recognised page was read goes into the log (`readings`), and whether another OCR's text
    layer was replaced (`read_again`); the judge and the fields node read the readings there.

    In a run a person asked to read with the vision language model (`Processing.vision`), the
    model reads every page: the log names it, its prompt and its tokens (`vision`), and what
    was sent is kept beside the document (`exchanges_key`). Without a model configured, the
    node fails."""

    def __init__(self, store: ObjectStore, ocr: Ocr) -> None:
        self._store = store
        self._ocr = ocr

    async def run(self, document: Document) -> NodeResult:
        vision = document.processing.vision
        input: JsonObject = {"original": original_key(document.sha256)}
        if vision:
            input["vision"] = True
            if self._ocr.vision is None:
                return NodeResult(
                    outcome=Outcome.FAILED,
                    reason=NO_VISION_MODEL,
                    model_version=None,
                    input=input,
                    output={},
                )
        async with work_directory() as work:
            original, archive = work / "original", work / "archive.pdf"
            await self._store.download(original_key(document.sha256), original)
            result = await self._ocr.make_archive(
                original, archive, media_type=document.media_type, vision=vision
            )
            await self._store.upload(
                archive_key(document.id), archive, content_type=media_types.PDF
            )
        output: JsonObject = {
            "archive": archive_key(document.id),
            "pages": result.pages,
            "pdfa": result.pdfa,
        }
        if result.note is not None:
            output["note"] = result.note
        if result.readings:
            output["readings"] = readings_to_json(result.readings)
        if result.read_again:
            output["read_again"] = True
        note = result.note
        if not result.pdfa:
            note = "the archive could not be made PDF/A" + ("" if note is None else f": {note}")
        if result.vision is not None:
            output["vision"] = _vision_output(result.vision)
            note = read_by(result.vision) + ("" if note is None else f"; {note}")
            await keep_calls(self._store, document, Node.OCR, list(result.vision.calls))
        return NodeResult(
            outcome=Outcome.OK if result.pdfa else Outcome.UNCERTAIN,
            reason=note,
            model_version=result.engine,
            input=input,
            output=output,
        )


NO_VISION_MODEL = (
    "a person asked for the vision language model, but none is configured "
    "(PAPIQ_VLM_BASE_URL, PAPIQ_VLM_MODEL)"
)


def read_by(vision: VisionReading) -> str:
    return f"every page was read by the vision language model {vision.model} ({vision.endpoint})"


def _vision_output(vision: VisionReading) -> JsonObject:
    return {
        "model": vision.model,
        "endpoint": vision.endpoint,
        "prompt": vision.prompt,
        "calls": len(vision.calls),
        "tokens": _tokens(vision.calls),
    }


def _tokens(calls: tuple[ModelCall, ...]) -> JsonObject:
    """The input and output tokens of all calls, as far as the endpoint reported them."""
    totals: JsonObject = {}
    for name in ("prompt_tokens", "completion_tokens"):
        counts = [call.usage.get(name) for call in calls]
        numbers = [count for count in counts if isinstance(count, int)]
        if numbers:
            totals[name] = sum(numbers)
    return totals


class PagesNode:
    """Images of every page of the original, and the preview of the first: what the web UI
    shows (and later, what grounding and vision models look at). Runs beside OCR, so it reads
    the original, not the archive. A file that cannot be read fails at once."""

    def __init__(self, store: ObjectStore, renderer: PageRenderer) -> None:
        self._store = store
        self._renderer = renderer

    async def run(self, document: Document) -> "PagesResult":
        async with work_directory() as work:
            original, pages = work / "original", work / "pages"
            pages.mkdir()
            await self._store.download(original_key(document.sha256), original)
            rendered = await self._renderer.render_pages(
                original, media_type=document.media_type, target=pages
            )
            for number in range(1, rendered.pages + 1):
                await self._store.upload(
                    page_key(document.id, number),
                    pages / f"{number}.webp",
                    content_type=PAGE_MEDIA_TYPE,
                )
            await self._store.upload(
                preview_key(document.id), pages / PREVIEW_FILE, content_type=PAGE_MEDIA_TYPE
            )
        result = NodeResult(
            outcome=Outcome.OK,
            model_version=rendered.renderer,
            input={"original": original_key(document.sha256)},
            output={
                "pages": rendered.pages,
                "first_page": page_key(document.id, 1),
                "preview": preview_key(document.id),
            },
        )
        return PagesResult(result, rendered.pages)


@dataclass(frozen=True)
class PagesResult:
    """The page images are there: the document's page count is stored with the result."""

    result: NodeResult
    pages: int

    async def apply(self, uow: UnitOfWork, document: Document, now: datetime) -> NodeResult:
        document.set_page_count(self.pages, now)
        return self.result


class ParseNode:
    """The text of the archive PDF as it is set, and its structure. A document without any text
    fails: there is nothing to classify, a person has to look at it. The Markdown a document
    parsed before 0.2 kept goes once its text is read again."""

    def __init__(self, store: ObjectStore, parser: DocumentParser) -> None:
        self._store = store
        self._parser = parser

    async def run(self, document: Document) -> NodeResult:
        async with work_directory() as work:
            archive, read, structure = (
                work / "archive.pdf",
                work / "content.txt",
                work / "content.json",
            )
            await self._store.download(archive_key(document.id), archive)
            result = await self._parser.parse(archive, text=read, structure=structure)
            text = await asyncio.to_thread(read.read_text, encoding="utf-8")
            await self._store.upload(
                text_key(document.id), read, content_type="text/plain; charset=utf-8"
            )
            await self._store.upload(
                structure_key(document.id), structure, content_type="application/json"
            )
            await self._store.delete(legacy_text_key(document.id))
        input: JsonObject = {"archive": archive_key(document.id)}
        output: JsonObject = {
            "text": text_key(document.id),
            "structure": structure_key(document.id),
            "pages": result.pages,
            "characters": len(text),
        }
        if not has_text(text):
            return NodeResult(
                outcome=Outcome.FAILED,
                reason=NO_TEXT_REASON,
                model_version=result.parser,
                input=input,
                output=output,
            )
        return NodeResult(
            outcome=Outcome.OK, model_version=result.parser, input=input, output=output
        )


def has_text(text: str) -> bool:
    return _WORD.search(text) is not None


@asynccontextmanager
async def work_directory() -> AsyncIterator[Path]:
    """A temporary directory, removed afterwards (also on error or cancellation)."""
    path = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="papiq-"))
    try:
        yield path
    finally:
        await asyncio.shield(asyncio.to_thread(shutil.rmtree, path, ignore_errors=True))
