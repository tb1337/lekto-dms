"""SEPA creditor identifier (Gläubiger-Identifikationsnummer, `DE98ZZZ09999999999`): points to
the contact that collects by direct debit; found anywhere where its business code holds a
letter (an IBAN's never does), and after its label; its check digits must fit (ISO 7064,
MOD 97-10, without the business code)."""

import re
from collections.abc import Iterator

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers.base import (
    SEPARATORS,
    VALUE,
    Candidate,
    IdentifierKind,
    IdentifierType,
    after_label,
)
from lekto.core.domain.reasons import ReasonCode, because

_FORM = re.compile(
    r"(?P<country>[A-Z]{2})(?P<check>\d{2})(?P<business>[A-Z0-9]{3})(?P<id>[A-Z0-9]{1,28})"
)
_ANYWHERE = re.compile(
    r"(?<![a-z0-9])[a-z]{2}\d{2} ?(?=[a-z0-9]{0,2}[a-z])[a-z0-9]{3} ?\d{8,28}(?![a-z0-9])"
)
_LABEL = re.compile(
    r"(?<![a-z])(?:gläubiger[-\s]*(?:id(?:entifikations(?:nummer)?)?|identifikationsnummer|nr)"
    r"|creditor[-\s]*(?:id|identifier))" + VALUE
)


def creditor_id_valid(value: str) -> bool:
    """Whether the check digits of a normalised creditor identifier fit."""
    found = _FORM.fullmatch(value)
    if found is None:
        return False
    digits = "".join(str(int(char, 36)) for char in found["id"] + found["country"] + found["check"])
    return int(digits) % 97 == 1


class CreditorId(IdentifierType):
    kind = IdentifierKind.CREDITOR_ID
    for_contacts = True

    def normalise(self, raw: str) -> str:
        """Without separators, in upper case, with check digits that fit."""
        value = SEPARATORS.sub("", raw.strip()).upper()
        if not creditor_id_valid(value):
            raise ValidationError(because(ReasonCode.NOT_OF_KIND, kind=self.kind.value, value=raw))
        return value

    def find(self, text: str) -> Iterator[Candidate]:
        for match in _ANYWHERE.finditer(text):
            yield Candidate(self.kind, match.group(), match.span())
        yield from after_label(self.kind, _LABEL, text)
