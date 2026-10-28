"""A contact's or a person's identifier as stored: kind, normalised value, where it comes from
(`IdentifierSource`), and for a contact's the topic it points to, the user it names and the
spaces it was learned in."""

from collections import defaultdict
from collections.abc import Iterable, Iterator
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


CUSTOMER_KINDS = frozenset(
    {
        IdentifierKind.CONTRACT_NUMBER,
        IdentifierKind.POLICY_NUMBER,
        IdentifierKind.MEMBERSHIP_NUMBER,
    }
)
"""What a customer number was until #145 (its labels): a contact's customer number still
matches a number of these kinds with its value."""


def related_keys(key: Key) -> frozenset[Key]:
    """`key` and the values it is the same number as across the split of #145: a customer
    number and the contract, policy and membership numbers of its value (`CUSTOMER_KINDS`)."""
    kind, value = key
    if kind is IdentifierKind.CUSTOMER_NUMBER:
        return frozenset({key, *((other, value) for other in CUSTOMER_KINDS)})
    if kind in CUSTOMER_KINDS:
        return frozenset({key, (IdentifierKind.CUSTOMER_NUMBER, value)})
    return frozenset({key})


def matches(identifier: Identifier, found: Key) -> bool:
    """Whether a found value is the identifier (`IdentifierType.matches`: a domain also stands
    for its subdomains); a contact's customer number is also the contract, policy or
    membership number of its value (`CUSTOMER_KINDS`: the kind was one until #145)."""
    kind, value = found
    if identifier.kind is IdentifierKind.CUSTOMER_NUMBER and kind in CUSTOMER_KINDS:
        return value == identifier.value
    return kind is identifier.kind and TYPES[kind].matches(identifier.value, value)


class KeyIndex[T]:
    """Identifiers with what belongs to each (`T`: their contact, the identifier itself), to
    tell for a found key which of them it is (`matches`) without comparing it with each: by
    its own key, a found contract, policy or membership number also as the customer number of
    its value (`CUSTOMER_KINDS`), a found domain also as each domain it is a subdomain of."""

    def __init__(self, items: Iterable[tuple[Identifier, T]]) -> None:
        self._by_key: dict[Key, list[T]] = defaultdict(list)
        for identifier, item in items:
            self._by_key[identifier.key].append(item)

    def matching(self, found: Key) -> list[T]:
        """What belongs to the identifiers `found` is."""
        return [item for key in _lookups(found) for item in self._by_key.get(key, ())]


def _lookups(found: Key) -> Iterator[Key]:
    """The keys an identifier that `found` matches may be stored under."""
    kind, value = found
    yield found
    if kind in CUSTOMER_KINDS:
        yield IdentifierKind.CUSTOMER_NUMBER, value
    if kind is IdentifierKind.EMAIL_DOMAIN:
        labels = value.split(".")
        for start in range(1, len(labels)):
            yield kind, ".".join(labels[start:])
