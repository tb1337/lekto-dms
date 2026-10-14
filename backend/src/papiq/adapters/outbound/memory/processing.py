"""Stand-ins for OCR, parser, page renderer and text locator: fast, deterministic, no
external programs.

They follow the contracts without real recognition: the archive is a minimal PDF that names the
source, the text is a short one, the page images tiny WebP headers, and the locator finds
texts in pages it is given instead of reading the PDF. A file that is neither a PDF ending with
`%%EOF` nor a supported image counts as damaged.
"""

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from papiq.core.domain import media_types
from papiq.core.domain.errors import UnprocessableDocumentError
from papiq.core.domain.locations import Box, Location
from papiq.core.ports.ocr import OcrResult
from papiq.core.ports.pages import PREVIEW_FILE, RenderedPages
from papiq.core.ports.parser import ParseResult

FAKE_PDF = b"%PDF-1.7\n% papiq fake archive\n%%EOF\n"
FAKE_WEBP = b"RIFF\x0c\x00\x00\x00WEBPVP8 "


class FakeOcr:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    async def make_archive(self, source: Path, target: Path, *, media_type: str) -> OcrResult:
        self.calls.append(source)
        data = await asyncio.to_thread(source.read_bytes)
        _check(data)
        await asyncio.to_thread(target.write_bytes, FAKE_PDF)
        return OcrResult(pages=1, engine="fake-ocr 1", pdfa=True)


class FakeParser:
    def __init__(self, text: str = "Fake text") -> None:
        self.text = text
        self.calls: list[Path] = []

    async def parse(self, source: Path, *, text: Path, structure: Path) -> ParseResult:
        self.calls.append(source)
        _check(await asyncio.to_thread(source.read_bytes))
        await asyncio.to_thread(text.write_text, self.text, encoding="utf-8")
        await asyncio.to_thread(
            structure.write_text, json.dumps({"text": self.text}), encoding="utf-8"
        )
        return ParseResult(pages=1, parser="fake-parser 1")


class FakePageRenderer:
    """`pages` images per document."""

    def __init__(self, pages: int = 1) -> None:
        self.pages = pages
        self.calls: list[Path] = []

    async def render_pages(self, source: Path, *, media_type: str, target: Path) -> RenderedPages:
        self.calls.append(source)
        _check(await asyncio.to_thread(source.read_bytes))
        for number in range(1, self.pages + 1):
            await asyncio.to_thread((target / f"{number}.webp").write_bytes, FAKE_WEBP)
        await asyncio.to_thread((target / PREVIEW_FILE).write_bytes, FAKE_WEBP)
        return RenderedPages(pages=self.pages, renderer="fake-pages 1")


class FakeTextLocator:
    """Looks for texts in `pages` (one string per page, lines split by line breaks) on their
    letters and digits, case ignored; a box per line, as wide as the matched characters and
    as high as a line. The PDF is only checked to be one."""

    def __init__(self, pages: Sequence[str] = ("Fake text",)) -> None:
        self.pages = list(pages)
        self.calls: list[list[str]] = []

    async def locate(self, pdf: Path, texts: Sequence[str]) -> list[tuple[Location, ...]]:
        if not texts:
            return []
        self.calls.append(list(texts))
        _check(await asyncio.to_thread(pdf.read_bytes))
        return [self._places(text) for text in texts]

    def _places(self, text: str) -> tuple[Location, ...]:
        needle = "".join(char.casefold() for char in text if char.isalnum())
        if not needle:
            return ()
        places = []
        for number, page in enumerate(self.pages, start=1):
            lines = page.splitlines() or [""]
            spots = [
                (row, column, char.casefold())
                for row, line in enumerate(lines)
                for column, char in enumerate(line)
                if char.isalnum()
            ]
            haystack = "".join(char for _, _, char in spots)
            start = haystack.find(needle)
            if start >= 0:
                matched = spots[start : start + len(needle)]
                boxes = []
                for row in sorted({row for row, _, _ in matched}):
                    columns = [column for spot_row, column, _ in matched if spot_row == row]
                    width = max(len(lines[row]), 1)
                    boxes.append(
                        Box.clamped(
                            min(columns) / width,
                            row / len(lines),
                            (max(columns) + 1) / width,
                            (row + 1) / len(lines),
                        )
                    )
                places.append(Location(number, tuple(boxes)))
        return tuple(places)


def _check(data: bytes) -> None:
    kind = media_types.detect(data[: media_types.SNIFF_SIZE])
    if kind is None or (kind == media_types.PDF and not data.rstrip().endswith(b"%%EOF")):
        raise UnprocessableDocumentError("the file is damaged or not a valid document")
