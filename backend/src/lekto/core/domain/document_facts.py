"""Facts as values of a document (`.idea/fakten.md`, issue #145): what a document shows that
marks something or points to something, numbers and references, each with its kind, its value
(normalised, as Lekto compares it), where it stands, where it comes from and its role.

A fact stands in the document and is not configured: it holds for every type, and Lekto
compares it across documents. The kinds are the identifiers' (`IdentifierKind`), fixed in the
code. Its role says what it is to the document (`FactRole`): the same number is the invoice's
own on the invoice and a reference on the reminder. Until the language model reads facts, the
role follows the kind (`role_of`).

A document keeps one fact per kind and value. The facts a source finds (patterns in the text,
codes on the pages, later the language model) are replaced with each run of the facts signal;
a person's correction (`FactState`, later) outlasts it.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.evidence import normalise
from lekto.core.domain.facts import identifier_spans
from lekto.core.domain.identifiers import IdentifierKind, Key, type_of


class FactRole(StrEnum):
    """What a fact is to the document that shows it (`fakten.md`, Rollen)."""

    CONTACT = "contact"  # points to the contact: customer number, personnel number, VAT ID
    TARGET = "target"  # points to what a series refers to: contract, policy, meter number
    OWN = "own"  # marks the document itself: invoice, credit note, order number
    THREAD = "thread"  # joins a strand: file reference, "our reference", claim, ticket
    REFERS = "refers"  # refers to another document: "your invoice no. …", "your letter of …"
    PERSON = "person"  # points to a person: tax ID, social security number


class FactOrigin(StrEnum):
    """Where a fact comes from; one fact may come from several sources."""

    PATTERN = "pattern"  # the patterns of its kind in the text
    CODE = "code"  # a code on the pages (the IBAN of a GiroCode)
    MODEL = "model"  # the language model
    PERSON = "person"  # a person added or corrected it


class FactState(StrEnum):
    """Whether a source found the fact as it is, or a person decided it."""

    FOUND = "found"  # as a source found it; replaced with each run of the facts signal
    ADDED = "added"  # a person added it
    CORRECTED = "corrected"  # a person corrected its value or role
    REJECTED = "rejected"  # a person rejected it: it is no fact of the document

    @property
    def by_person(self) -> bool:
        return self is not FactState.FOUND


ROLES: Mapping[IdentifierKind, FactRole] = {
    IdentifierKind.IBAN: FactRole.CONTACT,
    IdentifierKind.VAT_ID: FactRole.CONTACT,
    IdentifierKind.CUSTOMER_NUMBER: FactRole.CONTACT,
    IdentifierKind.PERSONNEL_NUMBER: FactRole.CONTACT,
    IdentifierKind.EMAIL_DOMAIN: FactRole.CONTACT,
    IdentifierKind.TAX_ID: FactRole.PERSON,
    IdentifierKind.SOCIAL_SECURITY_NUMBER: FactRole.PERSON,
    IdentifierKind.HEALTH_INSURANCE_NUMBER: FactRole.PERSON,
    IdentifierKind.EMAIL_ADDRESS: FactRole.PERSON,
}
"""The role a fact of each kind has until a source tells (a test holds that no kind is
missing)."""

MAX_WRITTEN = 200
"""Characters of a fact as written that are kept."""


def role_of(kind: IdentifierKind) -> FactRole:
    return ROLES[kind]


@dataclass(frozen=True, kw_only=True)
class DocumentFact:
    """A fact of a document. `value`: normalised, as Lekto compares it (`normalise_identifier`);
    `written`: as the text writes it where it stands first (None where only a code holds it);
    `position`: the first character there, which orders the facts as the text reads (None:
    only in a code)."""

    kind: IdentifierKind
    value: str
    role: FactRole
    origins: frozenset[FactOrigin]
    written: str | None = None
    position: int | None = None
    state: FactState = FactState.FOUND

    def __post_init__(self) -> None:
        if not self.value:
            raise ValidationError("a fact needs a value")
        if not self.origins:
            raise ValidationError("a fact comes from somewhere")
        if self.position is not None and self.position < 0:
            raise ValidationError("a fact's position is a character of the text")
        if self.written is not None:
            object.__setattr__(self, "written", self.written[:MAX_WRITTEN])

    @property
    def key(self) -> Key:
        return self.kind, self.value


def found_facts(
    text: str,
    in_text: Iterable[Key],
    in_codes: Iterable[Key] = (),
    places: Mapping[Key, int] | None = None,
) -> tuple[DocumentFact, ...]:
    """The facts a document shows: the identifiers in its text (`identifiers_in`) and in the
    codes on its pages (`code_identifiers`), each once, as the text reads (those only in a code
    last), with the role of its kind. Where one stands first is where its reader took it
    (`places`: in the normalised text, `places_in`), else where its value stands first."""
    texts, codes = set(in_text), set(in_codes)
    normalised = normalise(text) if places else ""
    facts = []
    for kind, value in texts | codes:
        origins = {FactOrigin.PATTERN} if (kind, value) in texts else set()
        if (kind, value) in codes:
            origins.add(FactOrigin.CODE)
        at = None if places is None else places.get((kind, value))
        where = _first(text, normalised, kind, value, at) if (kind, value) in texts else None
        facts.append(
            DocumentFact(
                kind=kind,
                value=value,
                role=role_of(kind),
                origins=frozenset(origins),
                written=None if where is None else text[where[0] : where[1]],
                position=None if where is None else where[0],
            )
        )
    return tuple(sorted(facts, key=reading_order))


def reading_order(fact: DocumentFact) -> tuple[int, int, str, str]:
    """As the text reads: by position, those without one last, then by kind and value."""
    return (
        0 if fact.position is not None else 1,
        fact.position or 0,
        fact.kind.value,
        fact.value,
    )


def _first(
    text: str, normalised: str, kind: IdentifierKind, value: str, at: int | None
) -> tuple[int, int] | None:
    """Where `value` stands in `text` as its kind may write it: the occurrence its reader took
    (the one at `at` in the `normalised` text: as many come before it there as here), else
    the first."""
    spans = identifier_spans(text, kind, value)
    if not spans:
        return None
    if at is None:
        return spans[0].start, spans[0].end
    pattern = type_of(kind).written(value)
    before = sum(
        1 for found in re.finditer(pattern, normalised, re.IGNORECASE) if found.start() < at
    )
    span = spans[min(before, len(spans) - 1)]
    return span.start, span.end


def merged(kept: Iterable[DocumentFact], found: Iterable[DocumentFact]) -> list[DocumentFact]:
    """The facts of a document after a source found `found` again: what a person decided
    (`kept` with a state by a person) stays, and a fact found of the same kind and value does
    not replace it; the other facts found before go."""
    decided = {fact.key: fact for fact in kept if fact.state.by_person}
    new = [fact for fact in found if fact.key not in decided]
    return sorted([*decided.values(), *new], key=reading_order)


def check_found(facts: Iterable[DocumentFact]) -> None:
    """Facts as sources found them, each kind and value once; ValidationError otherwise."""
    keys = [fact.key for fact in facts if fact.state is FactState.FOUND]
    if len(keys) != len(list(facts)) or len(set(keys)) != len(keys):
        raise ValidationError("found facts are found, each kind and value once")


def check_decided(fact: DocumentFact) -> None:
    """A fact a person decided; ValidationError for one as found."""
    if not fact.state.by_person:
        raise ValidationError("a decision is a person's: added, corrected or rejected")
