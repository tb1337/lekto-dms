"""Logos with Pillow: an untrusted PNG, JPEG, WebP or ICO image scaled down to a small WebP.

- Only these four decoders are asked (`Image.open(..., formats=...)`); the kind is recognised by
  the content first, so an SVG, which can carry scripts, never reaches one.
- The size is checked before anything is decoded: at most `MAX_PIXELS` pixels. A small file can
  declare a huge picture (a decompression bomb); of an ICO, every picture it holds is checked,
  as Pillow decodes the largest by the size its own header claims. Pillow's own warning about
  large images is an error here too.
- A JPEG is decoded at a reduced scale where it can be (`draft`) and turned upright by its EXIF
  orientation. Transparency stays (RGBA); the result fits `LOGO_SIZE` pixels square.
"""

import asyncio
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from papiq.core.domain import media_types
from papiq.core.domain.errors import ImageError, UnsupportedMediaTypeError
from papiq.core.ports.images import LOGO_SIZE

MAX_PIXELS = 4096 * 4096
"""Pixels of an image that is decoded at all (64 MB as RGBA)."""
_FORMATS = ("PNG", "JPEG", "WEBP", "ICO")
_PNG = b"\x89PNG\r\n\x1a\n"
_QUALITY = 90


class PillowImageNormaliser:
    def __init__(self, *, size: int = LOGO_SIZE, max_pixels: int = MAX_PIXELS) -> None:
        self._size = size
        self._max_pixels = max_pixels

    async def normalise(self, data: bytes) -> bytes:
        return await asyncio.to_thread(self._normalise, data)

    def _normalise(self, data: bytes) -> bytes:
        kind = media_types.detect_image(data[: media_types.SNIFF_SIZE])
        if kind is None:
            raise UnsupportedMediaTypeError("a logo is a PNG, JPEG, WebP or ICO image")
        if kind == media_types.ICO:
            self._check_icon(data)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data), formats=_FORMATS) as image:
                    return self._logo(image)
        except ImageError:
            raise
        except (
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            OSError,
            ValueError,
            SyntaxError,  # what some of Pillow's decoders raise for a broken header
            EOFError,
        ):
            raise ImageError("the image cannot be read") from None

    def _logo(self, image: Image.Image) -> bytes:
        self._check_size(*image.size)
        if image.format == "JPEG":
            image.draft("RGB", (self._size, self._size))
        image.load()
        picture = ImageOps.exif_transpose(image)
        transparent = picture.mode in ("RGBA", "LA", "PA") or "transparency" in picture.info
        picture = picture.convert("RGBA" if transparent else "RGB")
        picture.thumbnail((self._size, self._size), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        picture.save(out, "WEBP", quality=_QUALITY, method=4)
        return out.getvalue()

    def _check_size(self, width: int, height: int) -> None:
        if width < 1 or height < 1:
            raise ImageError("the image has no pixels")
        if width * height > self._max_pixels:
            raise ImageError(f"the image is larger than {self._max_pixels} pixels")

    def _check_icon(self, data: bytes) -> None:
        """Every picture of an ICO by the size its own header claims (a PNG's IHDR, a
        bitmap's DIB header), which may differ from the ICO's directory."""
        if len(data) < 6:
            raise ImageError("the image cannot be read")
        count = int.from_bytes(data[4:6], "little")
        for index in range(count):
            entry = data[6 + 16 * index : 6 + 16 * (index + 1)]
            if len(entry) < 16:
                raise ImageError("the image cannot be read")
            size = int.from_bytes(entry[8:12], "little")
            offset = int.from_bytes(entry[12:16], "little")
            picture = data[offset : offset + size]
            if len(picture) < 24 or offset + size > len(data):
                raise ImageError("the image cannot be read")
            if picture.startswith(_PNG):
                width = int.from_bytes(picture[16:20], "big")
                height = int.from_bytes(picture[20:24], "big")
            else:  # a bitmap's height counts its mask too
                width = abs(int.from_bytes(picture[4:8], "little", signed=True))
                height = abs(int.from_bytes(picture[8:12], "little", signed=True)) // 2
            self._check_size(max(width, 1), max(height, 1))
