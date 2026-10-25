"""Meter number (Zählernummer, Zählpunkt): a contact's, which may name the user it belongs
to; points to the meter a utility's bills refer to."""

from lekto.core.domain.identifiers.base import (
    IdentifierKind,
    LabelledNumber,
)


class MeterNumber(LabelledNumber):
    kind = IdentifierKind.METER_NUMBER
    for_contacts = True
    names_user = True
    longest = 40
    labels = (
        r"zähler[-\s]*(?:nummer|nr)|zählpunkt(?:[-\s]*(?:nummer|bezeichnung))?"
        r"|meter[-\s]*(?:no|number)"
    )
