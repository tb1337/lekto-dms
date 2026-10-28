"""Facts as values of a document (`.idea/fakten.md`, issue #145): what a document shows that
marks something or points to something, numbers and references, each with its kind, its value
(normalised, as Lekto compares it), where it stands, where it comes from and its role.

A fact stands in the document and is not configured: it holds for every type, and Lekto
compares it across documents. The kinds are the identifiers' (`IdentifierKind`), fixed in the
code. Its role says what it is to the document (`FactRole`): the same number is the invoice's
own on the invoice and a reference on the reminder. The role follows the kind (`role_of`)
unless the language model read the fact (`with_read`).

An IBAN or a creditor ID also has its holder (`Holder`): whose account or whose collection it
is where it stands, the sender's, the recipient's or another party's. A bank statement names
the payees' IBANs beside its own.

A document keeps one fact per kind and value. The facts the sources find (patterns in the text,
codes on the pages, the language model) are replaced when either signal stores them again; a
person's decision (`FactState`) outlasts it.
"""

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.evidence import contains, normalise
from lekto.core.domain.facts import identifier_spans
from lekto.core.domain.identifiers import (
    TYPES,
    IdentifierKind,
    Key,
    normalise_identifier,
    of_person,
    type_of,
)
from lekto.core.domain.reasons import Reason, ReasonCode, because


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


MAX_WRITTEN = 200
"""Characters of a fact as written (and of its holder's name) that are kept."""


class HolderKind(StrEnum):
    """Whose a number is where it stands (`domain.holders`)."""

    SENDER = "sender"  # the document's sender: the contact it comes from, if the name fits
    RECIPIENT = "recipient"  # a person it is addressed to: their own account
    THIRD_PARTY = "third_party"  # another party: a payee in a booking, a party of a list
    UNCLEAR = "unclear"  # not to tell


class HolderSource(StrEnum):
    """Who told the holder."""

    RULE = "rule"  # the fixed rule on the text and the pages (`domain.holders`)
    MODEL = "model"  # the language model


@dataclass(frozen=True)
class Holder:
    """Whose a fact's number is: its `kind`, the `name` the document gives the holder, as
    written (None where it gives none), and who told it. A sender that names someone other
    than the document's contact (neither its name nor an alias) is a third party."""

    kind: HolderKind
    source: HolderSource
    name: str | None = None

    def __post_init__(self) -> None:
        if self.name is not None:
            object.__setattr__(self, "name", " ".join(self.name.split())[:MAX_WRITTEN] or None)


HOLDER_KINDS = frozenset(
    {
        IdentifierKind.IBAN,
        IdentifierKind.CREDITOR_ID,
        IdentifierKind.VAT_ID,
        IdentifierKind.EMAIL_DOMAIN,
    }
)
"""The kinds of facts that have a holder: a contact's as often as another's (a VAT ID or an
e-mail domain since 0.8: a parent company's, a payment service's, a portal's)."""

MODEL_HOLDER_KINDS = frozenset({IdentifierKind.IBAN, IdentifierKind.CREDITOR_ID})
"""The kinds whose holder the language model is asked for (`facts-2`); the others' the rule
tells alone (Tobi, 28.10.2026)."""

SURE_HOLDER_KINDS = frozenset({IdentifierKind.EMAIL_DOMAIN})
"""The kinds training learns for a contact only where the rule tells they are its: a domain
names its holder, and one that names no one is often another party's (Tobi, 28.10.2026)."""

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
    IdentifierKind.CREDITOR_ID: FactRole.CONTACT,
    IdentifierKind.COMMERCIAL_REGISTER: FactRole.CONTACT,
    IdentifierKind.TAX_NUMBER: FactRole.CONTACT,
    IdentifierKind.CONTRACT_NUMBER: FactRole.TARGET,
    IdentifierKind.POLICY_NUMBER: FactRole.TARGET,
    IdentifierKind.MEMBERSHIP_NUMBER: FactRole.TARGET,
    IdentifierKind.METER_NUMBER: FactRole.TARGET,
    IdentifierKind.LOAN_NUMBER: FactRole.TARGET,
    IdentifierKind.MANDATE_REFERENCE: FactRole.TARGET,
    IdentifierKind.LICENSE_PLATE: FactRole.TARGET,
    IdentifierKind.INVOICE_NUMBER: FactRole.OWN,
    IdentifierKind.CREDIT_NOTE_NUMBER: FactRole.OWN,
    IdentifierKind.ORDER_NUMBER: FactRole.OWN,
    IdentifierKind.FILE_REFERENCE: FactRole.THREAD,
    IdentifierKind.OUR_REFERENCE: FactRole.THREAD,
    IdentifierKind.CLAIM_NUMBER: FactRole.THREAD,
    IdentifierKind.TICKET_NUMBER: FactRole.THREAD,
    IdentifierKind.YOUR_REFERENCE: FactRole.REFERS,
    IdentifierKind.LETTER_DATE: FactRole.REFERS,
    IdentifierKind.CHILD_BENEFIT_NUMBER: FactRole.PERSON,
}
"""The role a fact of each kind has until a source tells (a test holds that no kind is
missing)."""

NUMBER_KINDS = frozenset(
    kind for kind in IdentifierKind if not (TYPES[kind].for_contacts or TYPES[kind].for_persons)
)
"""The kinds of the numbers a document has of its own, of a strand or of another document it
refers to: no contact's or person's identifiers (invoice number, file reference)."""


def role_of(kind: IdentifierKind) -> FactRole:
    return ROLES[kind]


def person_only(kind: IdentifierKind) -> bool:
    """A kind of a person's and no contact's (the IBAN is both): only admins and that person
    see such a fact, only admins decide or find documents by it."""
    return TYPES[kind].for_persons and not TYPES[kind].for_contacts


@dataclass(frozen=True, kw_only=True)
class DocumentFact:
    """A fact of a document. `value`: normalised, as Lekto compares it (`normalise_identifier`);
    `written`: as the text writes it where it stands first (a person's value the text does not
    show: as they wrote it; None where only a code holds it);
    `position`: the first character there, which orders the facts as the text reads (None:
    only in a code); `holder`: whose it is (`HOLDER_KINDS` only; None while none told)."""

    kind: IdentifierKind
    value: str
    role: FactRole
    origins: frozenset[FactOrigin]
    written: str | None = None
    position: int | None = None
    state: FactState = FactState.FOUND
    holder: Holder | None = None

    def __post_init__(self) -> None:
        if not self.value:
            raise ValidationError("a fact needs a value")
        if not self.origins:
            raise ValidationError("a fact comes from somewhere")
        if self.position is not None and self.position < 0:
            raise ValidationError("a fact's position is a character of the text")
        if self.holder is not None and self.kind not in HOLDER_KINDS:
            raise ValidationError("only an IBAN or a creditor ID has a holder")
        if self.written is not None:
            object.__setattr__(self, "written", self.written[:MAX_WRITTEN])

    @property
    def key(self) -> Key:
        return self.kind, self.value

    @property
    def shown(self) -> str:
        """As the text writes it, on one line: a soft hyphen gone, line breaks and other space
        one blank (`RE-2026/⏎0042` → `RE-2026/ 0042`); the value where only a code holds it."""
        return " ".join((self.written or self.value).replace("\u00ad", "").split()) or self.value


def found_facts(
    text: str,
    in_text: Iterable[Key],
    in_codes: Iterable[Key] = (),
    places: Mapping[Key, int] | None = None,
    referred: Collection[Key] = (),
) -> tuple[DocumentFact, ...]:
    """The facts a document shows: the identifiers in its text (`identifiers_in`) and in the
    codes on its pages (`code_identifiers`), each once, as the text reads (those only in a code
    last), with the role of its kind; a document's own number the text shows only as another's
    (`referred_in`: "Ihre Rechnung Nr. 4711") refers to that document ("Ihre Vertragsnummer" is
    still the contract's). Where one stands first is where its
    reader took it (`places`: in the normalised text, `places_in`), else where its value stands
    first."""
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
                role=_role(kind, (kind, value) in referred),
                origins=frozenset(origins),
                written=None if where is None else text[where[0] : where[1]],
                position=None if where is None else where[0],
            )
        )
    return tuple(sorted(facts, key=reading_order))


def _role(kind: IdentifierKind, referred: bool) -> FactRole:
    role = role_of(kind)
    return FactRole.REFERS if referred and role is FactRole.OWN else role


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


# --- facts a reader gives: the language model ------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ReadFact:
    """A fact as a reader that is no pattern gives it (the language model), unchecked: its kind
    and role as named, the value as written, the passage that shows it and its label."""

    kind: str
    value: str
    role: str
    evidence: str | None = None
    label: str | None = None


def checked_read(
    text: str,
    read: ReadFact,
    *,
    kinds: Collection[IdentifierKind],
    roles: Collection[FactRole],
    personal: Collection[Key] = (),
) -> DocumentFact | Reason:
    """The fact `read` gives, checked as a field's value is: one of the `kinds` in one of the
    `roles` the reader was asked for, a value of the kind, standing in the text, and a passage
    of the text that shows it (`QUOTE_*`); for the day of a letter, the passage names the letter
    ("Ihr Schreiben vom"). A value that is one of a person's (`personal`: their numbers in the
    text and in the users' profiles, `of_person`), under whatever kind, is none. Its role as
    given. Why not, otherwise."""
    try:
        kind = IdentifierKind(read.kind)
        role = FactRole(read.role)
    except ValueError:
        return because(ReasonCode.FACT_KIND_UNKNOWN, kind=read.kind)
    if kind not in kinds or role not in roles:
        return because(ReasonCode.FACT_NOT_ASKED, kind=read.kind, role=read.role)
    try:
        value = normalise_identifier(kind, read.value)
    except ValidationError as error:
        return error.reason
    if of_person((kind, value), personal) or any(
        theirs[1] == value for theirs in personal if TYPES[theirs[0]].for_persons
    ):
        return because(ReasonCode.FACT_OF_A_PERSON)
    where = _first(text, "", kind, value, None)
    if where is None:
        return because(ReasonCode.FACT_NOT_IN_TEXT, value=read.value)
    evidence = (read.evidence or "").strip()
    if not evidence:
        return because(ReasonCode.QUOTE_MISSING)
    if not contains(normalise(text), evidence):
        return because(ReasonCode.QUOTE_NOT_IN_TEXT)
    if re.search(type_of(kind).written(value), evidence, re.IGNORECASE) is None:
        return because(ReasonCode.QUOTE_WITHOUT_VALUE)
    if kind is IdentifierKind.LETTER_DATE and not any(type_of(kind).find(normalise(evidence))):
        return because(ReasonCode.QUOTE_WITHOUT_VALUE)
    return DocumentFact(
        kind=kind,
        value=value,
        role=role,
        origins=frozenset({FactOrigin.MODEL}),
        written=text[where[0] : where[1]],
        position=where[0],
    )


def with_read(found: Iterable[DocumentFact], read: Iterable[DocumentFact]) -> list[DocumentFact]:
    """The facts the patterns and codes found, with what a reader gave (checked): a fact of the
    same kind and value is one fact with both origins, in the role the reader gave (`fakten.md`,
    decision 3: the language model decides the role); a fact only the reader gave comes in."""
    facts = {fact.key: fact for fact in found}
    for fact in read:
        known = facts.get(fact.key)
        facts[fact.key] = (
            fact
            if known is None
            else replace(known, role=fact.role, origins=known.origins | fact.origins)
        )
    return sorted(facts.values(), key=reading_order)


# --- a person's decisions (PR 6) --------------------------------------------------------------


def person_fact(
    text: str, kind: IdentifierKind, raw: str, role: FactRole, state: FactState
) -> DocumentFact:
    """The fact a person gives: of `kind`, the value `raw` as they wrote it (ValidationError,
    with the kind's reason, if it is none of the kind), in `role`; where it stands in `text`,
    if it does, else written as they wrote it (a template gives `R-4711`, not `R4711`)."""
    value = normalise_identifier(kind, raw)
    where = _first(text, "", kind, value, None)
    return DocumentFact(
        kind=kind,
        value=value,
        role=role,
        origins=frozenset({FactOrigin.PERSON}),
        written=raw.strip() if where is None else text[where[0] : where[1]],
        position=None if where is None else where[0],
        state=state,
    )


def added(given: DocumentFact, known: DocumentFact | None) -> DocumentFact:
    """A person adds `given` (`person_fact`); one of its kind and value a source found (or a
    person rejected) is that fact, in the role given, added."""
    if known is None:
        return replace(given, state=FactState.ADDED)
    return replace(
        known,
        role=given.role,
        origins=known.origins | {FactOrigin.PERSON},
        state=FactState.ADDED,
    )


def corrected(
    fact: DocumentFact, *, role: FactRole | None = None, new: DocumentFact | None = None
) -> list[DocumentFact]:
    """A person corrects `fact`: another role, the fact in it; another value (`new`, as
    `person_fact` gives it, in its role or the fact's), the fact rejected and the new one
    corrected, so a run that finds the old value again does not bring it back. Nothing for no
    change."""
    if new is not None and new.key != fact.key:
        return [
            rejected(fact),
            replace(new, role=role or fact.role, state=FactState.CORRECTED),
        ]
    if role is None or role is fact.role:
        return []
    return [
        replace(
            fact, role=role, origins=fact.origins | {FactOrigin.PERSON}, state=FactState.CORRECTED
        )
    ]


def rejected(fact: DocumentFact) -> DocumentFact:
    """A person rejects `fact`: it is no fact of the document (a person decided it)."""
    return replace(fact, origins=fact.origins | {FactOrigin.PERSON}, state=FactState.REJECTED)


def withdrawn(fact: DocumentFact) -> DocumentFact | None:
    """A person's decision about `fact` no longer stands: a fact some source found is as found
    again (without the person's origin), one only a person gave goes (None)."""
    sources = fact.origins - {FactOrigin.PERSON}
    if not sources:
        return None
    return replace(fact, origins=sources, state=FactState.FOUND)


# --- finding documents by their facts (PR 7) --------------------------------------------------


@dataclass(frozen=True)
class FactCriterion:
    """Documents with a fact (none a person rejected) of `kind`, with `value` (normalised, as
    `normalise_identifier` gives it) and in `role`; what is None is any. A value needs its kind,
    and something is given."""

    kind: IdentifierKind | None = None
    value: str | None = None
    role: FactRole | None = None

    def __post_init__(self) -> None:
        if self.kind is None and self.value is None and self.role is None:
            raise ValidationError(because(ReasonCode.FACT_CRITERION_EMPTY))
        if self.value is not None and self.kind is None:
            raise ValidationError(because(ReasonCode.FACT_CRITERION_EMPTY))

    @classmethod
    def written(
        cls, kind: IdentifierKind | None, value: str | None, role: FactRole | None
    ) -> "FactCriterion":
        """A criterion with the value as a person writes it (ValidationError, with the kind's
        reason, if it is none of the kind)."""
        normalised = None
        if value is not None and value.strip():
            if kind is None:
                raise ValidationError(because(ReasonCode.FACT_CRITERION_EMPTY))
            normalised = normalise_identifier(kind, value)
        return cls(kind, normalised, role)

    @property
    def token(self) -> str:
        """The token of the criterion among a document's `fact_tokens`."""
        return _token(self.kind, self.value, self.role)


def _token(kind: IdentifierKind | None, value: str | None, role: FactRole | None) -> str:
    return "|".join(
        (
            "*" if kind is None else kind.value,
            "*" if value is None else value,
            "*" if role is None else role.value,
        )
    )


def fact_tokens(facts: Iterable[DocumentFact]) -> frozenset[str]:
    """What a filter by facts looks for in a document (`FactCriterion.token`): each fact not
    rejected by its kind, value and role, also without the value, the role or both, and by its
    role alone."""
    tokens: set[str] = set()
    for fact in facts:
        if fact.state is FactState.REJECTED:
            continue
        kind, value, role = fact.kind, fact.value, fact.role
        tokens |= {
            _token(kind, value, role),
            _token(kind, value, None),
            _token(kind, None, role),
            _token(kind, None, None),
            _token(None, None, role),
        }
    return frozenset(tokens)
