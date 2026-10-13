"""PDFium (pypdfium2): page images (Pillow reads images and encodes WebP), the places of
quotes in a PDF's text layer and its text in fixed-pitch fonts (for the Docling child process)."""

from papiq.adapters.outbound.pdfium.library import count_pages
from papiq.adapters.outbound.pdfium.locator import PdfiumTextLocator
from papiq.adapters.outbound.pdfium.pages import PdfiumPageRenderer

__all__ = ["PdfiumPageRenderer", "PdfiumTextLocator", "count_pages"]
