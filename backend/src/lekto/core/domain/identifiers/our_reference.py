""" "Unser Zeichen": the sender's reference, which joins a strand of letters."""

from lekto.core.domain.identifiers.base import (
    REFERENCE_VALUE,
    IdentifierKind,
    LabelledNumber,
)


class OurReference(LabelledNumber):
    kind = IdentifierKind.OUR_REFERENCE
    value = REFERENCE_VALUE
    labels = r"unser(?:e)?[-\s]*(?:zeichen|referenz|az)|our[-\s]*ref(?:erence)?"
