"""The metadata of a stored file: of a PDF with pikepdf (its document information and its XMP
packet, as Paperless-ngx shows them), of an image with Pillow (format, size, resolution, EXIF).

Values are text as the file holds them; a value of bytes (an EXIF maker note) is left out, a
long one cut at `MAX_VALUE` characters. Of an image's tags, those that only describe how its
pixels are stored (strips, compression, bits) are left out; the camera's (the EXIF directory)
are in. A file that cannot be read, or an encrypted PDF, is unprocessable.
"""

import asyncio
import io
import re

import pikepdf
from PIL import ExifTags, Image, UnidentifiedImageError

from papiq.core.domain import media_types
from papiq.core.domain.errors import UnprocessableDocumentError
from papiq.core.ports.metadata import FileMetadata, MetadataEntry, MetadataSource

MAX_VALUE = 2000
# How the pixels are stored, and pointers to other directories: nothing a person reads.
_STORAGE_TAGS = frozenset(
    {
        *("BitsPerSample", "Compression", "ExifOffset", "FillOrder", "GPSInfo"),
        *("ImageLength", "ImageWidth", "JPEGInterchangeFormat", "JPEGInterchangeFormatLength"),
        *("PhotometricInterpretation", "PlanarConfiguration", "Predictor", "ResolutionUnit"),
        *("RowsPerStrip", "SampleFormat", "SamplesPerPixel", "StripByteCounts", "StripOffsets"),
        *("TileByteCounts", "TileLength", "TileOffsets", "TileWidth", "XResolution"),
        *("YResolution", "ExifImageHeight", "ExifImageWidth", "InteroperabilityOffset"),
    }
)
_QUALIFIED = re.compile(r"\{(.*)\}(.*)")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class FileMetadataReader:
    async def read_metadata(self, data: bytes) -> FileMetadata:
        return await asyncio.to_thread(_read, data)


def _read(data: bytes) -> FileMetadata:
    kind = media_types.detect(data[: media_types.SNIFF_SIZE])
    if kind == media_types.PDF:
        return _pdf(data)
    if kind in (media_types.JPEG, media_types.PNG, media_types.TIFF):
        return _image(data)
    raise UnprocessableDocumentError("the file is no PDF and no image")


def _text(value: object) -> str | None:
    if isinstance(value, bytes):
        return None
    text = ", ".join(map(str, value)) if isinstance(value, list | tuple) else str(value)
    text = _CONTROL.sub("", text).strip()
    return text[:MAX_VALUE] if text else None


def _pdf(data: bytes) -> FileMetadata:
    try:
        pdf = pikepdf.open(io.BytesIO(data))
    except pikepdf.PasswordError:
        raise UnprocessableDocumentError("the PDF is encrypted") from None
    except pikepdf.PdfError:
        raise UnprocessableDocumentError("the PDF cannot be read") from None
    with pdf:
        entries: list[MetadataEntry] = []
        for key, value in pdf.docinfo.items():
            text = _text(value)
            if text is not None:
                entries.append(MetadataEntry(MetadataSource.INFO, str(key).lstrip("/"), text))
        # Read only: opened outside a `with`, nothing is written back.
        xmp = pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False)
        pdfa = xmp.pdfa_status or None
        for qualified, value in xmp.items():
            text = _text(value)
            if text is None:
                continue
            match = _QUALIFIED.fullmatch(qualified)
            if match is None:
                key = qualified
            else:
                prefix = xmp.REVERSE_NS.get(match.group(1))
                key = f"{prefix}:{match.group(2)}" if prefix else match.group(2)
            entries.append(MetadataEntry(MetadataSource.XMP, key, text))
        return FileMetadata(
            format="PDF",
            pdf_version=pdf.pdf_version,
            pdfa=pdfa,
            pages=len(pdf.pages),
            entries=tuple(entries),
        )


def _image(data: bytes) -> FileMetadata:
    try:
        with Image.open(io.BytesIO(data)) as image:
            dpi = image.info.get("dpi")
            entries: list[MetadataEntry] = []
            exif = image.getexif()
            for tag, value in [*exif.items(), *exif.get_ifd(ExifTags.IFD.Exif).items()]:
                name = ExifTags.TAGS.get(tag, f"0x{tag:04x}")
                text = None if name in _STORAGE_TAGS else _text(value)
                if text is not None:
                    entries.append(MetadataEntry(MetadataSource.EXIF, name, text))
            return FileMetadata(
                format=image.format or "image",
                pages=getattr(image, "n_frames", 1),
                width=image.width,
                height=image.height,
                dpi=round(float(dpi[0]), 1) if dpi else None,
                entries=tuple(entries),
            )
    except (UnidentifiedImageError, OSError, ValueError):
        raise UnprocessableDocumentError("the image cannot be read") from None
