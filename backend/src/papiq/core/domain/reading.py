"""How well the OCR read a page: the words it recognised there and how many of them it was
unsure of. A page with a text layer of its own is not read again and has no reading.

A value on a poorly read page is only suggested (the fields node, the judge's document date):
the engine is often sure of a misread word, but where many words are unsure, the page is a
broken scan, and a number read there may be anything. Only content counts (`is_noise`): the
dot leaders after labels, table rules, stray marks and the small print of a letterhead are read
unsure on any scan and say nothing about whether a value was read right.

Tesseract also tells how sure it was of each word (`ReadWord`). The words of a document are
kept beside its archive (`reading_to_json`); the vision language model gives no confidences,
so its readings have no words and no content counts.
"""

import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.json_value import (
    JsonObject,
    JsonValue,
    as_bool,
    as_int,
    as_list,
    as_number,
    as_object,
    as_text,
)
from papiq.core.domain.locations import Box

# Fewer words say too little about a page: a blank back side, a page number.
MIN_WORDS = 10

UNSURE_BELOW = 60
"""Tesseract's confidence (0 to 100) below which a word counts as unsure."""

SMALL_LINE = 0.6
"""A line whose height (hOCR `x_size`) is under this share of the page's typical one is small
print, not content. Tesseract measures the lines of one font up to a fifth apart (a line of
digits or capitals has no descenders), so the cut lies well below: it takes a letterhead's or a
sender line's 6 pt beside 11 pt body text, and keeps 8 pt footnotes and every table row."""

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
    (`Datum..........`); one or two characters without a digit (stray marks read as `gy`,
    `TI`, `j`); or in a line under `SMALL_LINE` of the page's `typical_size` (a letterhead)."""
    text = word.text.strip()
    letters = sum(char.isalnum() for char in text)
    if not text or 2 * letters < len(text) or _LEADER.search(text):
        return True
    if len(text) <= 2 and not any(char.isdigit() for char in text):
        return True
    return (
        typical_size is not None and word.size is not None and word.size < SMALL_LINE * typical_size
    )


def content_words(words: Sequence[ReadWord]) -> list[ReadWord]:
    """The words of a page that are content (`is_noise`). The typical line size is the median
    over the words, so that the body text sets it, not a few headings or marks."""
    sizes = [word.size for word in words if word.size is not None and not is_noise(word)]
    typical = statistics.median(sizes) if sizes else None
    return [word for word in words if not is_noise(word, typical)]


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
    def unsure_share(self) -> float:
        return self.unsure / self.words if self.words else 0.0

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
        unsure (`PAPIQ_POOR_READING_THRESHOLD`), with enough of them to tell; of all its words
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
    if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
        raise ValidationError("invalid reading: no list of pages")
    if data.get("version") != READING_VERSION:
        return None
    found: dict[int, tuple[ReadWord, ...]] = {}
    for item in as_list(data.get("pages")):
        page = as_int(item.get("page")) if isinstance(item, dict) else None
        if not isinstance(item, dict) or page is None or page < 1:
            raise ValidationError(f"invalid page of a reading {item!r:.100}")
        if not isinstance(words := item.get("words"), list):
            raise ValidationError(f"invalid page of a reading {item!r:.100}")
        found[page] = tuple(ReadWord.from_json(word) for word in words)
    return found


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
    """What the OCR node logs: the archive and its pages, whether it is PDF/A, the engine's
    note, how each recognised page was read, whether another OCR's text layer was replaced, and
    a vision model's run (`vision`: model, endpoint, prompt, calls; `tokens` per call)."""

    archive: str
    pages: int
    pdfa: bool
    note: str | None = None
    readings: tuple[PageReading, ...] = ()
    read_again: bool = False
    vision: JsonObject | None = None
    tokens: tuple[JsonValue, ...] = ()

    def to_json(self) -> JsonObject:
        output: JsonObject = {"archive": self.archive, "pages": self.pages, "pdfa": self.pdfa}
        if self.note is not None:
            output["note"] = self.note
        if self.readings:
            output["readings"] = readings_to_json(self.readings)
        if self.read_again:
            output["read_again"] = True
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
        )
