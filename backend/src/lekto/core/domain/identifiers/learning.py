"""Learning identifiers of contacts from confirmed documents (`mine_identifiers`): a value that
stands in at least two of them, all of one contact. A value in documents of several contacts
(the owner's own IBAN on every direct debit) is never learned. A learned one points to the
topic all its documents carry, keeps the spaces they lie in, and a customer or personnel number
the user they all surely belong to."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from lekto.core.domain.identifiers.base import IdentifierKind
from lekto.core.domain.identifiers.identifier import (
    MAX_IDENTIFIERS,
    Identifier,
    IdentifierSource,
    related_keys,
)
from lekto.core.domain.identifiers.reading import of_person
from lekto.core.domain.identifiers.registry import CONTACT_KINDS, NAMING_KINDS
from lekto.core.domain.ids import ContactId, SpaceId, TagId, UserId

LEARN_FROM = 2
"""Confirmed documents of one contact a value must stand in to be learned."""


@dataclass(frozen=True)
class Confirmed:
    """A confirmed document as training learns from it: its contact and topic, the identifiers
    in its text, the space it lies in, and whose it surely is (`whose`: the user of the personal
    space it lies in and the users it names by more than their name)."""

    contact: ContactId | None
    topic: TagId | None
    found: frozenset[tuple[IdentifierKind, str]]
    space: SpaceId | None = None
    whose: frozenset[UserId] = frozenset()


def mine_identifiers(
    documents: Iterable[Confirmed],
    taken: Iterable[tuple[IdentifierKind, str]] = (),
    personal: Iterable[tuple[IdentifierKind, str]] = (),
) -> Mapping[ContactId, list[Identifier]]:
    """The identifiers to learn from confirmed documents: a value that stands in at least
    `LEARN_FROM` documents, all with the same contact. A document without a contact counts as
    another contact. `taken` (entered by hand or rejected anywhere, with the numbers it is the
    same as: `related_keys`) is never learned, nor what
    is one of the persons' values `personal` (`of_person`: also a customer number that stands
    in a social security number). A learned value points to a topic if all its documents carry
    that one; otherwise to none. It notes the spaces its documents lie in (`learned_in`); a
    customer or personnel number belongs to a user if every one of its documents is surely that
    user's alone (`Confirmed.whose`). Only the kinds of contacts are learned (`CONTACT_KINDS`):
    a person's numbers never become a contact's."""
    holders: dict[tuple[IdentifierKind, str], list[Confirmed]] = defaultdict(list)
    for document in documents:
        for key in document.found:
            holders[key].append(document)
    skip = {related for key in taken for related in related_keys(key)}
    persons = list(personal)
    learned: dict[ContactId, list[Identifier]] = defaultdict(list)
    for (kind, value), held in sorted(holders.items()):
        owners = {document.contact for document in held}
        if (
            kind not in CONTACT_KINDS
            or (kind, value) in skip
            or of_person((kind, value), persons)
            or len(held) < LEARN_FROM
            or len(owners) != 1
        ):
            continue
        (owner,) = owners
        topics = {document.topic for document in held}
        topic = next(iter(topics)) if len(topics) == 1 else None
        whose = {document.whose for document in held}
        user = None
        if kind in NAMING_KINDS and len(whose) == 1 and len(alone := next(iter(whose))) == 1:
            (user,) = alone
        spaces = frozenset(document.space for document in held if document.space is not None)
        if owner is not None:
            learned[owner].append(
                Identifier(kind, value, IdentifierSource.LEARNED, topic, user, spaces)
            )
    return {owner: found[:MAX_IDENTIFIERS] for owner, found in learned.items()}
