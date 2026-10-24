"""A contact's or a person's identifier as stored: kind, normalised value, where it comes from
(`IdentifierSource`), and for a contact's the topic it points to, the user it names and the
spaces it was learned in."""

from dataclasses import dataclass
from enum import StrEnum

from lekto.core.domain.identifiers.base import IdentifierKind, Key
from lekto.core.domain.identifiers.registry import TYPES, normalise_identifier
from lekto.core.domain.ids import SpaceId, TagId, UserId

MAX_IDENTIFIERS = 100
"""Identifiers of one contact, entered and learned."""


class IdentifierSource(StrEnum):
    MANUAL = "manual"
    LEARNED = "learned"
    REJECTED = "rejected"  # learned, then rejected (by an admin, or declined by its user)


@dataclass(frozen=True)
class Identifier:
    """`value` is normalised (see `normalise_identifier`); kind and value are unique across
    all contacts. `topic_id`: the topic of its contact it points to, if any (the contact checks
    that it enables it). `user_id`: the user a contact's customer or personnel number belongs
    to, if one does (entered by hand, or found by training); found in a document, it is
    evidence for them too. `learned_in`: the spaces of the confirmed documents a learned one
    was learned from (`seen_by`). A person's identifier has none of them."""

    kind: IdentifierKind
    value: str
    source: IdentifierSource = IdentifierSource.MANUAL
    topic_id: TagId | None = None
    user_id: UserId | None = None
    learned_in: frozenset[SpaceId] = frozenset()

    @classmethod
    def parse(
        cls,
        kind: IdentifierKind,
        raw: str,
        source: IdentifierSource = IdentifierSource.MANUAL,
        topic_id: TagId | None = None,
        user_id: UserId | None = None,
    ) -> "Identifier":
        return cls(kind, normalise_identifier(kind, raw), source, topic_id, user_id)

    @property
    def key(self) -> Key:
        return self.kind, self.value

    @property
    def manual(self) -> bool:
        """Whether a person entered it by hand."""
        return self.source is IdentifierSource.MANUAL

    @property
    def counts(self) -> bool:
        """Whether it is evidence (a rejected one only keeps training from learning it)."""
        return self.source is not IdentifierSource.REJECTED


def matches(identifier: Identifier, found: Key) -> bool:
    """Whether a found value is the identifier (`IdentifierType.matches`: a domain also stands
    for its subdomains)."""
    kind, value = found
    return kind is identifier.kind and TYPES[kind].matches(identifier.value, value)
