"""Commercial register number (Handelsregisternummer, `HRB 12345`): points to the contact; found
anywhere, also after its label, compared without spaces (`HRB12345`). The court is not part
of it: the same number at two courts is one value."""

import re
from collections.abc import Iterator

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers.base import Candidate, IdentifierKind, IdentifierType
from lekto.core.domain.reasons import ReasonCode, because

_FORM = re.compile(r"HR[AB]\d{1,6}[A-Z]{0,2}")
_ANYWHERE = re.compile(r"(?<![a-z0-9])hr ?[ab] ?\d{1,6}(?: ?[a-z]{1,2}(?![a-z]))?(?![a-z0-9])")


class CommercialRegister(IdentifierType):
    kind = IdentifierKind.COMMERCIAL_REGISTER
    for_contacts = True

    def normalise(self, raw: str) -> str:
        value = re.sub(r"[\s.-]+", "", raw.strip()).upper()
        if not _FORM.fullmatch(value):
            raise ValidationError(because(ReasonCode.NOT_OF_KIND, kind=self.kind.value, value=raw))
        return value

    def find(self, text: str) -> Iterator[Candidate]:
        for match in _ANYWHERE.finditer(text):
            yield Candidate(self.kind, match.group(), match.span())
