"""A document's files as they are stored, and what they say about themselves."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from papiq.core.ports.metadata import FileMetadata, MetadataSource
from papiq.core.services.documents import DocumentFiles, StoredFile


class MetadataEntryOut(BaseModel):
    source: MetadataSource = Field(
        description=(
            "`info`: a PDF's document information; `xmp`: its XMP packet (`prefix:name`); "
            "`exif`: an image's EXIF tags."
        )
    )
    key: str = Field(examples=["xmp:CreatorTool"])
    value: str = Field(description="As the file holds it; someone else's text.")


class FileMetadataOut(BaseModel):
    format: str = Field(examples=["PDF", "JPEG"])
    pdf_version: str | None = Field(examples=["1.7"])
    pdfa: str | None = Field(description="PDF/A part and conformance.", examples=["2B"])
    pages: int | None
    width: int | None = Field(description="An image's width in pixels.")
    height: int | None = Field(description="An image's height in pixels.")
    dpi: float | None = Field(description="An image's resolution.")
    entries: list[MetadataEntryOut] = Field(description="In the file's order.")

    @classmethod
    def of(cls, metadata: FileMetadata) -> "FileMetadataOut":
        return cls(
            format=metadata.format,
            pdf_version=metadata.pdf_version,
            pdfa=metadata.pdfa,
            pages=metadata.pages,
            width=metadata.width,
            height=metadata.height,
            dpi=metadata.dpi,
            entries=[
                MetadataEntryOut(source=entry.source, key=entry.key, value=entry.value)
                for entry in metadata.entries
            ],
        )


class StoredFileOut(BaseModel):
    size: int = Field(description="In bytes.")
    sha256: str
    metadata: FileMetadataOut | None = Field(
        description="Null if the file cannot be read for it (damaged, encrypted)."
    )

    @classmethod
    def of(cls, stored: StoredFile) -> "StoredFileOut":
        return cls(
            size=stored.size,
            sha256=stored.sha256,
            metadata=None if stored.metadata is None else FileMetadataOut.of(stored.metadata),
        )


class DocumentFilesOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "added": "2026-07-03T08:40:36Z",
                    "modified": "2026-07-07T10:12:00Z",
                    "original_filename": "scan-2026-07-03.pdf",
                    "media_type": "application/pdf",
                    "page_count": 2,
                    "original": {
                        "size": 10_812_334,
                        "sha256": (
                            "60da47f43707a540e24deda1ab809e1e395af4a86351d5784b9158acaafffddc"
                        ),
                        "metadata": {
                            "format": "PDF",
                            "pdf_version": "1.4",
                            "pdfa": None,
                            "pages": 2,
                            "width": None,
                            "height": None,
                            "dpi": None,
                            "entries": [
                                {"source": "info", "key": "Producer", "value": "Scanner 2.1"}
                            ],
                        },
                    },
                    "archive": None,
                }
            ]
        }
    )

    added: datetime
    modified: datetime
    original_filename: str
    media_type: str
    page_count: int | None
    original: StoredFileOut
    archive: StoredFileOut | None = Field(description="Null while there is none.")

    @classmethod
    def of(cls, files: DocumentFiles) -> "DocumentFilesOut":
        document = files.document
        return cls(
            added=document.created_at,
            modified=document.updated_at,
            original_filename=document.original_filename,
            media_type=document.media_type,
            page_count=document.page_count,
            original=StoredFileOut.of(files.original),
            archive=None if files.archive is None else StoredFileOut.of(files.archive),
        )
