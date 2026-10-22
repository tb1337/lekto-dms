"""What a document shows of its contact: names of contacts and identifiers, in its text and in
the codes on its pages, each with where it stands in the text.

The facts signal reports them for the judge (`signal_facts`); a person sees them beside the
text. A name counts whole (`names.mentions`); in a code only the payee of a GiroCode is a name.
A found identifier is matched with the contacts' (`identifiers.matches`): one that counts
(entered or learned) is evidence for its contact, and for its topic if it points to one; a
rejected one is known, but neither evidence nor unknown.

Persons (Tobi, 21.10.2026): a user is found by their identifiers (hard evidence: one of their
own, or a contact's customer or personnel number that names them), their birth date (medium)
and their display name or aliases (weak: an address block names everyone in a household). A
person's own numbers are no contact's: they never show as unknown identifiers. Only user ids and
the kinds of evidence leave this module's results for the log, never the values.

Where it stands: character spans of the text (`spans`), found with the written forms a value
has (an IBAN in groups of four, a customer number with dashes, a name with any spaces and
punctuation between its words, umlauts or not). A name broken over two columns has none. Where
the words of the text have their boxes, a span also has its places on the pages (`on_pages`).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import islice

from lekto.core.domain.codes import Code, code_identifiers, giro_code
from lekto.core.domain.evidence import UMLAUTS, dates_in, normalise
from lekto.core.domain.identifiers import CONTACT_KINDS, IdentifierKind, identifiers_in, matches
from lekto.core.domain.ids import ContactId, TagId, UserId
from lekto.core.domain.locations import Location
from lekto.core.domain.master_data import Contact
from lekto.core.domain.names import match_key, mentions
from lekto.core.domain.profiles import Person
from lekto.core.domain.text_places import TextPlaces

MOST = 20
"""Names and identifiers reported, each."""
_SPANS = 20  # places of one fact in the text
# How a folded name may be written: `ae` as `ä` or `ae`, and so on.
_SPELLINGS = {plain: f"(?:{letter}|{plain})" for letter, plain in {**UMLAUTS, "ß": "ss"}.items()}

type Key = tuple[IdentifierKind, str]


@dataclass(frozen=True)
class Span:
    """Characters `start` to `end` (exclusive) of the text, and where they stand on the pages
    (none where that is not known)."""

    start: int
    end: int
    locations: tuple[Location, ...] = ()


@dataclass(frozen=True, kw_only=True)
class NamedContact:
    contact_id: ContactId
    name: str  # the name or alias as the contact has it
    alias: bool
    in_text: bool
    in_code: bool  # the payee of a GiroCode
    spans: tuple[Span, ...] = ()


@dataclass(frozen=True, kw_only=True)
class FoundIdentifier:
    kind: IdentifierKind
    value: str  # normalised
    contact_id: ContactId | None  # the contact it is an identifier of, if one that counts
    in_text: bool
    in_code: bool
    spans: tuple[Span, ...] = ()
    topic_id: TagId | None = None  # the contact's topic it points to, if any

    @property
    def key(self) -> Key:
        return (self.kind, self.value)


class Strength(StrEnum):
    """How surely a document names a person."""

    WEAK = "weak"  # their display name or an alias
    MEDIUM = "medium"  # their birth date (in the judge also the model's recipient)
    HARD = "hard"  # one of their identifiers

    @property
    def rank(self) -> int:
        return _RANKS[self]


_RANKS = {Strength.WEAK: 1, Strength.MEDIUM: 2, Strength.HARD: 3}
NAME = "name"
ALIAS = "alias"
BIRTH_DATE = "birth_date"


@dataclass(frozen=True, kw_only=True)
class FoundPerson:
    """A user the document names: the strongest evidence, the kinds of all of it (`name`,
    `alias`, `birth_date`, the kinds of identifiers), and where names and identifiers stand."""

    user_id: UserId
    strength: Strength
    evidence: tuple[str, ...]
    spans: tuple[Span, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Facts:
    named: tuple[NamedContact, ...]
    identifiers: tuple[FoundIdentifier, ...]  # those of contacts first, then the unknown
    persons: tuple[FoundPerson, ...] = ()  # the surest first


def facts_in(
    text: str,
    contacts: Sequence[Contact],
    codes: Sequence[Code] = (),
    *,
    persons: Sequence[Person] = (),
    places: bool = False,
) -> Facts:
    """The facts of `text` and of the `codes` on its pages, the `persons` among them; with
    `places`, their spans."""
    text_key = match_key(text)
    payees = [match_key(giro.name) for code in codes if (giro := giro_code(code.text))]
    named: list[NamedContact] = []
    for contact in contacts:
        own = next((name for name in contact.names() if mentions(text_key, match_key(name))), None)
        paid = next(
            (n for n in contact.names() if any(mentions(p, match_key(n)) for p in payees)), None
        )
        name = own if own is not None else paid
        if name is None:
            continue
        named.append(
            NamedContact(
                contact_id=contact.id,
                name=name,
                alias=name != contact.name,
                in_text=own is not None,
                in_code=paid is not None,
                spans=name_spans(text, name) if places and own is not None else (),
            )
        )
    in_text = identifiers_in(text)
    in_codes: set[Key] = set()
    for code in codes:
        in_codes |= code_identifiers(code)
    owners: dict[Key, ContactId] = {}
    topics: dict[Key, TagId | None] = {}
    rejected: set[Key] = set()
    for contact in contacts:
        for identifier in contact.identifiers:
            for key in in_text | in_codes:
                if matches(identifier, key):
                    if identifier.counts:
                        if key not in owners:
                            owners[key] = contact.id
                            topics[key] = identifier.topic_id
                    else:
                        rejected.add(key)
    found_persons = _persons(text, text_key, in_text | in_codes, contacts, persons, places=places)
    personal = {key for person in persons for item in person.identifiers for key in [item.key]}
    found = [
        FoundIdentifier(
            kind=kind,
            value=value,
            contact_id=owners.get((kind, value)),
            in_text=(kind, value) in in_text,
            in_code=(kind, value) in in_codes,
            spans=identifier_spans(text, kind, value) if places else (),
            topic_id=topics.get((kind, value)),
        )
        for kind, value in sorted(in_text | in_codes, key=lambda key: (key[0].value, key[1]))
        if kind in CONTACT_KINDS
        and (
            (kind, value) in owners
            or ((kind, value) not in rejected and (kind, value) not in personal)
        )
    ]
    known = [item for item in found if item.contact_id is not None]
    unknown = [item for item in found if item.contact_id is None]
    return Facts(
        named=tuple(named[:MOST]),
        identifiers=(*known[:MOST], *unknown[:MOST]),
        persons=found_persons,
    )


def _persons(
    text: str,
    text_key: str,
    keys: set[Key],
    contacts: Sequence[Contact],
    persons: Sequence[Person],
    *,
    places: bool,
) -> tuple[FoundPerson, ...]:
    """The persons `text` names, the surest first (then by user id)."""
    evidence: dict[UserId, list[tuple[Strength, str, tuple[Span, ...]]]] = {}

    def add(user: UserId, strength: Strength, kind: str, spans: tuple[Span, ...] = ()) -> None:
        evidence.setdefault(user, []).append((strength, kind, spans))

    for person in persons:
        for identifier in person.identifiers:
            for key in keys:
                if matches(identifier, key):
                    spans = identifier_spans(text, *key) if places else ()
                    add(person.user_id, Strength.HARD, identifier.kind.value, spans)
    for contact in contacts:
        for identifier in contact.evidence():
            if identifier.user_id is None:
                continue
            for key in keys:
                if matches(identifier, key):
                    spans = identifier_spans(text, *key) if places else ()
                    add(identifier.user_id, Strength.HARD, identifier.kind.value, spans)
    if any(person.birth_date is not None for person in persons):
        days = dates_in(normalise(text))
        for person in persons:
            if person.birth_date is not None and person.birth_date in days:
                add(person.user_id, Strength.MEDIUM, BIRTH_DATE)
    for person in persons:
        for name in person.names:
            if mentions(text_key, match_key(name)):
                spans = name_spans(text, name) if places else ()
                kind = NAME if name == person.display_name else ALIAS
                add(person.user_id, Strength.WEAK, kind, spans)
                break
    found = []
    for user, items in evidence.items():
        items.sort(key=lambda item: -item[0].rank)
        kinds = tuple(dict.fromkeys(kind for _, kind, _ in items))
        spans = tuple(span for _, _, spans in items for span in spans)[:_SPANS]
        found.append(FoundPerson(user_id=user, strength=items[0][0], evidence=kinds, spans=spans))
    found.sort(key=lambda item: (-item.strength.rank, str(item.user_id)))
    return tuple(found[:MOST])


def on_pages(facts: Facts, places: TextPlaces) -> Facts:
    """The facts with where each of their spans stands on the pages."""

    def placed(spans: tuple[Span, ...]) -> tuple[Span, ...]:
        return tuple(
            replace(span, locations=places.locations(span.start, span.end)) for span in spans
        )

    return Facts(
        named=tuple(replace(item, spans=placed(item.spans)) for item in facts.named),
        identifiers=tuple(replace(item, spans=placed(item.spans)) for item in facts.identifiers),
        persons=tuple(replace(item, spans=placed(item.spans)) for item in facts.persons),
    )


def name_spans(text: str, name: str) -> tuple[Span, ...]:
    """Where a name stands in `text`: its words in order, anything but letters and digits
    between them, umlauts or their spellings; legal forms aside, as names are compared."""
    words = match_key(name).split()
    if not words:
        return ()
    pattern = r"[\W_]+".join(_spelling(word) for word in words)
    return _spans(rf"(?<!\w){pattern}(?!\w)", text)


def identifier_spans(text: str, kind: IdentifierKind, value: str) -> tuple[Span, ...]:
    """Where an identifier stands in `text`, as it may be written: separators between its
    characters (an IBAN, a VAT, customer or personnel number), any case; a personnel number
    also with leading zeros."""
    if kind is IdentifierKind.EMAIL_DOMAIN:
        return _spans(rf"(?<![\w-]){re.escape(value)}(?![\w-])", text)
    if kind is IdentifierKind.EMAIL_ADDRESS:
        return _spans(rf"(?<![\w.%+-]){re.escape(value)}(?![\w-])", text)
    pattern = r"[\s./-]?".join(re.escape(char) for char in value)
    if kind is IdentifierKind.PERSONNEL_NUMBER:
        pattern = rf"(?:0[\s./-]?)*{pattern}"
    return _spans(rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])", text)


def _spelling(word: str) -> str:
    pattern = re.escape(word)
    for folded, written in _SPELLINGS.items():
        pattern = pattern.replace(folded, written)
    return pattern


def _spans(pattern: str, text: str) -> tuple[Span, ...]:
    found = re.finditer(pattern, text, re.IGNORECASE)
    return tuple(Span(match.start(), match.end()) for match in islice(found, _SPANS))
