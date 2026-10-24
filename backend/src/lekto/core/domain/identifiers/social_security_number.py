"""The German social security (pension insurance) number of a person (their profile): 12
characters with a check digit; found anywhere in a text."""

import re
from collections.abc import Iterator

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers.base import (
    SEPARATORS,
    Candidate,
    IdentifierKind,
    IdentifierType,
)
from lekto.core.domain.reasons import ReasonCode, because

_FORM = re.compile(r"\d{4}(?:0[1-9]|1[0-2])\d{2}[A-Z]\d{3}")
_IN_TEXT = re.compile(r"(?<![a-z0-9])\d{2} ?\d{2} ?\d{2} ?\d{2} ?[a-z] ?\d{2} ?\d(?![a-z0-9])")


def social_security_number_valid(value: str) -> bool:
    """A German social security (pension insurance) number in compact form: area (2 digits),
    birth date (DDMMYY), the initial of the birth name, a serial number (2 digits) and the
    check digit: the letter as its position in the alphabet (two digits), the 12 digits
    weighted 2, 1, 2, 5, 7, 1, 2, 1, 2, 1, 2, 1, the digit sums of the products added, modulo
    10."""
    if not _FORM.fullmatch(value):
        return False
    digits = f"{value[:8]}{ord(value[8]) - ord('A') + 1:02d}{value[9:11]}"
    weights = (2, 1, 2, 5, 7, 1, 2, 1, 2, 1, 2, 1)
    total = sum(
        sum(divmod(int(digit) * weight, 10)) for digit, weight in zip(digits, weights, strict=True)
    )
    return total % 10 == int(value[11])


class SocialSecurityNumber(IdentifierType):
    kind = IdentifierKind.SOCIAL_SECURITY_NUMBER
    for_persons = True

    def normalise(self, raw: str) -> str:
        """Without separators, in upper case, with a valid check digit."""
        value = SEPARATORS.sub("", raw.strip()).upper()
        if not social_security_number_valid(value):
            raise ValidationError(because(ReasonCode.NOT_SOCIAL_SECURITY_NUMBER, value=raw))
        return value

    def find(self, text: str) -> Iterator[Candidate]:
        for match in _IN_TEXT.finditer(text):
            yield Candidate(self.kind, match.group(), match.span())
