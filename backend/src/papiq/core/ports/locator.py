from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from papiq.core.domain.locations import Location


class TextLocator(Protocol):
    """Finds passages on the pages of a PDF, for showing a quote where it stands. First
    adapter: PDFium on the text layer of the archive PDF."""

    async def locate(self, pdf: Path, texts: Sequence[str]) -> list[tuple[Location, ...]]:
        """For each of `texts`, in order, where it stands: page and boxes of each place, at
        most a few, in page order; none for a text that is not there. Case, spacing and line
        breaks do not matter, nor do hyphens at line ends and the marks of Markdown (a quote
        from the parsed text may read `Gesamtbetrag | 84,20 €`). UnprocessableDocumentError
        if the PDF cannot be read."""
        ...
