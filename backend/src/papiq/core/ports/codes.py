from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from papiq.core.domain.codes import Code


@dataclass(frozen=True, kw_only=True)
class CodeReading:
    codes: tuple[Code, ...]
    reader: str  # name and version of the reader, for the processing log
    pages: int  # pages read; a long document is read as far as the reader's limit


class CodeReader(Protocol):
    """Finds bar codes, QR codes and other symbols on the pages of a PDF. First adapter:
    zxing-cpp on pages rendered by PDFium.

    Reading runs outside the event loop (adapters use a thread)."""

    async def read_codes(self, source: Path) -> CodeReading:
        """The codes on the pages of the PDF `source` (the archive), in page order, each with
        its box on the page as shown. UnprocessableDocumentError if the file cannot be read."""
        ...
