from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class MetadataSource(StrEnum):
    INFO = "info"  # a PDF's document information dictionary
    XMP = "xmp"  # a PDF's XMP packet: `prefix:name`
    EXIF = "exif"  # an image's EXIF tags


@dataclass(frozen=True)
class MetadataEntry:
    source: MetadataSource
    key: str
    value: str  # as text, as the file holds it (a PDF date stays `D:2026…`)


@dataclass(frozen=True, kw_only=True)
class FileMetadata:
    """What a file says about itself: a PDF its version, PDF/A level and pages; an image its
    format, size and resolution; both their metadata entries, in the file's order."""

    format: str  # "PDF", "JPEG", "PNG", "TIFF", ...
    pdf_version: str | None = None
    pdfa: str | None = None  # PDF/A part and conformance, e.g. "2B"
    pages: int | None = None
    width: int | None = None  # an image's pixels
    height: int | None = None
    dpi: float | None = None
    entries: tuple[MetadataEntry, ...] = ()


class MetadataReader(Protocol):
    """Reads the metadata of a stored file: of a PDF (document information and XMP), of an
    image (EXIF). First adapter: pikepdf and Pillow.

    Reading runs outside the event loop (adapters use a thread)."""

    async def read_metadata(self, data: bytes) -> FileMetadata:
        """The metadata of the file `data`. UnprocessableDocumentError if it cannot be read
        (damaged, encrypted, of no supported kind)."""
        ...
