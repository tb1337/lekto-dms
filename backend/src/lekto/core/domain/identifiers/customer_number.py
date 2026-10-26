"""Customer number: a contact's, which may name the user it belongs to (Anna's customer
account); found after its label. Until #145 also the contract, policy and membership numbers,
which have kinds of their own now; a contact's customer number still matches them
(`identifier.matches`)."""

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

_FORM = re.compile(r"(?=[A-Z0-9]*\d)[A-Z0-9]{4,30}")
_LABEL = re.compile(
    r"(?:kunden[-\s]*(?:nummer|nr|konto)|kd[-.\s]*nr|kundennr"
    r"|customer[-\s]*(?:no|number|id)|account[-\s]*(?:no|number))" + VALUE
)


class CustomerNumber(IdentifierType):
    kind = IdentifierKind.CUSTOMER_NUMBER
    for_contacts = True
    names_user = True

    def normalise(self, raw: str) -> str:
        """Without separators, in upper case: 4 to 30 letters and digits, one a digit."""
        value = SEPARATORS.sub("", raw.strip()).upper()
        if not _FORM.fullmatch(value):
            raise ValidationError(because(ReasonCode.NOT_CUSTOMER_NUMBER, value=raw))
        return value

    def find(self, text: str) -> Iterator[Candidate]:
        return after_label(self.kind, _LABEL, text)
