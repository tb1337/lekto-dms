"""Ticket number (Ticket-, Vorgangsnummer): joins the letters of a request."""

from lekto.core.domain.identifiers.base import (
    IdentifierKind,
    LabelledNumber,
)


class TicketNumber(LabelledNumber):
    kind = IdentifierKind.TICKET_NUMBER
    labels = (
        r"ticket[-\s]*(?:nummer|nr|no|number|id)|vorgangs[-\s]*(?:nummer|nr)"
        r"|case[-\s]*(?:no|number|id)"
    )
