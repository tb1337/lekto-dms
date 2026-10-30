"""Opaque references to identifier values (`/identifiers/refs`, the `fact` filter, open
identifiers): an address names a value by its reference, never as written."""

from pydantic import BaseModel, ConfigDict, Field

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.ports.identity import DecryptionError, RefCipher

MAX_REF = 400
"""Characters of a reference at most (a value of 200 characters, sealed, in base64url)."""


def seal(refs: RefCipher, kind: IdentifierKind, value: str) -> str:
    """The reference to `value` (normalised) of `kind`."""
    return refs.seal(value, context=kind.value)


def opened(refs: RefCipher, kind: IdentifierKind, ref: str) -> str:
    """The value `ref` names for `kind`; ValidationError (422) for one that names none."""
    try:
        return refs.open(ref, context=kind.value)
    except DecryptionError:
        raise ValidationError(because(ReasonCode.REF_UNKNOWN)) from None


class RefIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"kind": "invoice_number", "value": "R-2025-0471"}]},
    )

    kind: IdentifierKind
    value: str = Field(min_length=1, max_length=200, description="As written.")


class RefOut(BaseModel):
    kind: IdentifierKind
    value: str = Field(description="Normalised, as Lekto compares it.")
    ref: str = Field(
        description="The value's reference for addresses (the `fact` filter, "
        "`GET /identifiers/open/{kind}/{ref}`); the same value always gives the same one."
    )
