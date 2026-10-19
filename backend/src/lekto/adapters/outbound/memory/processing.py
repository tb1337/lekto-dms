"""Stand-ins for OCR, parser, page renderer, text locator and code reader: fast,
deterministic, no external programs.

They follow the contracts without real recognition: the archive is a minimal PDF that names the
source (a scan or an image counts as read well, a PDF with fonts as not read), the text is a
short one, the page images tiny WebP headers, and the locator finds texts in pages it is given
instead of reading the PDF. A file that is neither a PDF ending with `%%EOF` nor a supported
image counts as damaged.
"""

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from lekto.core.domain import media_types
from lekto.core.domain.codes import Code
from lekto.core.domain.errors import UnprocessableDocumentError
from lekto.core.domain.exchanges import ModelCall
from lekto.core.domain.locations import Box, Location
from lekto.core.domain.reading import PageReading, PageWords
from lekto.core.ports.codes import CodeReading
from lekto.core.ports.metadata import FileMetadata, MetadataEntry, MetadataSource
from lekto.core.ports.ocr import OcrResult, VisionModel, VisionReading
from lekto.core.ports.pages import PREVIEW_FILE, RenderedPages
from lekto.core.ports.parser import ParseResult

FAKE_PDF = b"%PDF-1.7\n% lekto fake archive\n%%EOF\n"
FAKE_WEBP = b"RIFF\x0c\x00\x00\x00WEBPVP8 "


FAKE_READING = PageReading(page=1, words=20, unsure=0)


FAKE_VISION = VisionModel(model="fake-vlm", endpoint="vlm.example:443")


class FakeOcr:
    """`readings`: what it says it read of a scan or an image, instead of `FAKE_READING`, and
    `words` the words it read there (none unless given). `vision`: the vision model it reads
    with when asked to; it reads the page well then, with one call per page (`vision_calls`
    counts the documents it read so)."""

    def __init__(
        self,
        readings: Sequence[PageReading] | None = None,
        vision: VisionModel | None = None,
        words: Sequence[PageWords] = (),
    ) -> None:
        self.calls: list[Path] = []
        self.vision_calls: list[Path] = []
        self.readings = (FAKE_READING,) if readings is None else tuple(readings)
        self.words = tuple(words)
        self._vision = vision

    @property
    def vision(self) -> VisionModel | None:
        return self._vision

    async def make_archive(
        self, source: Path, target: Path, *, media_type: str, vision: bool = False
    ) -> OcrResult:
        if vision and self._vision is None:
            raise ValueError("no vision language model is configured")
        self.calls.append(source)
        data = await asyncio.to_thread(source.read_bytes)
        _check(data)
        await asyncio.to_thread(target.write_bytes, FAKE_PDF)
        if vision:
            assert self._vision is not None
            self.vision_calls.append(source)
            call = ModelCall(
                system="Transcribe the page.",
                user="Page 1.\n[image: page 1]",
                answer='{"lines": []}',
                model=self._vision.model,
                usage={"prompt_tokens": 1500, "completion_tokens": 100},
            )
            return OcrResult(
                pages=1,
                engine=f"fake-ocr 1, vision language model {self._vision.model}",
                pdfa=True,
                readings=(FAKE_READING,),
                vision=VisionReading(
                    model=self._vision.model,
                    endpoint=self._vision.endpoint,
                    prompt="read-fake",
                    calls=(call,),
                ),
            )
        has_text = media_type == media_types.PDF and b"/Font" in data
        if has_text:
            return OcrResult(pages=1, engine="fake-ocr 1", pdfa=True)
        return OcrResult(
            pages=1, engine="fake-ocr 1", pdfa=True, readings=self.readings, words=self.words
        )


FAKE_GIRO_CODE = Code(
    page=1,
    format="QR Code",
    text="BCD\n002\n1\nSCT\nMUSTDEM1XXX\nLekto Test GmbH\nDE89370400440532013000\nEUR123.45\n\n\n"
    "Rechnung 4711",
    box=Box(0.74, 0.78, 0.12, 0.085),
)


class FakeCodeReader:
    """Finds `codes` on every PDF it can read (none unless given)."""

    def __init__(self, codes: Sequence[Code] = ()) -> None:
        self.codes = tuple(codes)
        self.calls: list[Path] = []

    async def read_codes(self, source: Path) -> CodeReading:
        self.calls.append(source)
        _check(await asyncio.to_thread(source.read_bytes))
        return CodeReading(codes=self.codes, reader="fake-codes 1", pages=1)


class FakeMetadataReader:
    """The metadata of any file it can read: a PDF of one page from the fake producer, an
    image of its kind, one pixel square."""

    async def read_metadata(self, data: bytes) -> FileMetadata:
        _check(data)
        kind = media_types.detect(data[: media_types.SNIFF_SIZE])
        if kind == media_types.PDF:
            producer = MetadataEntry(MetadataSource.INFO, "Producer", "fake-metadata 1")
            return FileMetadata(format="PDF", pdf_version="1.7", pages=1, entries=(producer,))
        name = {media_types.JPEG: "JPEG", media_types.PNG: "PNG", media_types.TIFF: "TIFF"}
        return FileMetadata(format=name.get(kind or "", "image"), pages=1, width=1, height=1)


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
