"""The German tax ID of a person (steuerliche Identifikationsnummer, their profile): 11 digits
with a check digit; found after its label ("Steuer-ID", "IdNr.") or in its groups
(`12 345 678 901`)."""

import re
from collections import Counter
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

_FORM = re.compile(r"[1-9]\d{10}")
_LABEL = re.compile(
    r"(?<![a-z])(?:steuer[-\s]*id(?:entifikations)?(?:[-\s]*(?:nummer|nr))?"
    r"|steuerliche[-\s]*identifikations[-\s]*(?:nummer|nr)|identifikations[-\s]*(?:nummer|nr)"
    r"|id[-.\s]*nr|tin)\.?(?:\s*\([a-z.\s-]{1,20}\))?\s*[:.]?\s*"
    r"(\d{2} ?\d{3} ?\d{3} ?\d{3}|\d{11})(?!\d)"
)
_GROUPED = re.compile(r"(?<![\d.,/-])\d{2} \d{3} \d{3} \d{3}(?![\d.,/-]?\d)")


def tax_id_valid(value: str) -> bool:
    """A German tax ID: 11 digits, the first not 0; among the first ten, exactly one digit
    stands twice or three times (three not in a row), the others at most once; the last is the
    check digit (ISO 7064, MOD 11,10)."""
    if not _FORM.fullmatch(value):
        return False
    first = value[:10]
    counts = Counter(first)
    repeated = [digit for digit, count in counts.items() if count > 1]
    if len(repeated) != 1 or counts[repeated[0]] > 3:
        return False
    if counts[repeated[0]] == 3 and repeated[0] * 3 in first:
        return False
    product = 10
    for digit in first:
        total = (int(digit) + product) % 10 or 10
        product = total * 2 % 11
    return (11 - product) % 10 == int(value[10])


class TaxId(IdentifierType):
    kind = IdentifierKind.TAX_ID
    for_persons = True

    def normalise(self, raw: str) -> str:
        """Without separators, with a valid check digit."""
        value = SEPARATORS.sub("", raw.strip())
        if not tax_id_valid(value):
            raise ValidationError(because(ReasonCode.NOT_TAX_ID, value=raw))
        return value

    def find(self, text: str) -> Iterator[Candidate]:
        yield from after_label(self.kind, _LABEL, text)
        for match in _GROUPED.finditer(text):
            yield Candidate(self.kind, match.group(), match.span())
