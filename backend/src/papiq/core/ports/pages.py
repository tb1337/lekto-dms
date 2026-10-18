from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from papiq.core.domain import media_types

PAGE_MEDIA_TYPE = media_types.WEBP
PREVIEW_FILE = "preview.webp"
"""The file of the first page at preview size, next to the numbered pages."""


@dataclass(frozen=True)
class RenderedPages:
    pages: int
    renderer: str  # name and version, for the processing log


class PageRenderer(Protocol):
    """Renders the pages of a document as images. First adapter: PDFium for PDFs, Pillow for
    images."""

    async def render_pages(self, source: Path, *, media_type: str, target: Path) -> RenderedPages:
        """Write every page of `source` (a PDF or an image; a multi-page TIFF has several) to
        the directory `target` as WebP images `1.webp`, `2.webp`, ... of a fixed width, and
        the first page at preview width as `preview.webp`. UnprocessableDocumentError if the
        file cannot be read; then `target` stays empty."""
        ...
