from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, kw_only=True)
class ParseResult:
    pages: int
    parser: str  # name and version of the parser, for the processing log


class DocumentParser(Protocol):
    """Reads the text of the archive PDF from its text layer, with its structure. Adapter: the
    layout text of PDFium.

    Parsing runs outside the event loop (adapters use a thread or a process).
    """

    async def parse(self, source: Path, *, text: Path, structure: Path) -> ParseResult:
        """Read the archive PDF `source`: its text to `text` (plain text as it is set, the pages
        apart by a form feed on a line of its own), its structure as JSON to `structure`.

        UnprocessableDocumentError if the file cannot be read. Other errors may be temporary. On
        error, neither file is created.
        """
        ...
