"""Credit note number (Gutschriftsnummer): marks the credit note."""

from lekto.core.domain.identifiers.base import (
    COMPOUND,
    IdentifierKind,
    LabelledNumber,
)


class CreditNoteNumber(LabelledNumber):
    kind = IdentifierKind.CREDIT_NOTE_NUMBER
    compounds = COMPOUND
    labels = r"gutschrifts?[-\s]*(?:nummer|nr)|credit[-\s]*note[-\s]*(?:no|number)"
