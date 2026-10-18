"""File types Papiq accepts, recognised by their content, not by name or declared type."""

from dataclasses import dataclass

PDF = "application/pdf"
JPEG = "image/jpeg"
PNG = "image/png"
TIFF = "image/tiff"
WEBP = "image/webp"
ICO = "image/x-icon"
TEXT = "text/plain; charset=utf-8"
JSON = "application/json"

SUPPORTED: tuple[str, ...] = (PDF, JPEG, PNG, TIFF)
"""PDFs and photos or scans as images. Office files and e-mails are not supported yet."""

SNIFF_SIZE = 1024
"""Bytes from the start of a file that `detect` needs."""

_SIGNATURES = (
    (b"\xff\xd8\xff", JPEG),
    (b"\x89PNG\r\n\x1a\n", PNG),
    (b"II*\x00", TIFF),
    (b"MM\x00*", TIFF),
)


LOGO_UPLOADS: tuple[str, ...] = (PNG, JPEG, WEBP)
"""Images an admin uploads as a contact's logo; SVG is none of them (it can carry scripts)."""
LOGO_IMAGES: tuple[str, ...] = (*LOGO_UPLOADS, ICO)
"""Images a logo is made from: the uploads and the icons of websites (`favicon.ico`)."""


def detect_image(head: bytes) -> str | None:
    """The media type of a raster image a logo is made from (`LOGO_IMAGES`) starting with
    `head` (at least its first 12 bytes), or None."""
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return WEBP
    if head.startswith(b"\x00\x00\x01\x00"):
        return ICO
    found = detect(head)
    return found if found in (PNG, JPEG) else None


@dataclass(frozen=True)
class IconEntry:
    """A picture an ICO's directory names: its sides as given there and where it lies."""

    width: int
    height: int
    size: int  # bytes
    offset: int


def icon_entries(data: bytes, limit: int) -> list[IconEntry] | None:
    """The pictures the directory of the ICO `data` names (a side of 0 there is 256); None if
    it names none or more than `limit`, or is cut short."""
    count = int.from_bytes(data[4:6], "little")
    if not 0 < count <= limit or len(data) < 6 + 16 * count:
        return None
    entries = []
    for index in range(count):
        entry = data[6 + 16 * index : 6 + 16 * (index + 1)]
        entries.append(
            IconEntry(
                width=entry[0] or 256,
                height=entry[1] or 256,
                size=int.from_bytes(entry[8:12], "little"),
                offset=int.from_bytes(entry[12:16], "little"),
            )
        )
    return entries


def detect(head: bytes) -> str | None:
    """The supported media type of a file starting with `head` (its first `SNIFF_SIZE`
    bytes), or None. PDF readers accept the `%PDF-` header anywhere in the first kilobyte."""
    for signature, media_type in _SIGNATURES:
        if head.startswith(signature):
            return media_type
    if b"%PDF-" in head[:SNIFF_SIZE]:
        return PDF
    return None
