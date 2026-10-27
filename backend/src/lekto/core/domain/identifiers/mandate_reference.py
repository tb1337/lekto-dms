"""SEPA mandate reference (Mandatsreferenz): a contact's, which may name the user it belongs
to; points to the direct debit mandate."""

from lekto.core.domain.identifiers.base import (
    IdentifierKind,
    LabelledNumber,
)


class MandateReference(LabelledNumber):
    kind = IdentifierKind.MANDATE_REFERENCE
    for_contacts = True
    names_user = True
    longest = 35
    labels = r"mandats[-\s]*(?:referenz|ref)|mandate[-\s]*(?:reference|ref)"
