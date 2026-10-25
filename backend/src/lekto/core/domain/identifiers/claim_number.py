"""Claim number (Schadennummer): joins the letters of a claim."""

from lekto.core.domain.identifiers.base import (
    IdentifierKind,
    LabelledNumber,
)


class ClaimNumber(LabelledNumber):
    kind = IdentifierKind.CLAIM_NUMBER
    labels = r"schadens?[-\s]*(?:nummer|nr)|claim[-\s]*(?:no|number)"
