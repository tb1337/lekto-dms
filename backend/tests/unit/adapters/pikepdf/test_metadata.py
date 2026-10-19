"""pikepdf and Pillow: pass the contract, and read what a PDF and an image say about
themselves (document information, XMP, PDF/A level; EXIF without how the pixels are stored)."""

import io

import pikepdf
import pytest
from PIL import ExifTags, Image

from lekto.adapters.outbound.pikepdf import FileMetadataReader
from lekto.core.domain.errors import UnprocessableDocumentError
from lekto.core.ports.metadata import MetadataSource
from tests.builders import SAMPLES
from tests.contracts.processing import MetadataReaderContract


@pytest.fixture
def metadata_reader() -> FileMetadataReader:
    return FileMetadataReader()


class TestFileMetadataReader(MetadataReaderContract):
    pass


def pdf_a(*, encrypted: bool = False) -> bytes:
    """A two-page PDF with document information and XMP claiming PDF/A-2B."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.add_blank_page()
    with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as xmp:
        xmp["xmp:CreatorTool"] = "Papiq Test Scanner"
        xmp["pdfaid:part"] = "2"
        xmp["pdfaid:conformance"] = "B"
    pdf.docinfo["/Title"] = "Stromrechnung"
    pdf.docinfo["/Producer"] = "Papiq Test 1.0"
    out = io.BytesIO()
    encryption = pikepdf.Encryption(owner="owner", user="user") if encrypted else False
    pdf.save(out, encryption=encryption)
    return out.getvalue()


async def test_a_pdf_with_its_information_xmp_and_pdf_a_level(
    metadata_reader: FileMetadataReader,
) -> None:
    metadata = await metadata_reader.read_metadata(pdf_a())
    assert (metadata.format, metadata.pages, metadata.pdfa) == ("PDF", 2, "2B")
    entries = {(entry.source, entry.key): entry.value for entry in metadata.entries}
    assert entries[MetadataSource.INFO, "Title"] == "Stromrechnung"
    assert entries[MetadataSource.INFO, "Producer"] == "Papiq Test 1.0"
    assert entries[MetadataSource.XMP, "xmp:CreatorTool"] == "Papiq Test Scanner"
    assert entries[MetadataSource.XMP, "pdfaid:part"] == "2"


async def test_an_encrypted_pdf_is_unprocessable(metadata_reader: FileMetadataReader) -> None:
    with pytest.raises(UnprocessableDocumentError, match="encrypted"):
        await metadata_reader.read_metadata(pdf_a(encrypted=True))


async def test_a_photo_with_its_camera_but_not_how_its_pixels_are_stored(
    metadata_reader: FileMetadataReader,
) -> None:
    image = Image.new("RGB", (120, 80), "white")
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "Papiq"
    exif[ExifTags.Base.Model] = "Test Camera"
    exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = "2026:10:16 09:30:00"
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif, dpi=(300, 300))
    metadata = await metadata_reader.read_metadata(out.getvalue())
    assert (metadata.format, metadata.width, metadata.height, metadata.dpi) == (
        "JPEG",
        120,
        80,
        300.0,
    )
    entries = {entry.key: entry.value for entry in metadata.entries}
    assert entries["Make"] == "Papiq"
    assert entries["Model"] == "Test Camera"
    assert entries["DateTimeOriginal"] == "2026:10:16 09:30:00"
    assert "ExifOffset" not in entries
    assert {entry.source for entry in metadata.entries} == {MetadataSource.EXIF}


async def test_every_page_of_a_tiff(metadata_reader: FileMetadataReader) -> None:
    metadata = await metadata_reader.read_metadata((SAMPLES / "pages.tiff").read_bytes())
    assert (metadata.format, metadata.pages) == ("TIFF", 2)
    assert not {entry.key for entry in metadata.entries} & {"StripOffsets", "Compression"}
