"""File reference (Aktenzeichen, Geschäftszeichen): joins the letters of a case."""

from lekto.core.domain.identifiers.base import (
    REFERENCE_VALUE,
    IdentifierKind,
    LabelledNumber,
)


class FileReference(LabelledNumber):
    kind = IdentifierKind.FILE_REFERENCE
    value = REFERENCE_VALUE
    labels = (
        r"akten[-\s]*zeichen|az|geschäfts[-\s]*zeichen|gz|file[-\s]*reference|case[-\s]*reference"
    )
