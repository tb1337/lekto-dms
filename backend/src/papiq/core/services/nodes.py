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
from papiq.core.domain.json_value import JsonObject
from papiq.core.domain.pipeline import NodeResult, Outcome
from papiq.core.ports import DocumentParser, ObjectStore, Ocr, PageRenderer, UnitOfWork
from papiq.core.ports.pages import PAGE_MEDIA_TYPE, PREVIEW_FILE
from papiq.core.services.objects import (
    archive_key,
    markdown_key,
    original_key,
    page_key,
    preview_key,
    structure_key,
)

# Markdown without any letter or digit has no text; comments are placeholders (`<!-- image -->`).
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_WORD = re.compile(r"\w")


class OcrNode:
    """Archive PDF with text layer. A damaged or encrypted file fails at once
    (UnprocessableDocumentError, see PipelineService); an archive that is not PDF/A is
    uncertain, with the engine's reason. An archive that is PDF/A but differs from what was
    asked (a signature not carried over) is OK with the engine's note as reason."""

    def __init__(self, store: ObjectStore, ocr: Ocr) -> None:
        self._store = store
        self._ocr = ocr

    async def run(self, document: Document) -> NodeResult:
        async with work_directory() as work:
            original, archive = work / "original", work / "archive.pdf"
            await self._store.download(original_key(document.sha256), original)
            result = await self._ocr.make_archive(original, archive, media_type=document.media_type)
            await self._store.upload(
                archive_key(document.id), archive, content_type=media_types.PDF
            )
        input: JsonObject = {"original": original_key(document.sha256)}
        output: JsonObject = {
            "archive": archive_key(document.id),
            "pages": result.pages,
            "pdfa": result.pdfa,
        }
        if result.note is not None:
            output["note"] = result.note
        if not result.pdfa:
            reason = "the archive could not be made PDF/A"
            if result.note is not None:
                reason = f"{reason}: {result.note}"
            return NodeResult(
                outcome=Outcome.UNCERTAIN,
                reason=reason,
                model_version=result.engine,
                input=input,
                output=output,
            )
        return NodeResult(
            outcome=Outcome.OK,
            reason=result.note,
            model_version=result.engine,
            input=input,
            output=output,
        )


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
    """Markdown and structure from the archive PDF. A document without any text fails: there
    is nothing to classify, a person has to look at it. A parser that had to fall back (the
    text layer instead of its layout analysis, see `ParseResult.note`) makes the node
    uncertain, so the owner sees the document before it is filed."""

    def __init__(self, store: ObjectStore, parser: DocumentParser) -> None:
        self._store = store
        self._parser = parser

    async def run(self, document: Document) -> NodeResult:
        async with work_directory() as work:
            archive, markdown, structure = (
                work / "archive.pdf",
                work / "content.md",
                work / "content.json",
            )
            await self._store.download(archive_key(document.id), archive)
            result = await self._parser.parse(archive, markdown=markdown, structure=structure)
            text = await asyncio.to_thread(markdown.read_text, encoding="utf-8")
            await self._store.upload(
                markdown_key(document.id), markdown, content_type="text/markdown; charset=utf-8"
            )
            await self._store.upload(
                structure_key(document.id), structure, content_type="application/json"
            )
        input: JsonObject = {"archive": archive_key(document.id)}
        output: JsonObject = {
            "markdown": markdown_key(document.id),
            "structure": structure_key(document.id),
            "pages": result.pages,
            "characters": len(text),
        }
        if not has_text(text):
            return NodeResult(
                outcome=Outcome.FAILED,
                reason="no text recognised: the pages are blank or hold only pictures",
                model_version=result.parser,
                input=input,
                output=output,
            )
        if result.note is not None:
            output["note"] = result.note
            return NodeResult(
                outcome=Outcome.UNCERTAIN,
                reason=result.note,
                model_version=result.parser,
                input=input,
                output=output,
            )
        return NodeResult(
            outcome=Outcome.OK, model_version=result.parser, input=input, output=output
        )


def has_text(markdown: str) -> bool:
    return _WORD.search(_COMMENT.sub("", markdown)) is not None


@asynccontextmanager
async def work_directory() -> AsyncIterator[Path]:
    """A temporary directory, removed afterwards (also on error or cancellation)."""
    path = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="papiq-"))
    try:
        yield path
    finally:
        await asyncio.shield(asyncio.to_thread(shutil.rmtree, path, ignore_errors=True))
