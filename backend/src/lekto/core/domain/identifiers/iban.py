"""IBAN (ISO 13616): a contact's account (where a bill is paid to) or a person's own (their
profile); found anywhere in a text, in groups of four or not, with a valid check sum."""

import re
from collections.abc import Iterator

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers.base import Candidate, IdentifierKind, IdentifierType
from lekto.core.domain.reasons import ReasonCode, because

_FORM = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}")
# Groups of four, the country also apart from its check digits (`DE 89 3704 …`).
_IN_TEXT = re.compile(r"(?<![a-z0-9])[a-z]{2} ?\d{2}(?: ?[a-z0-9]{4}){2,7}(?: ?[a-z0-9]{1,4})?")
_SHORTEST = 15  # characters (Norway)


def iban_valid(iban: str) -> bool:
    """The ISO 13616 check sum (mod 97) of a compact IBAN in upper case."""
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(char, 36)) for char in rearranged)
    return int(digits) % 97 == 1


class Iban(IdentifierType):
    kind = IdentifierKind.IBAN
    for_contacts = True
    for_persons = True

    def normalise(self, raw: str) -> str:
        """Without spaces, in upper case, with a valid check sum."""
        value = re.sub(r"\s+", "", raw.strip()).upper()
        if not _FORM.fullmatch(value) or not iban_valid(value):
            raise ValidationError(because(ReasonCode.NOT_IBAN, value=raw))
        return value

    def find(self, text: str) -> Iterator[Candidate]:
        for match in _IN_TEXT.finditer(text):
            # The groups may run into what follows (`DE89 3704 … 3000 Sparkasse`): the longest
            # start with a valid check sum is the IBAN.
            compact = match.group().replace(" ", "")
            for end in range(len(compact), _SHORTEST - 1, -1):
                if iban_valid(compact[:end].upper()):
                    yield Candidate(self.kind, compact[:end])
                    break
