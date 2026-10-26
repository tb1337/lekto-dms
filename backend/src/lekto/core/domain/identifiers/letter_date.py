"""A reference to another's letter by its date ("Ihr Schreiben vom 18.06.2026", "your letter
of 18 June 2026"): this document refers to the addressee's letter of that day. Its value is the
day in ISO 8601; a two-digit year is not read (no day it came in to decide its century)."""

import re
from collections.abc import Iterator
from datetime import date

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.evidence import read_date
from lekto.core.domain.identifiers.base import (
    Candidate,
    IdentifierKind,
    IdentifierType,
    after_labels,
    labelled,
)
from lekto.core.domain.periods import MONTH_NAMES
from lekto.core.domain.reasons import ReasonCode, because

_MONTH = "|".join(name.casefold() for names in MONTH_NAMES.values() for name in names)
_DATE = (
    rf"\.?\s*(?P<value>\d{{1,2}}\.\s?\d{{1,2}}\.\s?\d{{4}}|\d{{1,2}}\.?\s+(?:{_MONTH})\s+\d{{4}})"
)
_LABEL = labelled(
    r"ihr(?:e|en)?\s+(?:schreiben|brief|nachricht|anfrage|e-?mail|mail|antrag|bescheid|"
    r"widerspruch|kündigung|reklamation)\s+vom"
    r"|your\s+(?:letter|e-?mail|message|request)\s+(?:of|dated)",
    _DATE,
)


class LetterDate(IdentifierType):
    kind = IdentifierKind.LETTER_DATE

    def normalise(self, raw: str) -> str:
        """The day as `YYYY-MM-DD`, from how it is written."""
        try:
            return date.fromisoformat(raw.strip()).isoformat()
        except ValueError:
            pass
        day = read_date(raw)
        if day is None or not re.search(r"\d{4}", raw):
            raise ValidationError(because(ReasonCode.NOT_OF_KIND, kind=self.kind.value, value=raw))
        return day.isoformat()

    def find(self, text: str) -> Iterator[Candidate]:
        return after_labels(self.kind, _LABEL, text)

    def written(self, value: str) -> str:
        """The day as the text writes it: `18.06.2026`, `18.6.2026`, `18. Juni 2026`."""
        day = date.fromisoformat(value)
        names = "|".join(re.escape(names[day.month - 1]) for names in MONTH_NAMES.values())
        numeric = rf"0?{day.day}\.\s?0?{day.month}\.\s?{day.year}"
        words = rf"0?{day.day}\.?\s+(?:{names})\s+{day.year}"
        return rf"(?<!\d)(?:{numeric}|{words})(?!\d)"
