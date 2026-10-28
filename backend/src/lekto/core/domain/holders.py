"""Whose an IBAN or a creditor ID is where it stands (`.idea/umsetzungsplan.md`, "Inhaber von
IBANs und Gläubiger-IDs"): the fixed rule on the text and the pages, German and English, that
holds when the language model tells nothing.

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
theirs wherever it stands, and the name of a GiroCode that holds one is its holder's.
"""

import re
from bisect import bisect_right
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass

from lekto.core.domain.document_facts import (
    HOLDER_KINDS,
    DocumentFact,
    Holder,
    HolderKind,
    HolderSource,
)
from lekto.core.domain.facts import identifier_spans
from lekto.core.domain.identifiers import Key
from lekto.core.domain.names import match_key

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
    r"^\s*(lastschriften?|gutschriften?|belastungen?|überweisung(en)?|uberweisung(en)?|dauerauftr"
    r"|zahlungseingang|zahlungsausgang|umsätze|buchungen?|direct\s+debits?|credits?|debits?"
    r"|transfers?|standing\s+orders?|payments?|transactions?)\b",
    re.IGNORECASE,
)
_SENDER = re.compile(
    r"\b(unser(e|em)?\s+(konto|bankverbindung)|bankverbindung|zahlbar\s+an\s+uns|auf\s+unser"
    r"|our\s+(account|bank\s+details)|bank\s+details|pay(able)?\s+to\s+us|remit\s+to)",
    re.IGNORECASE,
)
_RECIPIENT = re.compile(
    r"\b(ihre?[ms]?\s+(kontos?|iban|bankverbindung)|kontoinhaber|von\s+ihrem\s+konto"
    r"|your\s+(account|iban|bank\s+details)|account\s+holder|from\s+your\s+account)",
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
    r"|creditor[-\s]*(id|identifier)|ci)\s*[:=.]?\s*$"
)
_WORD = re.compile(r"[a-z]{3,}")
_ANOTHER_NUMBER = re.compile(r"\b[A-Z]{2}\d{2}[ A-Z0-9]{12,}")
_COLUMN = re.compile(r"\S+(?: {1,2}\S+)*")
_COLUMNS = re.compile(r"\s{3,}")

LIST = 6
"""Numbers of a kind from which a document lists them (a statement's payees)."""

FOOT = 0.8
"""Where the foot of a page starts, from its top (a fraction of its height)."""

_ABOVE = 3  # lines above a number that are its block
_NAME_WORDS = 6  # words a name has at most


class Parties:
    """Who a number may belong to: the persons (the users) by their names and their numbers,
    and the contacts by their names and aliases."""

    def __init__(
        self,
        person_names: Iterable[str] = (),
        person_numbers: Collection[Key] = (),
        contact_names: Iterable[str] = (),
    ) -> None:
        # A login name or a lone first name names no one: names of two words or more.
        self._persons = [words for words in map(_words, person_names) if len(words) >= 2]
        self._contacts = [words for words in map(_words, contact_names) if words]
        self.person_numbers = frozenset(person_numbers)

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
    where the pages are not known) and how many numbers of its kind the document shows."""

    line: str
    column: int
    written: str
    above: tuple[str, ...] = ()
    top: float | None = None
    numbers: int = 1


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
        coded = (codes or {}).get(fact.key)
        if fact.key in parties.person_numbers:
            found[fact.key] = Holder(HolderKind.RECIPIENT, HolderSource.RULE)
            continue
        if coded is not None:
            found[fact.key] = _named_holder(coded, parties)
            continue
        places = [
            lines.place(span.start, span.end, tops(span.start, span.end), numbers[fact.kind])
            for span in identifier_spans(text, fact.kind, fact.value)
        ]
        if places:
            found[fact.key] = _of_places([holder_at(place, parties) for place in places])
    return found


def held_by(holder: Holder | None, names: Iterable[str]) -> HolderKind | None:
    """Whose a number is to the contact of `names` (its name and aliases; none: no contact): a
    sender that names someone else is a third party. None without a holder."""
    if holder is None:
        return None
    if (
        holder.kind is HolderKind.SENDER
        and holder.name
        and not Parties(contact_names=names).contact(holder.name)
    ):
        return HolderKind.THIRD_PARTY
    return holder.kind


def foreign(holder: Holder | None, names: Iterable[str]) -> bool:
    """Whether a number belongs to someone other than the contact of `names`: a person or a
    third party (`held_by`). A number without a holder (read before 0.8) is not."""
    return held_by(holder, names) in (HolderKind.RECIPIENT, HolderKind.THIRD_PARTY)


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
    beside = _names_beside(place)
    listed = place.numbers >= LIST
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
            return HolderKind.THIRD_PARTY, name
    context = " ".join([*reversed(place.above[:2]), line])
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
    it on its line, then the lines above it in its column (up to three, not past another
    number), without kinds of booking, banks, addresses, labels and sentences."""
    head = place.line[: place.column]
    label = _LABEL.search(head)
    start = label.start() if label else place.column
    head = head[:start].strip()
    head = _COLUMNS.split(head)[-1] if head else ""
    candidates = [(head, place.line)] + [(_segment(raw, start), raw) for raw in place.above]
    found = []
    for index, (text, raw) in enumerate(candidates):
        if index > 0 and _ANOTHER_NUMBER.search(text):
            break
        text = _NAME_END.split(text.strip())[0].strip(" :;,.«»„\"'")
        if not _WORD.search(match_key(text)):
            continue
        if _KINDS_OF_BOOKING.search(text) or _BANK.search(text) or _ADDRESS.search(text):
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

    def place(self, start: int, end: int, top: float | None, numbers: int) -> Place:
        index = bisect_right(self._starts, start) - 1
        line = self._lines[index]
        column = start - self._starts[index]
        written = line[column : column + end - start]
        above = tuple(reversed(self._lines[max(0, index - _ABOVE) : index]))
        return Place(line, column, written, above, top, numbers)


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
