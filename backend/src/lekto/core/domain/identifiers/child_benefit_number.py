"""Child benefit number (Kindergeldnummer): a person's, three digits, `FK` and six digits
(`123FK456789`); found after its label."""

import re

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers.base import SEPARATORS, IdentifierKind, LabelledNumber
from lekto.core.domain.reasons import ReasonCode, because

_FORM = re.compile(r"\d{3}FK\d{6}")
_VALUE = r"\.?\s*[:.]?\s*(?P<value>\d{3}[-\s]?fk[-\s]?\d{6})(?![a-z0-9])"


class ChildBenefitNumber(LabelledNumber):
    kind = IdentifierKind.CHILD_BENEFIT_NUMBER
    for_persons = True
    value = _VALUE
    labels = r"kindergeld[-\s]*(?:nummer|nr)|child[-\s]*benefit[-\s]*(?:no|number)"

    def normalise(self, raw: str) -> str:
        """Without separators, in upper case."""
        value = SEPARATORS.sub("", raw.strip()).upper()
        if not _FORM.fullmatch(value):
            raise ValidationError(because(ReasonCode.NOT_OF_KIND, kind=self.kind.value, value=raw))
        return value
