"""Page image adapter: PDFium (pypdfium2) renders PDFs, Pillow reads images and encodes WebP."""

from papiq.adapters.outbound.pdfium.library import count_pages
from papiq.adapters.outbound.pdfium.pages import PdfiumPageRenderer

__all__ = ["PdfiumPageRenderer", "count_pages"]
