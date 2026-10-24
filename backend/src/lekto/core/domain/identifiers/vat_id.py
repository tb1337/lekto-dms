"""VAT number (USt-IdNr.): a company's; a German one found anywhere in a text, others after
their label."""

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

_FORM = re.compile(r"[A-Z]{2,3}(?=[A-Z0-9]*\d{6})[A-Z0-9]{8,12}")
_GERMAN = re.compile(r"(?<![a-z0-9])de ?\d{3} ?\d{3} ?\d{3}(?![a-z0-9])")
_LABEL = re.compile(
    r"(?<![a-z])(?:ust[-.\s]*id(?:[-.\s]*nr)?|umsatzsteuer[-\s]*id(?:entifikations)?[-\s]*"
    r"(?:nummer|nr)|vat[-\s]*(?:id|no|number|reg(?:istration)?(?:[-\s]*no)?)?"
    r"|uid[-\s]*(?:nr|nummer)?)" + VALUE
)


class VatId(IdentifierType):
    kind = IdentifierKind.VAT_ID
    for_contacts = True

    def normalise(self, raw: str) -> str:
        """Without separators, in upper case."""
        value = SEPARATORS.sub("", raw.strip()).upper()
        if not _FORM.fullmatch(value):
            raise ValidationError(because(ReasonCode.NOT_VAT_ID, value=raw))
        return value

    def find(self, text: str) -> Iterator[Candidate]:
        for match in _GERMAN.finditer(text):
            yield Candidate(self.kind, match.group(), match.span())
        yield from after_label(self.kind, _LABEL, text)
