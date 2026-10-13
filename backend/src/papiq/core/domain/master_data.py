"""Master data: contacts, document types and tags. Global, no owner; only admins change them."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Self

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.identifiers import (
    MAX_IDENTIFIERS,
    Identifier,
    IdentifierKind,
    IdentifierSource,
)
from papiq.core.domain.ids import ContactId, DocumentTypeId, TagId, new_id
from papiq.core.domain.validation import name_key, require_name, require_utc

MAX_ALIASES = 100
"""Aliases of one contact."""
MAX_DESCRIPTION = 300
"""Characters of a document type's description; it goes into every classification prompt."""


@dataclass(kw_only=True)
class MasterData:
    """Common part of all master data: a name unique per kind regardless of case."""

    name: str
    created_at: datetime
    version: int = 1

    def __post_init__(self) -> None:
        self.name = require_name(self.name)
        self.created_at = require_utc(self.created_at, "created_at")

    def rename(self, name: str) -> None:
        self.name = require_name(name)


@dataclass(kw_only=True)
class Contact(MasterData):
    """The other party of a document (Paperless-ngx: correspondent).

    `aliases` are other names the contact is written as in documents ("Nord Krankenversicherung
    AG" for "Nord Versicherungsgruppe"); classification matches them like the name. They are
    unique regardless of case and differ from the name; across contacts, names and aliases are
    unique too (see `MasterDataService`).

    `identifiers` are values its documents carry (see `identifiers`): entered by hand, learned
    by training, or learned and rejected. Each value belongs to one contact at most."""

    id: ContactId
    aliases: list[str] = field(default_factory=list)
    identifiers: list[Identifier] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.aliases = _aliases(self.name, self.aliases)
        self.identifiers = _identifiers(self.identifiers)

    @classmethod
    def create(
        cls,
        *,
        name: str,
        now: datetime,
        aliases: Iterable[str] = (),
        identifiers: Iterable[Identifier] = (),
    ) -> Self:
        contact = cls(id=ContactId(new_id()), name=name, created_at=now, aliases=list(aliases))
        contact.set_identifiers(identifiers)
        return contact

    def rename(self, name: str) -> None:
        """An alias that becomes the name is no longer an alias."""
        name = require_name(name)
        self.aliases = [alias for alias in self.aliases if name_key(alias) != name_key(name)]
        self.name = name

    def set_aliases(self, aliases: Iterable[str]) -> None:
        self.aliases = _aliases(self.name, aliases)

    def names(self) -> list[str]:
        """The name and the aliases."""
        return [self.name, *self.aliases]

    def set_identifiers(
        self, entered: Iterable[Identifier], rejected: Iterable[Identifier] | None = None
    ) -> None:
        """`entered` replaces the identifiers entered by hand (a learned one entered is then
        one entered by hand); `rejected`, if given, the rejected ones (a learned one rejected
        no longer counts, and training does not learn it again)."""
        manual = {item.key: Identifier(item.kind, item.value) for item in entered}
        if rejected is None:
            blocked = {item.key for item in self.identifiers if not item.counts}
        else:
            blocked = {item.key for item in rejected}
        blocked -= manual.keys()
        learned = [
            item
            for item in self.identifiers
            if item.source is IdentifierSource.LEARNED
            and item.key not in manual
            and item.key not in blocked
        ]
        refused = [Identifier(kind, value, IdentifierSource.REJECTED) for kind, value in blocked]
        self.identifiers = _identifiers([*manual.values(), *learned, *refused])

    def set_learned(self, learned: Iterable[Identifier]) -> None:
        """Replace the learned identifiers; values entered by hand or rejected stay as they
        are."""
        kept = [item for item in self.identifiers if item.source is not IdentifierSource.LEARNED]
        taken = {item.key for item in kept}
        fresh = [
            Identifier(item.kind, item.value, IdentifierSource.LEARNED)
            for item in learned
            if item.key not in taken
        ]
        self.identifiers = _identifiers([*kept, *fresh])

    def drop_identifier(self, key: tuple[IdentifierKind, str]) -> bool:
        """Forget the value (another contact took it); whether it was there."""
        kept = [item for item in self.identifiers if item.key != key]
        changed = len(kept) < len(self.identifiers)
        self.identifiers = kept
        return changed

    def evidence(self) -> list[Identifier]:
        """The identifiers that count: entered and learned."""
        return [item for item in self.identifiers if item.counts]

    def is_named(self, name: str) -> bool:
        """Whether `name` is the name or an alias, regardless of case."""
        key = name_key(name)
        return any(name_key(own) == key for own in self.names())


@dataclass(kw_only=True)
class DocumentType(MasterData):
    """The kind of a document; field definitions can be bound to it. `description` tells the
    language model what belongs to the type ("pay slips, Entgeltbescheinigung, ...")."""

    id: DocumentTypeId
    description: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.description = _description(self.description)

    @classmethod
    def create(cls, *, name: str, now: datetime, description: str | None = None) -> Self:
        return cls(id=DocumentTypeId(new_id()), name=name, created_at=now, description=description)

    def describe(self, description: str | None) -> None:
        self.description = _description(description)


@dataclass(kw_only=True)
class Tag(MasterData):
    """A label; tags carry no permissions."""

    id: TagId

    @classmethod
    def create(cls, *, name: str, now: datetime) -> Self:
        return cls(id=TagId(new_id()), name=name, created_at=now)


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def one_line(text: str) -> str:
    """Control characters and runs of white space as one space: names go into prompts, where a
    line break could start an instruction."""
    return " ".join(_CONTROL.sub(" ", text).split())


def _aliases(name: str, aliases: Iterable[str]) -> list[str]:
    """On one line, without duplicates (regardless of case); none may be the name."""
    result: list[str] = []
    keys = {name_key(name)}
    for alias in aliases:
        alias = require_name(one_line(alias), "alias")
        key = name_key(alias)
        if key == name_key(name):
            raise ValidationError(f"the alias '{alias}' is the contact's name")
        if key not in keys:
            keys.add(key)
            result.append(alias)
    if len(result) > MAX_ALIASES:
        raise ValidationError(f"a contact has at most {MAX_ALIASES} aliases")
    return result


_SOURCE_ORDER = {source: order for order, source in enumerate(IdentifierSource)}
_KIND_ORDER = {kind: order for order, kind in enumerate(IdentifierKind)}


def _identifiers(identifiers: Iterable[Identifier]) -> list[Identifier]:
    """Without duplicates (the first of a value wins), entered first, then learned, then
    rejected; at most `MAX_IDENTIFIERS` that count."""
    seen: set[tuple[IdentifierKind, str]] = set()
    result: list[Identifier] = []
    for item in identifiers:
        if item.key not in seen:
            seen.add(item.key)
            result.append(item)
    result.sort(key=lambda item: (_SOURCE_ORDER[item.source], _KIND_ORDER[item.kind], item.value))
    if sum(item.counts for item in result) > MAX_IDENTIFIERS:
        raise ValidationError(f"a contact has at most {MAX_IDENTIFIERS} identifiers")
    return result


def _description(description: str | None) -> str | None:
    text = (description or "").strip()
    if len(text) > MAX_DESCRIPTION:
        raise ValidationError(f"description must not be longer than {MAX_DESCRIPTION} characters")
    return text or None
