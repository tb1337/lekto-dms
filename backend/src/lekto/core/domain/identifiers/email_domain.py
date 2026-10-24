"""The domain of a contact's e-mail and web addresses (not a free mail provider's: its
addresses are people's); found in the addresses of a text; it also stands for its subdomains
(`service.stadtwerke.de` for `stadtwerke.de`)."""

import re
from collections.abc import Iterator

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers.base import Candidate, IdentifierKind, IdentifierType
from lekto.core.domain.identifiers.email_address import EMAIL
from lekto.core.domain.reasons import ReasonCode, because

FREE_MAIL = frozenset(
    {
        *("aol.com", "arcor.de", "bluewin.ch", "freenet.de", "gmail.com", "googlemail.com"),
        *("gmx.at", "gmx.ch", "gmx.de", "gmx.net", "hotmail.com", "hotmail.de", "icloud.com"),
        *("live.com", "live.de", "mail.de", "mailbox.org", "me.com", "msn.com", "online.de"),
        *("outlook.com", "outlook.de", "posteo.de", "proton.me", "protonmail.com"),
        *("t-online.de", "web.de", "yahoo.com", "yahoo.de"),
    }
)
"""Domains of free mail providers: their addresses belong to people, not to one contact."""

_FORM = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
_WEB = re.compile(r"(?<![a-z0-9@.-])(?:https?://(?:www\.)?|www\.)((?:[a-z0-9-]+\.)+[a-z]{2,63})")


class EmailDomain(IdentifierType):
    kind = IdentifierKind.EMAIL_DOMAIN
    for_contacts = True

    def normalise(self, raw: str) -> str:
        """In lower case, from an e-mail or web address too (without `mailto:`, the part before
        `@`, `http(s)://`, `www.` and a path); not a free mail provider's."""
        value = raw.strip().lower().removeprefix("mailto:").rpartition("@")[2]
        value = re.sub(r"^(?:https?://)?(?:www\.)?", "", value).split("/")[0].rstrip(".")
        if not _FORM.fullmatch(value):
            raise ValidationError(because(ReasonCode.NOT_DOMAIN, value=raw))
        if value in FREE_MAIL:
            raise ValidationError(because(ReasonCode.FREE_MAIL_DOMAIN, value=value))
        return value

    def find(self, text: str) -> Iterator[Candidate]:
        for pattern in (EMAIL, _WEB):
            for match in pattern.finditer(text):
                yield Candidate(self.kind, match.group(1), match.span(1))

    def written(self, value: str) -> str:
        """As it is, not within a longer name."""
        return rf"(?<![\w-]){re.escape(value)}(?![\w-])"

    def matches(self, value: str, found: str) -> bool:
        """The domain or one of its subdomains."""
        return found == value or found.endswith("." + value)
