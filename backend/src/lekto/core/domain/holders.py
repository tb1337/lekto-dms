"""Whose an IBAN, a creditor ID or a VAT ID is where it stands (`.idea/umsetzungsplan.md`,
"Inhaber von IBANs und Gläubiger-IDs", "Inhaber von USt-IdNr. und E-Mail-Domains"): the fixed
rule on the text and the pages, German and English, that holds when the language model tells
nothing (it is asked for IBANs and creditor IDs only). Whose an e-mail domain is, its name
tells (`domain_holder`).

A number's places are read one by one, each from its line, the three lines above and where it
stands on its page. The first rule that applies tells (`_at`):

- glued to a word, it is no number of its own: unclear;
- a label on its line tells: "unser Konto", "bank details" the sender's; "Ihr Konto",
  "account holder" the recipient's;
- a known name beside it (before it on its line, or above it in its column) is its holder's: a
  person's is the recipient's, a contact's the sender's under that name, or another party's
  where it stands in a booking (a line with a date or an amount) or in a list of numbers;
- a person's name anywhere in its block (the account holder at the foot of a statement);
- an unknown name beside it counts only in a booking or in a list: another party's under that
  name;
- a label in the lines above: the recipient's, where money goes (the payee's: another
  party's), or the sender's;
- one of a list is another party's, one at the foot of a page the sender's.

The sender named is the document's contact only where the name is its name or an alias; the
rule does not know the contact, those who use the holder compare (`Holder`). A number's holder
is that of its places (`holders`): a recipient's at one place is theirs; places that differ
between sender and another party leave it unclear. A person's own number (their profile) is
theirs wherever it stands, and the name of a GiroCode that holds one is its holder's. A VAT ID
that stands alone in the document is the sender's where its places tell nothing.
"""

import re
from bisect import bisect_right
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache

from lekto.core.domain.document_facts import (
    HOLDER_KINDS,
    MODEL_HOLDER_KINDS,
    SURE_HOLDER_KINDS,
    DocumentFact,
    Holder,
    HolderKind,
    HolderSource,
)
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.evidence import contains, normalise
from lekto.core.domain.facts import identifier_spans
from lekto.core.domain.identifiers import (
    FREE_MAIL,
    IdentifierKind,
    Key,
    normalise_identifier,
    type_of,
)
from lekto.core.domain.names import match_key
from lekto.core.domain.reasons import Reason, ReasonCode, because

_DATE = r"\d{1,2}\.\d{1,2}\.\d{2,4}|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}"
_AMOUNT = r"[-+]?\d[\d.]*,\d{2}|[-+]?\d{1,3}(?:,\d{3})*\.\d{2}"
_CURRENCY = r"(?:€|EUR|£|GBP|\$|USD|CHF)"
# What ends a name in a column: a date or an amount after two spaces, or three spaces.
_NAME_END = re.compile(rf"\s{{2,}}(?:{_DATE})\b|\s{{2,}}(?:{_AMOUNT})|\s{{3,}}")
# A line of a booking: a date, or an amount with its currency.
_BOOKING = re.compile(rf"{_DATE}|(?:{_AMOUNT})\s*{_CURRENCY}|[€£$]\s*(?:{_AMOUNT})")
_BANK = re.compile(
    r"bank|\bbk\b|landesbk|sparkasse|raiffeisen|\bbic\b|swift|kreditinstitut|\beg\b|\bblz\b"
    r"|sort\s+code|routing",
    re.IGNORECASE,
)
_ADDRESS = re.compile(
    r"\b\d{5}\s+\w|str(\.|aße|asse)\s*\d|\bweg\s+\d|\bplatz\s+\d"
    r"|\b\d+\s+\w+\s+(street|road|avenue|lane|drive)\b|\b[a-z]{1,2}\d{1,2}\s+\d[a-z]{2}\b",
    re.IGNORECASE,
)
_KINDS_OF_BOOKING = re.compile(
    r"^\s*(lastschrift(en)?|gutschrift(en)?|belastung(en)?|überweisung(en)?|uberweisung(en)?"
    r"|dauerauftr\w*|zahlungseingang|zahlungsausgang|umsätze|buchung(en)?|miete|gehalt|lohn"
    r"|direct\s+debits?"
    r"|credits?|debits?|transfers?|standing\s+orders?|payments?|transactions?|rent|salary)\b",
    re.IGNORECASE,
)
_VAT = r"(ust|umsatzsteuer)[-.\s]*id\w*|vat\b"
_SENDER = re.compile(
    r"\b(unser(e|em)?\s+(konto|bankverbindung)|bankverbindung|zahlbar\s+an\s+uns|auf\s+unser"
    r"|our\s+(account|bank\s+details)|bank\s+details|pay(able)?\s+to\s+us|remit\s+to"
    rf"|unser(e|er)?\s+({_VAT})|our\s+({_VAT}))",
    re.IGNORECASE,
)
_RECIPIENT = re.compile(
    r"\b(ihre?[ms]?\s+(kontos?|iban|bankverbindung)|kontoinhaber|von\s+ihrem\s+konto"
    r"|your\s+(account|iban|bank\s+details)|account\s+holder|from\s+your\s+account"
    rf"|ihre?r?\s+({_VAT})|your\s+({_VAT}))",
    re.IGNORECASE,
)
_TARGET = re.compile(
    r"\b(überweisung|uberweisung|auszahlung|gutschrift\s+auf|empfänger|begünstigter"
    r"|zahlungsempfänger|auftraggeber|payee|beneficiary|pay\s+to|paid\s+to|transfer\s+to)\b",
    re.IGNORECASE,
)
# The label of the number just before it, left out of the name before it.
_LABEL = re.compile(
    r"(?i)(iban|gläubiger[-\s]*(id(entifikations(nummer)?)?|identifikationsnummer|nr\.?)"
    r"|creditor[-\s]*(id|identifier)|ci"
    r"|(ust|umsatzsteuer)[-.\s]*(id(\.|entifikations)?[-.\s]*(nr|nummer)?|identifikationsnummer)"
    r"|vat[-\s]*(id|no|number|reg(istration)?[-\s]*(no|number)?)?)\s*[:=.]?\s*$"
)
_WORD = re.compile(r"[a-z]{3,}")
_ANOTHER_NUMBER = re.compile(r"\b[A-Z]{2}\d{2}[ A-Z0-9]{12,}")
_ANOTHER_VAT = re.compile(r"\b[A-Z]{2} ?\d[\d ]{7,13}\b")
# A column: words apart by one or two spaces; columns apart by three spaces or a table's `|`.
_COLUMN = re.compile(r"[^\s|]+(?: {1,2}[^\s|]+)*")
_COLUMNS = re.compile(r"\s{3,}|\s*\|\s*")

LIST = 6
"""Numbers of a kind from which a document lists them (a statement's payees)."""

FOOT = 0.8
"""Where the foot of a page starts, from its top (a fraction of its height)."""

_ABOVE = 3  # lines above a number that are its block
_NAME_WORDS = 6  # words a name has at most


@dataclass(frozen=True)
class Party:
    """A contact as the rule for e-mail domains sees it: its name, all its names (with the
    aliases) and the domains a person gave it."""

    name: str
    names: tuple[str, ...]
    domains: frozenset[str] = frozenset()


class Parties:
    """Who a number may belong to: the persons (the users) by their names and their numbers,
    and the contacts by their names and aliases (`contacts`: each on its own, for the e-mail
    domains)."""

    def __init__(
        self,
        person_names: Iterable[str] = (),
        person_numbers: Collection[Key] = (),
        contact_names: Iterable[str] = (),
        contacts: Iterable[Party] = (),
    ) -> None:
        # A login name or a lone first name names no one: names of two words or more.
        self._persons = [words for words in map(_words, person_names) if len(words) >= 2]
        self._contacts = [words for words in map(_words, contact_names) if words]
        self.person_numbers = frozenset(person_numbers)
        self.contacts = tuple(contacts)

    def person(self, text: str) -> bool:
        """Whether `text` names one of the persons."""
        return _named(text, self._persons)

    def contact(self, text: str) -> bool:
        """Whether `text` names one of the contacts."""
        return _named(text, self._contacts)


@dataclass(frozen=True)
class Place:
    """Where a number stands: its `line`, the `column` it starts at there and how it is
    `written`, the lines `above` it (the nearest last), how far down its page it starts (None
    where the pages are not known), how many numbers of its kind the document shows, and
    whether it may be a party's of a booking or a list (`booked`: an IBAN or a creditor ID; a
    VAT ID stands in no booking)."""

    line: str
    column: int
    written: str
    above: tuple[str, ...] = ()
    top: float | None = None
    numbers: int = 1
    booked: bool = True


def holders(
    text: str,
    facts: Iterable[DocumentFact],
    parties: Parties,
    *,
    tops: Callable[[int, int], float | None] = lambda start, end: None,
    codes: Mapping[Key, str] | None = None,
) -> dict[Key, Holder]:
    """The holder of each of `facts` of `HOLDER_KINDS` the text shows, by the rule: from its
    places in `text` (`identifier_spans`), how far down its page each starts (`tops`) and the
    name of a code on the pages that holds it (`codes`: a GiroCode's payee). A person's own
    number is theirs wherever it stands."""
    shown = [fact for fact in facts if fact.kind in HOLDER_KINDS]
    numbers = {kind: sum(1 for fact in shown if fact.kind is kind) for kind in HOLDER_KINDS}
    lines = _Lines(text)
    found: dict[Key, Holder] = {}
    for fact in shown:
        if fact.kind is IdentifierKind.EMAIL_DOMAIN:
            found[fact.key] = domain_holder(fact.value, text, parties)
            continue
        coded = (codes or {}).get(fact.key)
        if fact.key in parties.person_numbers:
            found[fact.key] = Holder(HolderKind.RECIPIENT, HolderSource.RULE)
            continue
        if coded is not None:
            found[fact.key] = _named_holder(coded, parties)
            continue
        places = [
            lines.place(
                span.start,
                span.end,
                tops(span.start, span.end),
                numbers[fact.kind],
                booked=fact.kind is not IdentifierKind.VAT_ID,
            )
            for span in identifier_spans(text, fact.kind, fact.value)
        ]
        if places:
            held = _of_places([holder_at(place, parties) for place in places])
            if (
                held.kind is HolderKind.UNCLEAR
                and fact.kind is IdentifierKind.VAT_ID
                and numbers[fact.kind] == 1
            ):
                held = Holder(HolderKind.SENDER, HolderSource.RULE)  # the only one: the sender's
            found[fact.key] = held
    return found


def held_by(holder: Holder | None, names: Iterable[str]) -> HolderKind | None:
    """Whose a number is to the contact of `names` (its name and aliases; none: no contact): a
    sender that names someone else is a third party. None without a holder."""
    if holder is None:
        return None
    if (
        holder.kind is HolderKind.SENDER
        and holder.name
        and not _contact_parties(tuple(names)).contact(holder.name)
    ):
        return HolderKind.THIRD_PARTY
    return holder.kind


@lru_cache(maxsize=4096)
def _contact_parties(names: tuple[str, ...]) -> Parties:
    """A contact by its names, kept: `held_by` is asked about the same contact for each of
    its facts (training, the open identifiers, the evaluation)."""
    return Parties(contact_names=names)


def foreign(holder: Holder | None, names: Iterable[str]) -> bool:
    """Whether a number belongs to someone other than the contact of `names`: a person or a
    third party (`held_by`). A number without a holder (read before 0.8) is not."""
    return held_by(holder, names) in (HolderKind.RECIPIENT, HolderKind.THIRD_PARTY)


def unlearned(fact: DocumentFact, names: Iterable[str]) -> bool:
    """Whether training leaves `fact` out for the contact of `names`: someone else's
    (`foreign`), or of `SURE_HOLDER_KINDS` and not surely its (an e-mail domain whose name
    names no one: offered in the open list, not learned)."""
    if foreign(fact.holder, names):
        return True
    return (
        fact.kind in SURE_HOLDER_KINDS
        and fact.holder is not None
        and fact.holder.kind is HolderKind.UNCLEAR
    )


# --- e-mail domains: whose by the name --------------------------------------------------------

_ADDRESS_AT = re.compile(r"([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)")
_FILLERS = frozenset({"und", "der", "die", "das", "von", "fuer", "the", "and", "for"})


def domain_holder(domain: str, text: str, parties: Parties) -> Holder:
    """Whose an e-mail domain is, by its name rather than where it stands (Tobi, 28.10.2026):
    a free mail domain's holder is not to tell (unclear); one of a person (the domain of one of
    their addresses, or of an address in `text` whose part before the @ names them) is the
    recipient's; one a contact carries, or whose name a word of a contact's name stands in
    (`domain_owner`), the sender's under that contact's name (`held_by`: another contact's is
    a third party's); else unclear."""
    domain = domain.lower()
    if domain in FREE_MAIL:
        return Holder(HolderKind.UNCLEAR, HolderSource.RULE)
    personal = {
        value.rpartition("@")[2].lower()
        for kind, value in parties.person_numbers
        if kind is IdentifierKind.EMAIL_ADDRESS
    }
    if domain in personal:
        return Holder(HolderKind.RECIPIENT, HolderSource.RULE)
    for match in _ADDRESS_AT.finditer(text):
        if match.group(2).lower() == domain and parties.person(
            re.sub(r"[._+-]+", " ", match.group(1))
        ):
            return Holder(HolderKind.RECIPIENT, HolderSource.RULE)
    owner = domain_owner(domain, parties.contacts)
    if owner is not None:
        return Holder(HolderKind.SENDER, HolderSource.RULE, owner)
    return Holder(HolderKind.UNCLEAR, HolderSource.RULE)


def domain_owner(domain: str, contacts: Iterable[Party]) -> str | None:
    """The name of the contact an e-mail domain is: one a person gave it, else the one with the
    most letters of its names' words (three letters or more, without legal forms) in the
    domain's name before its top level (`stadtwerke-nordheim` of `stadtwerke-nordheim.de` for
    "Stadtwerke Nordheim GmbH"); None where none or two of them do as much."""
    domain = domain.lower()
    contacts = list(contacts)
    for party in contacts:
        if domain in party.domains:
            return party.name
    stem = re.sub(r"[^a-z0-9]", "", domain.removeprefix("www.").rpartition(".")[0])
    if not stem:
        return None
    scores: dict[str, int] = {}
    for party in contacts:
        words = {word for name in party.names for word in _WORD.findall(match_key(name))}
        score = sum(len(word) for word in words - _FILLERS if word in stem)
        if score:
            scores[party.name] = max(score, scores.get(party.name, 0))
    if not scores:
        return None
    best = max(scores.values())
    named = [name for name, score in scores.items() if score == best]
    return named[0] if len(named) == 1 else None


def holder_at(place: Place, parties: Parties) -> Holder:
    """The holder of the number at `place`, by the first rule that applies."""
    kind, name = _at(place, parties)
    return Holder(kind, HolderSource.RULE, name)


def _at(place: Place, parties: Parties) -> tuple[HolderKind, str | None]:
    line = place.line
    if line[place.column + len(place.written) :][:1].isalnum():
        return HolderKind.UNCLEAR, None  # glued to a word: no number of its own
    if _SENDER.search(line):
        return HolderKind.SENDER, None
    if _RECIPIENT.search(line):
        return HolderKind.RECIPIENT, None
    beside = [(name, booking and place.booked) for name, booking in _names_beside(place)]
    listed = place.numbers >= LIST and place.booked
    for name, booking in beside:
        if parties.person(name):
            return HolderKind.RECIPIENT, name
        if parties.contact(name):
            # A party of a booking or of a list is not the document's sender.
            kind = HolderKind.THIRD_PARTY if booking or listed else HolderKind.SENDER
            return kind, name
    # A person's name anywhere in its block, in any column: the account holder's name and
    # address beside the IBAN at the foot of a statement. (A contact's name there may be
    # another booking's or the bank's: only beside it.)
    for raw in (line, *place.above):
        if any(parties.person(part) for part in _COLUMNS.split(raw.strip())):
            return HolderKind.RECIPIENT, None
    for name, booking in beside:
        if booking or listed:  # a booking's party, or a party of a list
            return HolderKind.THIRD_PARTY, name or None
    # A label above whose line holds a number of its own is that number's (a VAT ID under
    # "Unsere USt-IdNr. DE…" is not the sender's for it).
    above = [raw for raw in place.above[:2] if place.booked or not _ANOTHER_VAT.search(raw)]
    context = " ".join([*reversed(above), line])
    if _RECIPIENT.search(context):
        return HolderKind.RECIPIENT, None
    if _TARGET.search(context):
        return HolderKind.THIRD_PARTY, None  # where money goes: not the sender
    if _SENDER.search(context):
        return HolderKind.SENDER, None
    if listed:
        return HolderKind.THIRD_PARTY, None
    if place.top is not None and place.top > FOOT:
        return HolderKind.SENDER, None
    return HolderKind.UNCLEAR, None


def _names_beside(place: Place) -> list[tuple[str, bool]]:
    """The names a number stands with, each with whether it stands in a booking: just before
    it on its line, then (unless its line is a booking) the lines above it in its column (up
    to three, not past another number), without a kind of booking before it, banks,
    addresses, labels and sentences. A kind of booking alone is an empty name (of a booking,
    where its line is one)."""
    head = place.line[: place.column]
    label = _LABEL.search(head)
    start = label.start() if label else place.column
    head = head[:start].strip()
    head = _COLUMNS.split(head)[-1] if head else ""
    candidates = [(head, place.line)]
    # Above a booking stand other bookings: their names are not this number's.
    if not _BOOKING.search(place.line):
        candidates += [(_segment(raw, start), raw) for raw in place.above]
    found = []
    for index, (text, raw) in enumerate(candidates):
        if index > 0 and _ANOTHER_NUMBER.search(text):
            break
        text = _NAME_END.split(text.strip())[0].strip(" :;,.«»„\"'")
        # "Lastschrift Stadtwerke …" in one column: the name after the kind of booking; the
        # kind alone still makes the number a booking's party, without a name.
        kind = _KINDS_OF_BOOKING.match(text)
        text = text[kind.end() :].strip(" :;,.-") if kind else text
        if kind and not _WORD.search(match_key(text)):
            found.append(("", _BOOKING.search(raw) is not None))
            continue
        if not _WORD.search(match_key(text)):
            continue
        if _BANK.search(text) or _ADDRESS.search(text):
            continue
        if _SENDER.search(text) or _RECIPIENT.search(text) or _TARGET.search(text):
            continue
        if len(text.split()) > _NAME_WORDS or re.search(r"[@:/]|www|\d{3}", text):
            continue
        found.append((text, _BOOKING.search(raw) is not None))
    return found


def _segment(line: str, column: int) -> str:
    """The part of `line` in the column that starts at `column` (parts apart by three
    spaces)."""
    for match in _COLUMN.finditer(line):
        if match.start() <= column + 6 and match.end() > column - 2:
            return match.group()
    return ""


def _named_holder(name: str, parties: Parties) -> Holder:
    kind = HolderKind.RECIPIENT if parties.person(name) else HolderKind.SENDER
    return Holder(kind, HolderSource.RULE, name)


def _of_places(found: Collection[Holder]) -> Holder:
    """A number's holder from those of its places: a recipient's at one is theirs; the sender
    and another party both leave it unclear; else the one the places tell."""
    for holder in found:
        if holder.kind is HolderKind.RECIPIENT:
            return holder
    told = [holder for holder in found if holder.kind is not HolderKind.UNCLEAR]
    if not told or len({holder.kind for holder in told}) > 1:
        return Holder(HolderKind.UNCLEAR, HolderSource.RULE)
    return next((holder for holder in told if holder.name), told[0])


class _Lines:
    """The lines of a text, to find the line a character stands on."""

    def __init__(self, text: str) -> None:
        self._lines = text.split("\n")
        self._starts = [0]
        for line in self._lines:
            self._starts.append(self._starts[-1] + len(line) + 1)

    def place(
        self, start: int, end: int, top: float | None, numbers: int, *, booked: bool = True
    ) -> Place:
        index = bisect_right(self._starts, start) - 1
        line = self._lines[index]
        column = start - self._starts[index]
        written = line[column : column + end - start]
        above = tuple(reversed(self._lines[max(0, index - _ABOVE) : index]))
        return Place(line, column, written, above, top, numbers, booked)


def _words(text: str) -> frozenset[str]:
    return frozenset(_WORD.findall(match_key(text)))


def _named(text: str, names: Iterable[frozenset[str]]) -> bool:
    """Whether every word of one of `names` stands in `text`, a letter off allowed in long
    words (OCR)."""
    mine = _words(text)
    if not mine:
        return False
    return any(all(any(_close(word, own) for own in mine) for word in name) for name in names)


def _close(a: str, b: str) -> bool:
    """The same word, or one letter off in words of five letters or more."""
    if a == b:
        return True
    if min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) <= 1
    short, long = sorted((a, b), key=len)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


# --- the holders the language model tells (`facts-2`) -----------------------------------------

NEAR = 400
"""Characters around a number within which the holder's name the model gives must stand."""


@dataclass(frozen=True, kw_only=True)
class ReadHolder:
    """A holder as the language model tells it, unchecked: the number's kind and value as
    listed, the holder, its name as written and the passage that shows it."""

    kind: str
    value: str
    holder: str
    name: str | None = None
    evidence: str | None = None


def checked_holder(
    text: str, read: ReadHolder, listed: Collection[Key]
) -> tuple[Key, Holder] | Reason:
    """The holder `read` tells, checked: of one of the `listed` numbers, a holder Lekto knows,
    a passage of the text that shows the number (`QUOTE_*`), and a name that stands in the text
    near one of the number's places (`NEAR`). Why not, otherwise."""
    number = next((kind for kind in MODEL_HOLDER_KINDS if kind.value == read.kind), None)
    if number is None:
        return because(ReasonCode.HOLDER_NOT_LISTED, value=read.value)
    try:
        key = (number, normalise_identifier(number, read.value))
    except ValidationError as error:
        return error.reason
    if key not in listed:
        return because(ReasonCode.HOLDER_NOT_LISTED, value=read.value)
    try:
        kind = HolderKind(read.holder)
    except ValueError:
        return because(ReasonCode.HOLDER_KIND_UNKNOWN, holder=read.holder)
    evidence = (read.evidence or "").strip()
    if not evidence:
        return because(ReasonCode.QUOTE_MISSING)
    if not contains(normalise(text), evidence):
        return because(ReasonCode.QUOTE_NOT_IN_TEXT)
    if re.search(type_of(key[0]).written(key[1]), evidence, re.IGNORECASE) is None:
        return because(ReasonCode.QUOTE_WITHOUT_VALUE)
    name = (read.name or "").strip() or None
    if name is not None:
        near = [
            text[max(0, span.start - NEAR) : span.end + NEAR]
            for span in identifier_spans(text, *key)
        ]
        if not any(contains(normalise(around), name) for around in near):
            return because(ReasonCode.HOLDER_NAME_NOT_NEAR, name=name)
    return key, Holder(kind, HolderSource.MODEL, name)


def merged_holder(rule: Holder | None, model: Holder | None) -> Holder | None:
    """The holder of a number from the rule's and the model's: the model's, unless one of them
    says the sender's and the other a person's or a third party's (then unclear), or the model
    cannot tell (then the rule's). A holder the model told before (kept with the facts) is no
    rule's."""
    if model is None:
        return rule
    if model.kind is HolderKind.UNCLEAR and rule is not None and rule.source is HolderSource.RULE:
        return rule
    if rule is None or rule.source is HolderSource.MODEL:
        return model
    told = {rule.kind, model.kind} - {HolderKind.UNCLEAR}
    if HolderKind.SENDER in told and len(told) > 1:
        return Holder(HolderKind.UNCLEAR, HolderSource.MODEL)
    return model
