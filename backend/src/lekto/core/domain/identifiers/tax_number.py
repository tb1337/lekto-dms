"""A company's tax number (Steuernummer): points to the contact; found after its label
("Steuernummer", "St.-Nr."), compared as its digits (`123/456/78901` is `12345678901`)."""

import re

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers.base import IdentifierKind, LabelledNumber
from lekto.core.domain.reasons import ReasonCode, because

_FORM = re.compile(r"\d{10,13}")


class TaxNumber(LabelledNumber):
    kind = IdentifierKind.TAX_NUMBER
    for_contacts = True
    labels = r"steuer[-\s]*(?:nummer|nr)|st[-.\s]*nr|tax[-\s]*number"

    def normalise(self, raw: str) -> str:
        """Its digits: 10 to 13 of them."""
        value = re.sub(r"[\s./-]+", "", raw.strip())
        if not _FORM.fullmatch(value):
            raise ValidationError(because(ReasonCode.NOT_OF_KIND, kind=self.kind.value, value=raw))
        return value
