"""A user's profile: what is private about them as a person, and what finds them in a document.

The display name is public and stays on the user (`User.display_name`). The profile holds the
rest, which only the user and admins see: other names (aliases, a maiden name), the birth date,
an e-mail address and the person's identifiers (`identifiers.PERSON_KINDS`: an IBAN, the tax ID,
the social security and the health insurance number, further e-mail addresses). Found in a
document, they tell whose it is (`facts.FoundPerson`); none of it ever goes to the language
model, the search index or the processing log (Tobi, 21.10.2026).

Display names are unique across users regardless of case, and no display name is another user's
username, so that a name shown stands for one person (the services check it under a lock, the
repositories keep the rule among display names for two requests at once). Aliases are private
and need not be unique: a 409 for an alias would tell that it is someone's (they are only weak
or medium evidence, and a recipient that matches two people names neither). An identifier may
belong to several users (the IBAN of a joint account), never to a user and a contact
(`ProfileService`, `MasterDataService`).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers import (
    PERSON_KINDS,
    Identifier,
    IdentifierKind,
    normalise_identifier,
)
from lekto.core.domain.ids import UserId
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.users import MAX_DISPLAY_NAME, User
from lekto.core.domain.validation import name_key, require_name

MAX_ALIASES = 10
"""Other names of one person."""
MAX_PERSON_IDENTIFIERS = 50
"""Identifiers of one person."""
EARLIEST_BIRTH = date(1900, 1, 1)


@dataclass(kw_only=True)
class Profile:
    """The private part of a user (`id` is the user's). `version` 0: not stored yet."""

    id: UserId
    aliases: list[str] = field(default_factory=list)
    birth_date: date | None = None
    email: str | None = None
    identifiers: list[Identifier] = field(default_factory=list)
    version: int = 0

    def __post_init__(self) -> None:
        self.aliases = _aliases(self.aliases)
        if self.birth_date is not None and self.birth_date < EARLIEST_BIRTH:
            raise ValidationError(
                because(ReasonCode.BIRTH_DATE_TOO_EARLY, date=EARLIEST_BIRTH.isoformat())
            )
        if self.email is not None:
            self.email = normalise_identifier(IdentifierKind.EMAIL_ADDRESS, self.email)
        self.identifiers = _identifiers(self.identifiers)

    @classmethod
    def empty(cls, user: UserId) -> "Profile":
        return cls(id=user)

    def evidence(self) -> list[Identifier]:
        """The identifiers that find the person: their own and the e-mail address."""
        found = list(self.identifiers)
        if self.email is not None:
            address = Identifier(IdentifierKind.EMAIL_ADDRESS, self.email)
            if address.key not in {item.key for item in found}:
                found.append(address)
        return found


@dataclass(frozen=True)
class Person:
    """What finds a user in a document: their display name and aliases (never the username),
    birth date and identifiers. Private: built for matching only. `private`: whether what is
    private about them may find them (also a contact's number that names them); `public()` is
    what anyone may match, the display name alone."""

    user_id: UserId
    display_name: str | None = None
    aliases: tuple[str, ...] = ()
    birth_date: date | None = None
    identifiers: tuple[Identifier, ...] = ()
    private: bool = True

    @classmethod
    def of(cls, user: User, profile: Profile | None) -> "Person":
        if profile is None:
            return cls(user.id, user.display_name)
        return cls(
            user.id,
            user.display_name,
            tuple(profile.aliases),
            profile.birth_date,
            tuple(profile.evidence()),
        )

    @property
    def names(self) -> tuple[str, ...]:
        """The display name, then the aliases."""
        return (*((self.display_name,) if self.display_name else ()), *self.aliases)

    def public(self) -> "Person":
        """The person as anyone may find them: by their display name, nothing private."""
        return Person(self.user_id, self.display_name, private=False)


def _aliases(aliases: Iterable[str]) -> list[str]:
    kept: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        name = require_name(alias, "alias", max_length=MAX_DISPLAY_NAME)
        if name_key(name) in seen:
            raise ValidationError(because(ReasonCode.ALIAS_TWICE, alias=name))
        seen.add(name_key(name))
        kept.append(name)
    if len(kept) > MAX_ALIASES:
        raise ValidationError(because(ReasonCode.PERSON_TOO_MANY_ALIASES, max=MAX_ALIASES))
    return kept


def _identifiers(identifiers: Iterable[Identifier]) -> list[Identifier]:
    kept: dict[tuple[IdentifierKind, str], Identifier] = {}
    for item in identifiers:
        if item.kind not in PERSON_KINDS:
            raise ValidationError(f"a person has no identifier of the kind '{item.kind.value}'")
        kept.setdefault(item.key, Identifier(item.kind, item.value))
    if len(kept) > MAX_PERSON_IDENTIFIERS:
        raise ValidationError(
            because(ReasonCode.PERSON_TOO_MANY_IDENTIFIERS, max=MAX_PERSON_IDENTIFIERS)
        )
    return list(kept.values())
