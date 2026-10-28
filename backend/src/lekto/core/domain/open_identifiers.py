"""The open identifiers (`.idea/umsetzungsplan.md`, "Übersicht und Kennungen"): the identifiers
no person has confirmed yet, across all contacts and documents. A learned one stands at a contact
(training found it); an unknown one stands in confirmed documents of a contact's kind
(`CONTACT_KINDS`) but at no contact, neither entered, learned nor rejected. A person's value (a
user's profile, `of_person`) and a free mail domain are never open, nor an IBAN or a creditor ID
a person holds in any document; one counts only in the documents where it is their contact's
(`domain.holders`: not a payee's on a bank statement). A suggested one is an IBAN or a creditor
ID open nowhere else whose holder a document names: for that person's profile, or for that
contact (the landlord's IBAN in the bookings of a bank statement)."""

import re
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from lekto.core.domain.document_facts import HOLDER_KINDS, DocumentFact, HolderKind
from lekto.core.domain.holders import Parties, foreign
from lekto.core.domain.identifiers import (
    CONTACT_KINDS,
    FREE_MAIL,
    Identifier,
    IdentifierKind,
    IdentifierSource,
    Key,
    matches,
    of_person,
)
from lekto.core.domain.ids import ContactId, DocumentId, UserId
from lekto.core.domain.master_data import Contact
from lekto.core.domain.profiles import Person

REACH = 120
"""Characters of text shown before and after an identifier where it stands."""


class OpenSource(StrEnum):
    LEARNED = "learned"
    UNKNOWN = "unknown"
    SUGGESTED = "suggested"  # an IBAN or a creditor ID a document names as another's


@dataclass(frozen=True)
class Sighting:
    """A fact of a confirmed document with a contact, where the open identifiers are looked for
    (`DocumentFactRepository.sightings`): the document, its contact and date (the document's
    date, else the day it came), the fact as it stands there, and the user whose personal space
    the document lies in (None: a shared space)."""

    document: DocumentId
    contact: ContactId
    dated: date
    fact: DocumentFact
    owner: UserId | None = None


@dataclass(frozen=True)
class OpenIdentifier:
    """An identifier no person has confirmed: its kind and value (normalised, and as the newest
    document writes it), where it is open, and the confirmed documents that show it, newest
    first. `contacts`: a learned one's contact; an unknown one's are the contacts of its
    documents, the one with most documents first; a suggested one's the contact it belongs to,
    or none and the `person` it belongs to."""

    kind: IdentifierKind
    value: str
    written: str
    source: OpenSource
    contacts: tuple[ContactId, ...]
    seen: tuple[Sighting, ...]
    person: UserId | None = None

    @property
    def key(self) -> Key:
        return self.kind, self.value

    @property
    def last(self) -> date | None:
        return self.seen[0].dated if self.seen else None


def open_identifiers(
    contacts: Iterable[Contact],
    sightings: Iterable[Sighting],
    personal: Collection[Key] = (),
    persons: Iterable[Person] = (),
    declined: Mapping[UserId, Collection[Key]] | None = None,
) -> list[OpenIdentifier]:
    """The open identifiers among `contacts` and the facts `sightings` in confirmed documents
    (`personal`: the persons' values), the most documents first, then the newest. With
    `persons`, an IBAN a document's recipient holds is suggested for one of them (named, or
    the user whose personal space the document lies in; not one they `declined`), and an IBAN
    or a creditor ID a document names as another contact's for that contact."""
    contacts = list(contacts)
    seen = [item for item in sightings if item.fact.kind in CONTACT_KINDS]
    stated = [item for contact in contacts for item in contact.identifiers]
    by_key: dict[Key, list[Sighting]] = defaultdict(list)
    for item in seen:
        by_key[item.fact.key].append(item)
    found: list[OpenIdentifier] = []
    for contact in contacts:
        for identifier in contact.identifiers:
            if identifier.source is not IdentifierSource.LEARNED:
                continue
            shown = [item for key, items in by_key.items() if matches(identifier, key)
                     for item in items]  # fmt: skip
            found.append(_open(identifier.key, OpenSource.LEARNED, (contact.id,), shown))
    names = {contact.id: contact.names() for contact in contacts}
    for key, items in by_key.items():
        kind, value = key
        if (
            any(matches(identifier, key) for identifier in stated)
            or of_person(key, personal)
            or (kind is IdentifierKind.EMAIL_DOMAIN and value in FREE_MAIL)
            or any(_held(item, HolderKind.RECIPIENT) for item in items)
        ):
            continue
        # An IBAN or a creditor ID counts only where it is its contact's (`domain.holders`):
        # not a payee's on a bank statement.
        items = [item for item in items if not foreign(item.fact.holder, names[item.contact])]
        if not items:
            continue
        counts = Counter(item.contact for item in items)
        owners = tuple(sorted(counts, key=lambda contact: (-counts[contact], str(contact))))
        found.append(_open(key, OpenSource.UNKNOWN, owners, items))
    found += _suggested(contacts, by_key, {item.key for item in found}, stated, personal,
                        list(persons), declined or {})  # fmt: skip
    return sorted(
        found,
        key=lambda item: (
            -len(item.seen),
            -(item.last or date.min).toordinal(),
            item.kind.value,
            item.value,
        ),
    )


def _suggested(
    contacts: Sequence[Contact],
    by_key: Mapping[Key, Sequence[Sighting]],
    opened: Collection[Key],
    stated: Sequence[Identifier],
    personal: Collection[Key],
    persons: Sequence[Person],
    declined: Mapping[UserId, Collection[Key]],
) -> list[OpenIdentifier]:
    """The IBANs and creditor IDs open nowhere else whose holder a document names: a person
    (the recipient's), else another contact than the document's."""
    contact_names = {contact.id: Parties(contact_names=contact.names()) for contact in contacts}
    person_names = {
        person.user_id: Parties(person_names=[person.display_name or "", *person.aliases])
        for person in persons
    }
    found = []
    for key, items in by_key.items():
        if (
            key[0] not in HOLDER_KINDS
            or key in opened
            or any(matches(identifier, key) for identifier in stated)
            or of_person(key, personal)
        ):
            continue
        received = [item for item in items if _held(item, HolderKind.RECIPIENT)]
        if received:
            users = {_recipient(item, person_names) for item in received}
            user = users.pop() if len(users) == 1 else None
            if user is not None and key not in declined.get(user, ()):
                found.append(_open(key, OpenSource.SUGGESTED, (), received, person=user))
            continue
        named = [
            (item, target)
            for item in items
            if (holder := item.fact.holder) is not None
            and holder.name
            and holder.kind in (HolderKind.SENDER, HolderKind.THIRD_PARTY)
            and (target := _contact_named(holder.name, contact_names)) is not None
            and target != item.contact
        ]
        targets = {target for _, target in named}
        if len(targets) == 1:
            found.append(
                _open(key, OpenSource.SUGGESTED, (targets.pop(),), [item for item, _ in named])
            )
    return found


def _recipient(item: Sighting, persons: Mapping[UserId, Parties]) -> UserId | None:
    """The person a recipient's number belongs to: the one its name names, else the user whose
    personal space the document lies in."""
    name = item.fact.holder.name if item.fact.holder is not None else None
    if name:
        named = [user for user, parties in persons.items() if parties.person(name)]
        return named[0] if len(named) == 1 else None
    return item.owner


def _contact_named(name: str, contacts: Mapping[ContactId, Parties]) -> ContactId | None:
    """The one contact `name` names; None for none or several."""
    named = [contact for contact, parties in contacts.items() if parties.contact(name)]
    return named[0] if len(named) == 1 else None


def _held(item: Sighting, kind: HolderKind) -> bool:
    return item.fact.holder is not None and item.fact.holder.kind is kind


def _open(
    key: Key,
    source: OpenSource,
    contacts: tuple[ContactId, ...],
    seen: Sequence[Sighting],
    *,
    person: UserId | None = None,
) -> OpenIdentifier:
    kind, value = key
    newest = sorted(seen, key=lambda item: (item.dated, str(item.document)), reverse=True)
    # One sighting per document (a learned customer number may stand there as a contract number
    # too).
    unique = list({item.document: item for item in reversed(newest)}.values())[::-1]
    written = next((item.fact.written for item in unique if item.fact.written), None)
    return OpenIdentifier(kind, value, written or value, source, contacts, tuple(unique), person)


@dataclass(frozen=True)
class Excerpt:
    """Where an identifier stands in a text: the text before it, as written, and after it,
    each on one line, cut at a word, with "…" where the text goes on."""

    before: str
    match: str
    after: str


_SPACE = re.compile(r"\s+")


def excerpt(text: str, position: int, length: int, reach: int = REACH) -> Excerpt:
    """The text around the stretch at `position` of `length` characters."""
    start, end = max(0, position), min(len(text), position + length)
    before = text[max(0, start - reach) : start]
    after = text[end : end + reach]
    if start > reach:
        before = "…" + before.split(None, 1)[-1] if " " in before.strip() else "…" + before
    if end + reach < len(text):
        after = after.rsplit(None, 1)[0] + "…" if " " in after.strip() else after + "…"
    return Excerpt(
        _SPACE.sub(" ", before).lstrip(),
        _SPACE.sub(" ", text[start:end]),
        _SPACE.sub(" ", after).rstrip(),
    )
