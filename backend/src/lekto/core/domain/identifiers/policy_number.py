"""Policy number (Versicherungsschein-, Policennummer): a contact's, which may name the user it
belongs to; points to the policy. Not a person's insurance number: "Rentenversicherungs-
nummer" and "Krankenversicherungsnummer" are no label of it."""

from lekto.core.domain.identifiers.base import (
    IdentifierKind,
    LabelledNumber,
)


class PolicyNumber(LabelledNumber):
    kind = IdentifierKind.POLICY_NUMBER
    for_contacts = True
    names_user = True
    labels = (
        r"versicherungs[-\s]*(?:schein[-\s]*)?(?:nummer|nr)|police?n?[-\s]*(?:nummer|nr)"
        r"|policy[-\s]*(?:no|number)"
    )
