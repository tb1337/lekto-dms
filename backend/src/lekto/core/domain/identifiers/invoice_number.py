"""Invoice number (Rechnungsnummer): marks the invoice; after "Ihre Rechnung" it refers to it."""

from lekto.core.domain.identifiers.base import (
    COMPOUND,
    IdentifierKind,
    LabelledNumber,
)


class InvoiceNumber(LabelledNumber):
    kind = IdentifierKind.INVOICE_NUMBER
    compounds = COMPOUND
    labels = (
        r"rechnungs[-\s]*(?:nummer|nr)|rechnung[-\s]*(?:nummer|nr)|rg[-.\s]*nr"
        r"|invoice[-\s]*(?:no|number|#)"
    )
