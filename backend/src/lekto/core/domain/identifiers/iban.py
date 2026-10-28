"""IBAN (ISO 13616): a contact's account (where a bill is paid to) or a person's own (their
profile); found anywhere in a text, in groups of four or not, with a country of the IBAN
registry, its length and a valid check sum."""

import re
from collections.abc import Iterator

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers.base import Candidate, IdentifierKind, IdentifierType
from lekto.core.domain.reasons import ReasonCode, because

_FORM = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]+")
# Groups of four, the country also apart from its check digits (`DE 89 3704 …`).
_IN_TEXT = re.compile(r"(?<![a-z0-9])[a-z]{2} ?\d{2}(?: ?[a-z0-9]{4}){2,7}(?: ?[a-z0-9]{1,4})?")
# The countries of the IBAN registry (SWIFT, ISO 13616) and the length of their IBANs. Without
# them a creditor reference (ISO 11649, `RF18 5390 0754 7034`) and any string whose check sum
# happens to fit pass for an IBAN.
_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22,
    "BI": 27, "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22, "DJ": 27,
    "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18, "FK": 18, "FO": 18, "FR": 27,
    "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HN": 28, "HR": 21, "HU": 28,
    "IE": 22, "IL": 23, "IQ": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28,
    "LC": 32, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "LY": 25, "MC": 27, "MD": 24, "ME": 22,
    "MK": 19, "MN": 20, "MR": 27, "MT": 31, "MU": 30, "NI": 28, "NL": 18, "NO": 15, "OM": 23,
    "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "RU": 33, "SA": 24,
    "SC": 31, "SD": 18, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "SO": 23, "ST": 25, "SV": 28,
    "TL": 23, "TN": 24, "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20, "YE": 30,
}  # fmt: skip


def iban_valid(iban: str) -> bool:
    """A compact IBAN in upper case: its country's length and the ISO 13616 check sum (mod 97)."""
    if len(iban) != _LENGTHS.get(iban[:2]):
        return False
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
            # The groups may run into what follows (`DE89 3704 … 3000 Sparkasse`): the IBAN is
            # as long as its country says.
            compact = match.group().replace(" ", "")
            length = _LENGTHS.get(compact[:2].upper(), 0)
            if len(compact) >= length and iban_valid(compact[:length].upper()):
                yield Candidate(self.kind, compact[:length])
