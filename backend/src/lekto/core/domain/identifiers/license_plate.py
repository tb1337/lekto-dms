"""Licence plate (Kfz-Kennzeichen): a contact's (the insurer's, the garage's), which may name
the user it belongs to; points to the car."""

from lekto.core.domain.identifiers.base import (
    IdentifierKind,
    LabelledNumber,
)


class LicensePlate(LabelledNumber):
    kind = IdentifierKind.LICENSE_PLATE
    for_contacts = True
    names_user = True
    longest = 10
    labels = r"(?:kfz[-\s]*|amtliches[-\s]*)?kennzeichen|licen[cs]e[-\s]*plate"
