"""The PDFium library is not thread-safe, not even for different documents: every use in this
process goes through `LOCK`."""

import threading
import unicodedata
from pathlib import Path

import pypdfium2
import pypdfium2.raw as pdfium_c

from lekto.core.domain.errors import UnprocessableDocumentError

LOCK = threading.Lock()


def count_pages(path: Path) -> int:
    """Pages of a PDF (blocking; run it in a thread)."""
    with LOCK:
        try:
            document = pypdfium2.PdfDocument(path)
        except pypdfium2.PdfiumError as error:
            raise UnprocessableDocumentError(f"the PDF cannot be read: {error}") from None
        try:
            return len(document)
        finally:
            document.close()


# A page's text cannot be read when this share of its characters (whitespace aside) maps to
# nothing: control characters, private use, unassigned code points, the replacement character.
UNREADABLE_SHARE = 0.3
_UNMAPPED = frozenset({"Cc", "Co", "Cn", "Cs"})


def unreadable_share(text: str) -> float:
    """The share of the characters of `text` (whitespace aside) that map to nothing; 0 without
    any."""
    characters = [char for char in text if not char.isspace()]
    if not characters:
        return 0.0
    unmapped = sum(
        char == "\ufffd" or unicodedata.category(char) in _UNMAPPED for char in characters
    )
    return unmapped / len(characters)


def has_unreadable_text(path: Path) -> bool:
    """Whether a page of the PDF has text that cannot be read (`UNREADABLE_SHARE`): a font
    without a character map (`/ToUnicode`), as some PDF printers write them, gives its codes,
    which come out as control characters (blocking; run it in a thread). False for a PDF that
    cannot be read: OCRmyPDF says why."""
    with LOCK:
        try:
            document = pypdfium2.PdfDocument(path)
        except pypdfium2.PdfiumError:
            return False
        try:
            return any(
                unreadable_share(page.get_textpage().get_text_range()) >= UNREADABLE_SHARE
                for page in document
            )
        finally:
            document.close()


def has_hidden_text(path: Path) -> bool:
    """Whether a page of the PDF has invisible text, the layer an OCR puts over a scan
    (blocking; run it in a thread). False for a PDF that cannot be read: OCRmyPDF says why."""
    with LOCK:
        try:
            document = pypdfium2.PdfDocument(path)
        except pypdfium2.PdfiumError:
            return False
        try:
            for page in document:
                textpage = page.get_textpage()
                for index in range(textpage.count_chars()):
                    found = pdfium_c.FPDFText_GetTextObject(textpage, index)
                    mode = pdfium_c.FPDFTextObj_GetTextRenderMode(found) if found else None
                    if mode == pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE:
                        return True
            return False
        finally:
            document.close()
