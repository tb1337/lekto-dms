"""Order number (Bestell-, Auftragsnummer): marks the order, or the confirmation of it."""

from lekto.core.domain.identifiers.base import (
    COMPOUND,
    IdentifierKind,
    LabelledNumber,
)


class OrderNumber(LabelledNumber):
    kind = IdentifierKind.ORDER_NUMBER
    compounds = COMPOUND
    labels = r"bestell[-\s]*(?:nummer|nr)|auftrags[-\s]*(?:nummer|nr)|order[-\s]*(?:no|number|#)"
