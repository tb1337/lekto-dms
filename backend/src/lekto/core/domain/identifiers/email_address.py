"""A whole e-mail address: a person's (their profile, with its e-mail); found anywhere in a
text."""

import re
from collections.abc import Iterator

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers.base import Candidate, IdentifierKind, IdentifierType
from lekto.core.domain.reasons import ReasonCode, because

_FORM = re.compile(r"[a-z0-9._%+-]+@(?:[a-z0-9-]+\.)+[a-z]{2,63}")
EMAIL = re.compile(r"[a-z0-9._%+-]+@((?:[a-z0-9-]+\.)+[a-z]{2,63})")
"""An e-mail address in a text in lower case; its first group is the domain."""


class EmailAddress(IdentifierType):
    kind = IdentifierKind.EMAIL_ADDRESS
    for_persons = True

    def normalise(self, raw: str) -> str:
        """In lower case, without `mailto:`."""
        value = raw.strip().lower().removeprefix("mailto:")
        if not _FORM.fullmatch(value):
            raise ValidationError(because(ReasonCode.NOT_EMAIL_ADDRESS, value=raw))
        return value

    def find(self, text: str) -> Iterator[Candidate]:
        # Without its place: only a person's numbers keep a customer or personnel number they
        # overlap from counting (`identifiers_from`).
        for match in EMAIL.finditer(text):
            yield Candidate(self.kind, match.group())

    def written(self, value: str) -> str:
        """As it is, not within a longer address."""
        return rf"(?<![\w.%+-]){re.escape(value)}(?![\w-])"
