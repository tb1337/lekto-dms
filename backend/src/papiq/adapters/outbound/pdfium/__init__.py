"""PDFium (pypdfium2): the text of the archive as it is set (the parser), page images (Pillow
reads images and encodes WebP) and the places of quotes in a PDF's text layer."""

from papiq.adapters.outbound.pdfium.layout import LayoutParser
from papiq.adapters.outbound.pdfium.library import (
    count_pages,
    has_hidden_text,
    has_unreadable_text,
)
from papiq.adapters.outbound.pdfium.locator import PdfiumTextLocator
from papiq.adapters.outbound.pdfium.pages import PdfiumPageRenderer

__all__ = [
    "LayoutParser",
    "PdfiumPageRenderer",
    "PdfiumTextLocator",
    "count_pages",
    "has_hidden_text",
    "has_unreadable_text",
]
