"""How well the OCR read a page: the words it recognised there and how many of them it was
unsure of. A page with a text layer of its own is not read again and has no reading.

A value on a poorly read page is only suggested (the fields node, the judge's document date):
the engine is often sure of a misread word, but where many words are unsure, the page is a
broken scan, and a number read there may be anything.
"""

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
    as_object,
    as_text,
)

# Fewer words say too little about a page: a blank back side, a page number.
MIN_WORDS = 10

NO_TEXT_REASON = "no text recognised: the pages are blank or hold only pictures"
"""Why the parse node fails a document without any text."""


@dataclass(frozen=True)
class PageReading:
    """`page` from 1; `unsure` of its `words` the engine was unsure of."""

    page: int
    words: int
    unsure: int

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValidationError("pages are numbered from 1")
        if not 0 <= self.unsure <= self.words:
            raise ValidationError("the unsure words must be some of the words")

    @property
    def unsure_share(self) -> float:
        return self.unsure / self.words if self.words else 0.0

    def poor(self, threshold: float) -> bool:
        """Whether the page counts as poorly read: at least `threshold` of its words unsure
        (`PAPIQ_POOR_READING_THRESHOLD`), with enough words to tell."""
        return self.words >= MIN_WORDS and self.unsure_share >= threshold

    def to_json(self) -> JsonObject:
        return {"page": self.page, "words": self.words, "unsure": self.unsure}


def readings_to_json(readings: Sequence[PageReading]) -> list[JsonValue]:
    return [reading.to_json() for reading in readings]


def readings_from_json(data: object) -> tuple[PageReading, ...]:
    """The readings as the OCR node wrote them into its log entry; none for an entry without
    (written before readings, or the engine read no page)."""
    if not isinstance(data, list):
        return ()
    readings: list[PageReading] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        page, words, unsure = (as_int(item.get(key)) for key in ("page", "words", "unsure"))
        if page is not None and words is not None and unsure is not None:
            try:
                readings.append(PageReading(page=page, words=words, unsure=unsure))
            except ValidationError:
                continue
    return tuple(readings)


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
