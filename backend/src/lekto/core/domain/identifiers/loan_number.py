"""Loan number (Darlehens-, Kreditnummer): a contact's, which may name the user it belongs to."""

from lekto.core.domain.identifiers.base import (
    IdentifierKind,
    LabelledNumber,
)


class LoanNumber(LabelledNumber):
    kind = IdentifierKind.LOAN_NUMBER
    for_contacts = True
    names_user = True
    labels = (
        r"darlehens[-\s]*(?:nummer|nr|konto(?:[-\s]*(?:nummer|nr))?)"
        r"|kredit[-\s]*(?:nummer|nr)|loan[-\s]*(?:no|number)"
    )
