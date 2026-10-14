"""How well the OCR read a page: the words it recognised there and how many of them it was
unsure of. A page with a text layer of its own is not read again and has no reading.

A value on a poorly read page is only suggested (the fields node, the judge's document date):
the engine is often sure of a misread word, but where many words are unsure, the page is a
broken scan, and a number read there may be anything.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.json_value import JsonObject, JsonValue

# Fewer words say too little about a page: a blank back side, a page number.
MIN_WORDS = 10


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
        page, words, unsure = item.get("page"), item.get("words"), item.get("unsure")
        if isinstance(page, int) and isinstance(words, int) and isinstance(unsure, int):
            try:
                readings.append(PageReading(page=page, words=words, unsure=unsure))
            except ValidationError:
                continue
    return tuple(readings)
