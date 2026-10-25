""" "Ihr Zeichen": the addressee's reference, which refers to a document of theirs."""

from lekto.core.domain.identifiers.base import (
    REFERENCE_VALUE,
    IdentifierKind,
    LabelledNumber,
)


class YourReference(LabelledNumber):
    kind = IdentifierKind.YOUR_REFERENCE
    value = REFERENCE_VALUE
    labels = r"ihr(?:e)?[-\s]*(?:zeichen|referenz)|your[-\s]*ref(?:erence)?"
