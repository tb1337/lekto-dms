"""Licence plate (Kfz-Kennzeichen): a contact's (the insurer's, the garage's), which may name
the user it belongs to; points to the car. A German plate: the district's one to three letters,
one or two letters, one to four digits, `E` or `H` after them or not (`M-AB 1234`); found after
its label."""

import re

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers.base import SEPARATORS, IdentifierKind, LabelledNumber
from lekto.core.domain.reasons import ReasonCode, because

_FORM = re.compile(r"[A-ZÄÖÜ]{1,3}[A-Z]{1,2}[1-9]\d{0,3}[EH]?")
_VALUE = (
    r"\.?\s*[:.]?\s*(?P<value>[a-zäöü]{1,3}[-\s]?[a-z]{1,2}[-\s]?[1-9]\d{0,3}[eh]?)"
    r"(?![a-z0-9])"
)


class LicensePlate(LabelledNumber):
    kind = IdentifierKind.LICENSE_PLATE
    for_contacts = True
    names_user = True
    value = _VALUE
    labels = (
        r"(?:kfz[-\s]*|amtliches[-\s]*|fahrzeug[-\s]*|auto[-\s]*)?kennzeichen"
        r"|licen[cs]e[-\s]*plate"
    )

    def normalise(self, raw: str) -> str:
        """Without separators, in upper case."""
        value = SEPARATORS.sub("", raw.strip()).upper()
        if not _FORM.fullmatch(value):
            raise ValidationError(because(ReasonCode.NOT_OF_KIND, kind=self.kind.value, value=raw))
        return value
