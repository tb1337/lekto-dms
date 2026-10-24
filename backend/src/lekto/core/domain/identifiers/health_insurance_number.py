"""The German health insurance number of a person (Krankenversichertennummer, their profile): a
letter and nine digits, the last a check digit; found after its label ("Versichertennummer",
"Krankenversicherungsnummer", "KVNR")."""

import re
from collections.abc import Iterator

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers.base import (
    SEPARATORS,
    Candidate,
    IdentifierKind,
    IdentifierType,
    after_label,
)
from lekto.core.domain.reasons import ReasonCode, because

_FORM = re.compile(r"[A-Z]\d{9}")
_LABEL = re.compile(
    r"(?<![a-z])(?:(?:kranken)?versicherten[-\s]*(?:nummer|nr|id)"
    r"|kranken[-\s]*versicherungs[-\s]*(?:nummer|nr)|kvnr)\.?\s*[:.]?\s*"
    r"([a-z] ?\d(?: ?\d){8})(?![a-z0-9])"
)


def health_insurance_number_valid(value: str) -> bool:
    """A German health insurance number (Krankenversichertennummer): a letter and nine digits,
    the last the check digit: the letter as its position in the alphabet (two digits) and the
    first eight digits, weighted 1, 2, 1, 2, …, the digit sums of the products added, modulo
    10."""
    if not _FORM.fullmatch(value):
        return False
    digits = f"{ord(value[0]) - ord('A') + 1:02d}{value[1:9]}"
    total = sum(
        sum(divmod(int(digit) * (2 if position % 2 else 1), 10))
        for position, digit in enumerate(digits)
    )
    return total % 10 == int(value[9])


class HealthInsuranceNumber(IdentifierType):
    kind = IdentifierKind.HEALTH_INSURANCE_NUMBER
    for_persons = True

    def normalise(self, raw: str) -> str:
        """Without separators, in upper case, with a valid check digit."""
        value = SEPARATORS.sub("", raw.strip()).upper()
        if not health_insurance_number_valid(value):
            raise ValidationError(because(ReasonCode.NOT_HEALTH_INSURANCE_NUMBER, value=raw))
        return value

    def find(self, text: str) -> Iterator[Candidate]:
        return after_label(self.kind, _LABEL, text)
