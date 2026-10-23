"""How well the OCR read a page: the words it recognised there and how many of them it was
unsure of. A page with a text layer of its own is not read again and has no reading.

A value on a poorly read page is only suggested (the fields node, the judge's document date):
the engine is often sure of a misread word, but where many words are unsure, the page is a
broken scan, and a number read there may be anything. Only content counts (`is_noise`): the
dot leaders after labels, table rules, stray marks and the small print of a letterhead are read
unsure on any scan and say nothing about whether a value was read right.

Tesseract also tells how sure it was of each word (`ReadWord`): a value whose own words were
read unsure is only suggested on a well read page too (`value_words`). Where the value's words
are found, not the whole page but the content around them decides whether its place was read
poorly (`surroundings`): a well read header above a badly read table keeps a date there. The
words of a document are kept beside its archive (`reading_to_json`); the vision language model
gives no confidences, so its readings have no words and no content counts.
"""

import math
import re
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, Self

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.evidence import DocumentText
from lekto.core.domain.json_value import (
    JsonObject,
    JsonValue,
    as_bool,
    as_int,
    as_list,
    as_number,
    as_object,
    as_text,
)
from lekto.core.domain.locations import Box, Location

# Fewer words say too little about a page: a blank back side, a page number.
MIN_WORDS = 10

UNSURE_BELOW = 60
"""Tesseract's confidence (0 to 100) below which a word counts as unsure."""

SMALL_LINE = 0.6
"""A line whose height (hOCR `x_size`) is under this share of the page's typical one is small
print, not content. Tesseract measures the lines of one font up to a fifth apart (a line of
digits or capitals has no descenders), so the cut lies well below: it takes a letterhead's or a
sender line's 6 pt beside 11 pt body text, and keeps 8 pt footnotes and every table row."""

FLAT_WORD = 0.35
"""A word whose box is under this share of its line's height is no word: Tesseract reads the
dots of a leader, a dash or a table rule as letters (`«oso:`, `see`, `cence`, `EEE`), and their
box stays as low as the dots (0.1 to 0.2 of the line on a test scan), while a word of small
letters only (`nur`, `an`) still has the x-height (0.55 and more)."""

SURROUNDING = 20
"""The content words nearest to a value that tell whether its place was read poorly."""

SURROUNDING_POOR = 3
"""Unsure words among the `SURROUNDING` that make a value's place poorly read (Tobi,
19.10.2026: 15 %, not the page's 8 %): among 20 words one stray reading is already 5 %, and two
(a label beside its leader, a speck in a table) turned a date read sure yellow; the value's own
words must be read sure in any case."""

LEADER_GAP = 1.0
"""How close, in heights of its line, a word stands to a leader beside it on the line to be
tainted by it (`content_words`)."""

CHARACTER = 0.5
"""How wide a character is for the height of its line (hOCR `x_size`, about the font size), as
in the proportional fonts of letters: it turns a horizontal gap measured in characters into
line heights (`gap`)."""

READING_VERSION = 1
"""The version of `reading.json`, the words of a document's archive."""

_LEADER = re.compile(r"[.\u00b7\u2026_\-\u2013\u2014]{3,}")  # dots, dashes, underscores

NO_TEXT_REASON = "no text recognised: the pages are blank or hold only pictures"
"""Why the parse node fails a document without any text."""


@dataclass(frozen=True)
class ReadWord:
    """A word as Tesseract read it: its `text`, how sure it was (`confidence`, 0 to 100), its
    `box` on the page as it is shown (as the places of quotes; None where the reading gave no
    page size), and the height of its line (`size`, hOCR `x_size`, a share of the page's
    height; None where not given)."""

    text: str
    confidence: int
    box: Box | None = None
    size: float | None = None

    @property
    def unsure(self) -> bool:
        return self.confidence < UNSURE_BELOW

    def to_json(self) -> JsonObject:
        """As `reading.json` keeps it, the box as `[x, y, width, height]`."""
        output: JsonObject = {"text": self.text, "confidence": self.confidence}
        if self.box is not None:
            output["box"] = [self.box.x, self.box.y, self.box.width, self.box.height]
        if self.size is not None:
            output["size"] = self.size
        return output

    @classmethod
    def from_json(cls, data: JsonValue) -> Self:
        """What `to_json` wrote. ValidationError if it is not a word."""
        if not isinstance(data, dict):
            raise ValidationError(f"invalid word {data!r:.100}")
        text, confidence = as_text(data.get("text")), as_int(data.get("confidence"))
        if text is None or confidence is None:
            raise ValidationError(f"invalid word {data!r:.100}")
        box = None
        if (raw := data.get("box")) is not None:
            numbers = [number for value in as_list(raw) if (number := as_number(value)) is not None]
            if len(numbers) != 4:
                raise ValidationError(f"invalid box of a word {raw!r:.100}")
            box = Box(*numbers)
        return cls(text, confidence, box, as_number(data.get("size")))


def is_noise(word: ReadWord, typical_size: float | None = None) -> bool:
    """Whether a word is noise, neither content nor a sign of a broken scan: fewer than half
    of its characters letters or digits (table rules, marks); a dot, dash or underscore leader
    (`Datum..........`), also one read as letters (a box lower than `FLAT_WORD` of its line);
    one or two characters without a digit (stray marks read as `gy`, `TI`, `j`); or in a line
    under `SMALL_LINE` of the page's `typical_size` (a letterhead)."""
    text = word.text.strip()
    letters = sum(char.isalnum() for char in text)
    if not text or 2 * letters < len(text) or _LEADER.search(text):
        return True
    if len(text) <= 2 and not any(char.isdigit() for char in text):
        return True
    if word.box is not None and word.size and word.box.height < FLAT_WORD * word.size:
        return True
    return (
        typical_size is not None and word.size is not None and word.size < SMALL_LINE * typical_size
    )


def content_words(words: Sequence[ReadWord]) -> list[ReadWord]:
    """The words of a page (in reading order) that are content (`is_noise`), without those
    standing right beside a leader on their line (`beside_leaders`). The typical line size is
    the median over the words, so that the body text sets it, not a few headings or marks."""
    sizes = [word.size for word in words if word.size is not None and not is_noise(word)]
    typical = statistics.median(sizes) if sizes else None
    beside = beside_leaders(words)
    return [
        word
        for index, word in enumerate(words)
        if index not in beside and not is_noise(word, typical)
    ]


def beside_leaders(words: Sequence[ReadWord]) -> set[int]:
    """The indexes of the words (in reading order) that stand right before or after a leader on
    their line, within `LEADER_GAP` of a line's height (Tobi, 19.10.2026): Tesseract reads a
    label beside its dots unsure (`Krankenkasse` 38 % before `................`) though the
    label is clean, so such a word is neither content nor unsure. A leader is a word that is
    one (`Datum...........`, `—............`) or was read from one (a flat box, `FLAT_WORD`)."""
    beside: set[int] = set()
    for index, word in enumerate(words):
        if not _is_leader(word):
            continue
        for other in (index - 1, index + 1):
            if 0 <= other < len(words) and _side_by_side(word, words[other]):
                beside.add(other)
    return beside


def _is_leader(word: ReadWord) -> bool:
    if _LEADER.search(word.text.strip()):
        return True
    return (
        word.box is not None and word.size is not None and word.box.height < FLAT_WORD * word.size
    )


def _side_by_side(first: ReadWord, second: ReadWord) -> bool:
    """Whether two words stand on one line next to each other, within `LEADER_GAP`."""
    a, b = first.box, second.box
    if a is None or b is None:
        return False
    line = max(first.size or a.height, second.size or b.height)
    middle_a, middle_b = a.y + a.height / 2, b.y + b.height / 2
    gap = max(b.x - (a.x + a.width), a.x - (b.x + b.width), 0.0)
    return abs(middle_a - middle_b) <= line / 2 and gap <= LEADER_GAP * line


@dataclass(frozen=True)
class PageReading:
    """`page` from 1; `unsure` of its `words` the engine was unsure of; of them, the words that
    are content (`content`) and the unsure ones among them (`content_unsure`). The content
    counts are None for a page read before they were counted, and for one the vision language
    model read (it gives no confidences)."""

    page: int
    words: int
    unsure: int
    content: int | None = None
    content_unsure: int | None = None

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValidationError("pages are numbered from 1")
        if not 0 <= self.unsure <= self.words:
            raise ValidationError("the unsure words must be some of the words")
        if self.content is None or self.content_unsure is None:
            if (self.content, self.content_unsure) != (None, None):
                raise ValidationError("the content words come with the unsure ones among them")
            return
        if not 0 <= self.content <= self.words:
            raise ValidationError("the content words must be some of the words")
        if not 0 <= self.content_unsure <= min(self.content, self.unsure):
            raise ValidationError("the unsure content words must be content and unsure")

    @classmethod
    def of(cls, page: int, words: Sequence[ReadWord]) -> Self:
        """The reading of page `page` with these words (each with some text)."""
        content = content_words(words)
        return cls(
            page=page,
            words=len(words),
            unsure=sum(word.unsure for word in words),
            content=len(content),
            content_unsure=sum(word.unsure for word in content),
        )

    @property
    def counted(self) -> tuple[int, int]:
        """The words that count and the unsure ones among them: the content where it was
        counted, otherwise all."""
        if self.content is None or self.content_unsure is None:
            return self.words, self.unsure
        return self.content, self.content_unsure

    @property
    def share(self) -> float:
        """The share of unsure words that decides whether the page is poorly read."""
        words, unsure = self.counted
        return unsure / words if words else 0.0

    def poor(self, threshold: float) -> bool:
        """Whether the page counts as poorly read: at least `threshold` of its content words
        unsure (`LEKTO_POOR_READING_THRESHOLD`), with enough of them to tell; of all its words
        where content was not counted (read before, or by the vision language model)."""
        return self.counted[0] >= MIN_WORDS and self.share >= threshold

    def describe(self) -> str:
        """Why the page counts as poorly read, for a check's reason."""
        words = "words" if self.content is None else "content words"
        return f"page {self.page} was poorly read ({self.share:.0%} of its {words} unsure)"

    def to_json(self) -> JsonObject:
        output: JsonObject = {"page": self.page, "words": self.words, "unsure": self.unsure}
        if self.content is not None:
            output["content"] = self.content
            output["content_unsure"] = self.content_unsure
        return output


def readings_to_json(readings: Sequence[PageReading]) -> list[JsonValue]:
    return [reading.to_json() for reading in readings]


def readings_from_json(data: object) -> tuple[PageReading, ...]:
    """The readings as the OCR node wrote them into its log entry; none for an entry without
    (written before readings, or the engine read no page). An entry written before content was
    counted has no content counts."""
    if not isinstance(data, list):
        return ()
    readings: list[PageReading] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        page, words, unsure, content, content_unsure = (
            as_int(item.get(key))
            for key in ("page", "words", "unsure", "content", "content_unsure")
        )
        if page is not None and words is not None and unsure is not None:
            try:
                readings.append(PageReading(page, words, unsure, content, content_unsure))
            except ValidationError:
                continue
    return tuple(readings)


@dataclass(frozen=True)
class PageWords:
    """The words Tesseract read on page `page` (from 1), in its reading order."""

    page: int
    words: tuple[ReadWord, ...]

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValidationError("pages are numbered from 1")


def reading_to_json(pages: Sequence[PageWords]) -> JsonObject:
    """The content of `reading.json`: the words of the pages Tesseract read, those with a box
    (the others cannot be found by a quote)."""
    return {
        "version": READING_VERSION,
        "pages": [
            {"page": page.page, "words": [w.to_json() for w in page.words if w.box is not None]}
            for page in pages
        ],
    }


def reading_from_json(data: JsonValue) -> dict[int, tuple[ReadWord, ...]] | None:
    """The words of a stored `reading.json` by page; None if it is of another version.
    ValidationError if it is not one."""
    if not isinstance(data, dict):
        raise ValidationError("invalid reading: not an object")
    if data.get("version") != READING_VERSION:
        return None
    if not isinstance(data.get("pages"), list):
        raise ValidationError("invalid reading: no list of pages")
    found: dict[int, tuple[ReadWord, ...]] = {}
    for item in as_list(data.get("pages")):
        page = as_int(item.get("page")) if isinstance(item, dict) else None
        if not isinstance(item, dict) or page is None or page < 1:
            raise ValidationError(f"invalid page of a reading {item!r:.100}")
        if not isinstance(words := item.get("words"), list):
            raise ValidationError(f"invalid page of a reading {item!r:.100}")
        found[page] = tuple(ReadWord.from_json(word) for word in words)
    return found


class Placed(Protocol):
    """A word on a page: what it reads and its box (None where not known). Tesseract's words
    (`ReadWord`) and those of the parsed text (`labels.LaidWord`) are placed alike."""

    @property
    def text(self) -> str: ...

    @property
    def box(self) -> Box | None: ...


def words_at[W: Placed](location: Location, words: Sequence[W]) -> list[W]:
    """The words that stand in one of the location's boxes, in reading order: those whose
    middle lies in a box, given half its height up and down (the text layer's boxes follow its
    font and differ from Tesseract's)."""
    found = []
    for word in words:
        if word.box is None:
            continue
        middle_x = word.box.x + word.box.width / 2
        middle_y = word.box.y + word.box.height / 2
        if any(
            area.x <= middle_x <= area.x + area.width
            and area.y - area.height / 2 <= middle_y <= area.y + area.height * 1.5
            for area in location.boxes
        ):
            found.append(word)
    return found


def value_words[W: Placed](
    words: Sequence[W], shows: Callable[[DocumentText], bool]
) -> tuple[W, ...] | None:
    """The words that make up a value among `words` (those of its quote, in reading order):
    the shortest runs of them that show it (`shows`, as the quote check reads the value); where
    it stands more than once in as many words, all of them (a longer form beside a shorter one,
    `24. Juni 2022` beside `24.06.2022`, is not looked at). None if the words do not show it
    (it is not written as such, or they are not the words of the quote)."""

    def shown(run: Sequence[W]) -> bool:
        return shows(DocumentText(" ".join(word.text for word in run)))

    if not words or not shown(words):
        return None
    for length in range(1, len(words)):
        runs = [words[start : start + length] for start in range(len(words) - length + 1)]
        found = [index for index, run in enumerate(runs) if shown(run)]
        if found:
            indexes = sorted({index + offset for index in found for offset in range(length)})
            return tuple(words[index] for index in indexes)
    return tuple(words)


VALUE_RUN = 4
"""The most words a value is looked for in across the page (`value_on_pages`): a date written
out (`24. Juni 2022`) or an amount split by the reading (`1.180, 41`)."""


def value_on_pages[W: Placed](
    pages: Mapping[int, Sequence[W]], shows: Callable[[DocumentText], bool]
) -> tuple[int, tuple[W, ...]] | None:
    """Where a value stands among the words read on the pages, for one whose quote was not
    found on them: the shortest runs of words in reading order that show it (`shows`, as
    `value_words`), up to `VALUE_RUN` words; its page and words if it stands at exactly one
    place, else None (nowhere, or more than once: which one the quote meant is not known)."""
    for length in range(1, VALUE_RUN + 1):
        found = [
            (page, tuple(words[start : start + length]))
            for page, words in sorted(pages.items())
            for start in range(len(words) - length + 1)
            if shows(DocumentText(" ".join(word.text for word in words[start : start + length])))
        ]
        if found:
            return found[0] if len(found) == 1 else None
    return None


def gap(first: Box, second: Box, *, line: float, character: float) -> float:
    """How far apart two boxes on a page are, in line heights: Euclidean between their nearest
    edges, 0 where they overlap. The vertical gap is measured in lines (`line`, a line's height
    as a share of the page's height), so that a row is a row whatever the leading; the
    horizontal one in characters (`character`, a character's width as a share of the page's
    width), at `CHARACTER` of a line each. Boxes are shares of a page whose shape the reading
    does not keep; the line and the character are measured on the page itself, so a receipt or
    a landscape page is measured as truly as a letter."""
    across = max(0.0, second.x - (first.x + first.width), first.x - (second.x + second.width))
    down = max(0.0, second.y - (first.y + first.height), first.y - (second.y + second.height))
    return math.hypot(across / character * CHARACTER, down / line)


@dataclass(frozen=True)
class Surroundings:
    """The content words nearest to a value's words on its page (`surroundings`)."""

    words: tuple[ReadWord, ...]

    @property
    def unsure(self) -> int:
        return sum(word.unsure for word in self.words)

    def poor(self) -> bool:
        """Whether the value stands in a poorly read place: at least `SURROUNDING_POOR` of the
        words around it unsure."""
        return bool(self.words) and self.unsure >= SURROUNDING_POOR

    def describe(self) -> str:
        """Why the value's place counts as poorly read, for a check's reason."""
        return (
            f"the text around the value was poorly read ({self.unsure} of {len(self.words)}"
            " content words unsure)"
        )


def surroundings(
    words: Sequence[ReadWord], value: Sequence[ReadWord], count: int = SURROUNDING
) -> Surroundings | None:
    """The `count` content words of a page (`words`, `content_words`) nearest to the value's
    words (`value`, from `value_words`, which are among them), not counting those: by `gap` to
    the nearest of them, rounded to a millionth of a line so that equal gaps are equal however
    the boxes were rounded, a tie by reading order. The line is the median line height of the
    content (without sizes, of its boxes), the character the median width of one in its boxes.
    No layout is assumed: a table, a header or a form are words at a distance like any other.
    None where the page has fewer than `count` content words besides the value's (or none):
    the whole page decides then."""
    content = [(word, word.box) for word in content_words(words) if word.box is not None]
    places = [word.box for word in value if word.box is not None]
    own = set(value)
    others = [(word, box) for word, box in content if word not in own]
    if len(others) < max(count, 1) or not places:
        return None
    sizes = [word.size for word, _ in content if word.size is not None]
    line = statistics.median(sizes or [box.height for _, box in content])
    character = statistics.median(box.width / len(word.text.strip()) for word, box in content)
    if line <= 0 or character <= 0:  # boxes without extent: nothing to measure by
        return None
    distances = [
        (round(min(gap(box, place, line=line, character=character) for place in places), 6), i)
        for i, (_, box) in enumerate(others)
    ]
    return Surroundings(tuple(others[i][0] for _, i in sorted(distances)[:count]))


class VisionAdvice(StrEnum):
    """Why a person is advised to have the document read by the vision language model: the
    text recognition made it red or yellow."""

    NO_TEXT = "no_text"  # red: no text was recognised
    POOR_PAGE = "poor_page"  # yellow or red, with a poorly read page


@dataclass(frozen=True, kw_only=True)
class DocumentReading:
    """How the text of the document's archive was read (its latest OCR): by the vision
    language model or not, each recognised page, and the advice to read it with the model."""

    vision: bool
    pages: tuple[PageReading, ...]
    poor: tuple[int, ...]  # the pages that count as poorly read
    advice: VisionAdvice | None


def vision_advice(
    *,
    vision: bool,
    poor: Sequence[int],
    needs_person: bool,
    no_text: bool,
) -> VisionAdvice | None:
    """The advice for a document that waits for a person (`needs_person`: yellow or red, not
    being processed): its parse found no text, or a page was read poorly. None once the model
    has read it: reading again would cost and change nothing."""
    if vision or not needs_person:
        return None
    if no_text:
        return VisionAdvice.NO_TEXT
    if poor:
        return VisionAdvice.POOR_PAGE
    return None


@dataclass(frozen=True, kw_only=True)
class OcrOutput:
    """What the OCR node logs: the archive and its pages, whether it is PDF/A and its colours
    were converted to RGB for that (`rgb`), the engine's note, how each recognised page was read,
    whether another OCR's text layer was replaced, and a vision model's run (`vision`: model,
    endpoint, prompt, calls; `tokens` per call)."""

    archive: str
    pages: int
    pdfa: bool
    note: str | None = None
    readings: tuple[PageReading, ...] = ()
    read_again: bool = False
    vision: JsonObject | None = None
    tokens: tuple[JsonValue, ...] = ()
    rgb: bool = False

    def to_json(self) -> JsonObject:
        output: JsonObject = {"archive": self.archive, "pages": self.pages, "pdfa": self.pdfa}
        if self.note is not None:
            output["note"] = self.note
        if self.readings:
            output["readings"] = readings_to_json(self.readings)
        if self.read_again:
            output["read_again"] = True
        if self.rgb:
            output["rgb"] = True
        if self.vision is not None:
            output["vision"] = self.vision
            output["tokens"] = list(self.tokens)
        return output

    @classmethod
    def from_json(cls, data: JsonObject) -> Self:
        """What `to_json` wrote; what an entry lacks is empty."""
        return cls(
            archive=as_text(data.get("archive")) or "",
            pages=as_int(data.get("pages")) or 0,
            pdfa=as_bool(data.get("pdfa")) is True,
            note=as_text(data.get("note")),
            readings=readings_from_json(data.get("readings")),
            read_again=as_bool(data.get("read_again")) is True,
            vision=as_object(data.get("vision")),
            tokens=tuple(as_list(data.get("tokens"))),
            rgb=as_bool(data.get("rgb")) is True,
        )
