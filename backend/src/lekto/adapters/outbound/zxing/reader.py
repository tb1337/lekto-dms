"""Bar codes, QR codes and other symbols with zxing-cpp, on the pages of a PDF rendered by
PDFium.

Each page is rendered in grey at `DPI` (small codes need it: a matrix code of a franking mark
has modules of a third of a millimetre), its long edge at most `MAX_EDGE` pixels, and zxing-cpp
reads every format it knows from it. A long document is read as far as `max_pages`. Rendering
goes through the process-wide PDFium lock; decoding does not need it. A result zxing-cpp marks
invalid, or with no text, is left out; the same code twice on a page counts once.
"""

import asyncio
import importlib.metadata
from pathlib import Path

import pypdfium2
import zxingcpp
from PIL import Image

from lekto.adapters.outbound.pdfium.library import LOCK
from lekto.core.domain.codes import Code
from lekto.core.domain.errors import UnprocessableDocumentError
from lekto.core.domain.locations import Box
from lekto.core.ports.codes import CodeReading

DPI = 300
POINTS_PER_INCH = 72  # the unit of a PDF page's size
MAX_EDGE = 5000  # pixels: A4 at 300 dpi is 3508
MAX_PAGES = 50


class ZxingCodeReader:
    def __init__(self, *, max_pages: int = MAX_PAGES) -> None:
        self._max_pages = max_pages
        self._name = (
            f"zxing-cpp {importlib.metadata.version('zxing-cpp')}, "
            f"pdfium {pypdfium2.PDFIUM_INFO.build}"
        )

    async def read_codes(self, source: Path) -> CodeReading:
        return await asyncio.to_thread(self._read, source)

    def _read(self, source: Path) -> CodeReading:
        try:
            with LOCK:
                document = pypdfium2.PdfDocument(source)
                total = len(document)  # a library call too: under the lock
        except pypdfium2.PdfiumError as error:
            raise UnprocessableDocumentError(f"the PDF cannot be read: {error}") from None
        codes: list[Code] = []
        try:
            pages = min(total, self._max_pages)
            for index in range(pages):
                image = _render(document, index)
                codes.extend(_codes_of(image, index + 1))
        finally:
            with LOCK:
                document.close()
        return CodeReading(codes=tuple(codes), reader=self._name, pages=pages)


def _render(document: pypdfium2.PdfDocument, index: int) -> Image.Image:
    with LOCK:
        page = document[index]
        try:
            width, height = page.get_size()
            scale = min(DPI / POINTS_PER_INCH, MAX_EDGE / max(width, height, 1))
            bitmap = page.render(scale=scale, grayscale=True)
            image: Image.Image = bitmap.to_pil().convert("L")
        finally:
            page.close()
    return image


def _codes_of(image: Image.Image, page: int) -> list[Code]:
    found: list[Code] = []
    seen: set[tuple[str, str]] = set()
    for barcode in zxingcpp.read_barcodes(image):
        if not barcode.valid or not barcode.text:
            continue
        format = str(barcode.format)
        if (format, barcode.text) in seen:
            continue
        seen.add((format, barcode.text))
        position = barcode.position
        corners = (
            position.top_left,
            position.top_right,
            position.bottom_right,
            position.bottom_left,
        )
        xs = [point.x / image.width for point in corners]
        ys = [point.y / image.height for point in corners]
        box = Box.clamped(min(xs), min(ys), max(xs), max(ys))
        found.append(Code(page=page, format=format, text=barcode.text, box=box))
    return found
