"""Making a contact's logo from an image."""

from typing import Protocol

LOGO_SIZE = 128
"""Pixels a logo fits into, square."""
MAX_PIXELS = 4096 * 4096
"""Pixels of an image a logo is made from at most (64 MB decoded as RGBA)."""
MAX_ICON_ENTRIES = 64
"""Pictures of an ICO a logo is made from at most (a website's favicon has a few)."""


class ImageNormaliser(Protocol):
    """Reads a raster image and makes it a logo. First adapter: Pillow.

    The image comes from an admin or from a website (`LogoFetcher`), so it is not trusted:
    adapters read only the kinds named below, check its size before they decode it, and run
    outside the event loop (in a thread)."""

    async def normalise(self, data: bytes) -> bytes:
        """`data`, a PNG, JPEG, WebP or ICO image (of an ICO its largest picture), scaled down
        to fit `LOGO_SIZE` pixels square keeping its proportions, as WebP keeping its
        transparency; a smaller one keeps its size. UnsupportedMediaTypeError for another kind
        (SVG among them); ImageError if it cannot be read or would be too large decoded (more
        than `MAX_PIXELS`, an ICO with more than `MAX_ICON_ENTRIES` pictures)."""
        ...
