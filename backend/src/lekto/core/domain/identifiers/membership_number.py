"""Membership number (Mitgliedsnummer): a contact's, which may name the user it belongs to."""

from lekto.core.domain.identifiers.base import (
    COMPOUND,
    IdentifierKind,
    LabelledNumber,
)


class MembershipNumber(LabelledNumber):
    kind = IdentifierKind.MEMBERSHIP_NUMBER
    for_contacts = True
    names_user = True
    compounds = COMPOUND
    labels = r"mitglieds[-\s]*(?:nummer|nr)|member(?:ship)?[-\s]*(?:no|number|id)"
