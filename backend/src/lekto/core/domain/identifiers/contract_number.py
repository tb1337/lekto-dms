"""Contract number (Vertragsnummer): a contact's, which may name the user it belongs to; points
to the contract a series of documents refers to."""

from lekto.core.domain.identifiers.base import (
    COMPOUND,
    IdentifierKind,
    LabelledNumber,
)


class ContractNumber(LabelledNumber):
    kind = IdentifierKind.CONTRACT_NUMBER
    for_contacts = True
    names_user = True
    compounds = COMPOUND
    labels = (
        r"vertrags[-\s]*(?:nummer|nr|konto(?:[-\s]*(?:nummer|nr))?)|contract[-\s]*(?:no|number|id)"
    )
