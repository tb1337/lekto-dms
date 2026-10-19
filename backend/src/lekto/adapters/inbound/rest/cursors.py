"""Cursors of pages of documents (`GET /documents`, `GET /inbox`, the preview of applying a
rule): the id of the document a page ends with, in base64url. Clients pass `next_cursor` back
as `cursor` and do not read it."""

from typing import Annotated
from uuid import UUID

from fastapi import Query

from lekto.core.domain.encoding import base64url, from_base64url
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import DocumentId

Cursor = Annotated[str | None, Query(max_length=64, description="`next_cursor`.")]
"""The `cursor` parameter of a page."""


def encode_cursor(id: DocumentId) -> str:
    return base64url(id.bytes)


def decode_cursor(cursor: str | None) -> DocumentId | None:
    """The document of `cursor`; None without one. ValidationError if it is not a cursor."""
    if not cursor:
        return None
    try:
        return DocumentId(UUID(bytes=from_base64url(cursor)))
    except ValueError:
        raise ValidationError("cursor: invalid") from None
