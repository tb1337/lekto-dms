"""Whether a field's value stands by its label (issue #55, step 1: measured and recorded, not
enforced).

The model gives, beside a value and its quote, the label of the value as it stands in the
document (`Gesamtbrutto`), or none. The label is looked for among the words of the parsed text
(`content.json`, which every document has, digital or scanned), as the quote locator matches a
quote: with case and spacing evened out, then on its letters and digits alone. The value stands
by the label on the label's line to its right, or below it in the same column (overlapping it,
or starting within `LABEL_COLUMN` characters of its left edge) within `LABEL_LINES` lines. No
layout is assumed beyond line and column: the line (the usual distance between the page's
lines) and the character (the median width of one in its words' boxes) are measured on the page
itself, as `reading.gap` measures, so a receipt is measured as truly as a letter.
"""

import html
import itertools
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.evidence import DocumentText
from lekto.core.domain.json_value import JsonObject, JsonValue, as_int, as_list, as_number, as_text
from lekto.core.domain.locations import Box, Location
from lekto.core.domain.reading import Placed, value_runs, value_words, words_at

LABEL_LINES = 3
"""How many lines below its label a value may stand in the label's column (Tobi, 19.10.2026)."""

LABEL_COLUMN = 4
"""How many characters the left edge of a value below its label may stand from the label's left
edge and still be in its column, where the two do not overlap (a value set a little in)."""

_SHORTEST_LOOSE = 3  # letters and digits a label needs to be matched on those alone, as quotes


class LabelOutcome(StrEnum):
    """What the label check found."""

    BESIDE = "beside"  # the value stands by the label
    APART = "apart"  # the label stands in the text, the value not by it
    LABEL_MISSING = "label_missing"  # the label does not stand in the text
    NO_LABEL = "no_label"  # the model gave none
    UNKNOWN = "unknown"  # no words with boxes, the value not found, or a type not checked


@dataclass(frozen=True)
class LabelCheck:
    """The label the model gave for a field's value (`text`, None for none) and what the check
    found (`outcome`)."""

    text: str | None
    outcome: LabelOutcome

    def to_json(self) -> JsonObject:
        return {"text": self.text, "outcome": self.outcome.value}

    @classmethod
    def from_json(cls, data: JsonValue) -> Self | None:
        """None for anything but a check (and for an entry from before the check)."""
        if not isinstance(data, dict):
            return None
        try:
            outcome = LabelOutcome(str(data.get("outcome")))
        except ValueError:
            return None
        return cls(as_text(data.get("text")), outcome)


@dataclass(frozen=True)
class LaidWord:
    """A word of the parsed text and its box on the page as it is shown."""

    text: str
    box: Box


def layout_words(data: JsonValue) -> dict[int, tuple[LaidWord, ...]] | None:
    """The words of the parsed text by page, in reading order, from the structure the parser
    writes (`content.json`: `pages`, each with its `number` and `lines`, each line with its
    `words`, each word with `text` and `box` as `[x1, y1, x2, y2]` in fractions of the page from
    its top left). None for a structure of another kind (Docling's, before 0.2); a word without
    a usable box is left out."""
    if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
        return None
    pages: dict[int, tuple[LaidWord, ...]] = {}
    for page in as_list(data.get("pages")):
        if not isinstance(page, dict) or (number := as_int(page.get("number"))) is None:
            continue
        words = []
        for line in as_list(page.get("lines")):
            items = as_list(line.get("words")) if isinstance(line, dict) else []
            for item in items:
                word = _laid_word(item)
                if word is not None:
                    words.append(word)
        pages[number] = tuple(words)
    return pages


def _laid_word(item: JsonValue) -> LaidWord | None:
    if not isinstance(item, dict) or not (text := as_text(item.get("text"))):
        return None
    corners = [
        number for value in as_list(item.get("box")) if (number := as_number(value)) is not None
    ]
    if len(corners) != 4:
        return None
    try:
        box = Box.clamped(*corners)
    except ValidationError:
        return None
    return LaidWord(text, box) if box.width > 0 and box.height > 0 else None


def grid_layout(text: str) -> JsonObject:
    """The structure of a text set on a fixed grid, in the parser's format (`layout_words`): a
    line of the page per line of the text, a column per character, the pages apart by form
    feeds. What the evaluation keeps beside a case's text, where no PDF was parsed."""
    pages: list[JsonValue] = []
    for number, page in enumerate(text.split("\f"), start=1):
        rows = page.strip("\n").split("\n")
        columns = max([80, *(len(row) for row in rows)])
        height = max(60, len(rows))
        lines: list[JsonValue] = []
        for index, row in enumerate(rows):
            words: list[JsonValue] = []
            start = None
            for column, char in enumerate(row + " "):
                if not char.isspace() and start is None:
                    start = column
                elif char.isspace() and start is not None:
                    box = [start / columns, (index + 0.15) / height]
                    box += [column / columns, (index + 0.85) / height]
                    words.append({"text": row[start:column], "box": [round(v, 4) for v in box]})
                    start = None
            if words:
                lines.append({"text": " ".join(row.split()), "words": words})
        pages.append({"number": number, "width": 595.0, "height": 842.0, "lines": lines})
    return {"parser": "grid", "version": 1, "pages": pages}


def label_places[W: Placed](words: Sequence[W], label: str) -> list[tuple[W, ...]]:
    """The runs of `words` (those of a page, in reading order) the label stands at: matched with
    case and spacing evened out, or else on its letters and digits alone (with at least three of
    them), as the quote locator matches, but as whole words: a match starts at a word's start
    and ends at a word's end (`Brutto` is not in `Steuerbrutto`, `Gesamtbrutto` is in
    `**Gesamtbrutto:**` on letters and digits)."""
    for loose in (False, True):
        spelt, origin = _spelt([word.text for word in words], loose=loose)
        needle = _spelt([html.unescape(label)], loose=loose)[0].strip()
        if not needle or (loose and len(needle) < _SHORTEST_LOOSE):
            continue
        places = []
        start = spelt.find(needle)
        while start >= 0:
            end = start + len(needle)
            if _bounded(spelt, origin, start, end):
                indexes = sorted(set(origin[start:end]))
                places.append(tuple(words[index] for index in indexes))
            start = spelt.find(needle, start + 1)
        if places:
            return places
    return []


def _bounded(spelt: str, origin: Sequence[int], start: int, end: int) -> bool:
    """Whether `spelt[start:end]` starts at a word's start and ends at a word's end: beside it
    the end of the text, a character of another word, or, within a word, no letter or digit
    on one side (`Brutto:` in `Brutto:3.650,00`, not `Brutto` in `Steuerbrutto`)."""

    def edge(inside: int, outside: int) -> bool:
        if outside < 0 or outside >= len(spelt) or origin[outside] != origin[inside]:
            return True
        return not (spelt[inside].isalnum() and spelt[outside].isalnum())

    return edge(start, start - 1) and edge(end - 1, end)


def _spelt(texts: Sequence[str], *, loose: bool) -> tuple[str, list[int]]:
    """The texts one after the other, folded, a space between them and for any run of spaces in
    them (`loose`: letters and digits only), with the text each character comes from."""
    out: list[str] = []
    origin: list[int] = []
    for index, text in enumerate(texts):
        for char in f"{text} ":
            if char.isspace():
                if not loose and out and out[-1] != " ":
                    out.append(" ")
                    origin.append(index)
            elif not loose or char.isalnum():
                for folded in char.casefold():
                    out.append(folded)
                    origin.append(index)
    return "".join(out), origin


@dataclass(frozen=True)
class _Measure:
    """The line (the usual distance between the page's lines) and the character (the median
    width of one) of a page, as shares of its height and width."""

    line: float
    character: float

    @classmethod
    def of(cls, words: Sequence[Placed]) -> Self | None:
        boxes = [(word.text.strip(), word.box) for word in words if word.box is not None]
        boxes = [(text, box) for text, box in boxes if text and box.width > 0 and box.height > 0]
        if not boxes:
            return None
        character = statistics.median(box.width / len(text) for text, box in boxes)
        rows: list[list[Box]] = []
        for box in sorted((box for _, box in boxes), key=_middle):
            if (
                rows
                and abs(_middle(box) - _middle(rows[-1][0]))
                <= max(box.height, rows[-1][0].height) / 2
            ):
                rows[-1].append(box)
            else:
                rows.append([box])
        middles = [statistics.median(_middle(box) for box in row) for row in rows]
        distances = [below - above for above, below in itertools.pairwise(middles)]
        line = (
            statistics.median(distances)
            if distances
            else statistics.median(box.height for _, box in boxes)
        )
        return cls(line, character) if line > 0 and character > 0 else None


def stands_by(
    words: Sequence[Placed],
    label: Sequence[Placed],
    value: Sequence[Placed],
    measure: _Measure | None = None,
) -> bool:
    """Whether the value's words stand by the label's on their page (`words`, which measure it,
    unless `measure` is given): on the label's line to its right, or below it in its column
    within `LABEL_LINES` lines. A label over two lines (or read across columns) is measured by
    the line of its last word, where it ends. A value that shares a word with its label
    (`Brutto:3.650,00`) stands by it."""
    if any(word in value for word in label):
        return True
    measure = measure or _Measure.of(words)
    first, second = _union(_last_line(label)), _union(value)
    if measure is None or first is None or second is None:
        return False
    down = (_middle(second) - _middle(first)) / measure.line
    if abs(_middle(second) - _middle(first)) <= max(first.height, second.height) / 2:
        return second.x >= first.x + first.width - measure.character
    if not 0.5 < down <= LABEL_LINES + 0.5:
        return False
    overlap = min(first.x + first.width, second.x + second.width) - max(first.x, second.x)
    return overlap > 0 or abs(second.x - first.x) <= LABEL_COLUMN * measure.character


def value_places[W: Placed](
    pages: Mapping[int, Sequence[W]],
    locations: Sequence[Location],
    shows: Callable[[DocumentText], bool],
) -> list[tuple[int, tuple[W, ...]]]:
    """Where a value's words stand: in each place of its quote, the words there that show it
    (`value_words`); where none of them does (or the quote has no place), every place the value
    stands on the pages (`value_runs`; Tobi, 28.10.2026, #55 19.3: an amount in a table and
    again in a sentence is by its label where either place is)."""
    places = []
    for location in locations:
        found = value_words(words_at(location, pages.get(location.page, ())), shows)
        if found:
            places.append((location.page, found))
    if not places:
        places.extend(value_runs(pages, shows))
    return places


def check_label(
    label: str | None,
    pages: Mapping[int, Sequence[LaidWord]],
    locations: Sequence[Location],
    shows: Callable[[DocumentText], bool] | None,
) -> LabelCheck:
    """The label check of a value of a checked type: none without a label; unknown without
    words, or where the value is not found (`value_places`; `shows` None: not written as such);
    otherwise whether the label stands in the text, and, at any of its places, by any place of
    the value."""
    if label is None:
        return LabelCheck(None, LabelOutcome.NO_LABEL)
    if not any(pages.values()):
        return LabelCheck(label, LabelOutcome.UNKNOWN)
    found = {page: label_places(words, label) for page, words in pages.items()}
    if not any(found.values()):
        return LabelCheck(label, LabelOutcome.LABEL_MISSING)
    values = [] if shows is None else value_places(pages, locations, shows)
    if not values:
        return LabelCheck(label, LabelOutcome.UNKNOWN)
    measures = {page: _Measure.of(pages[page]) for page in {page for page, _ in values}}
    beside = any(
        stands_by(pages[page], place, value, measures[page])
        for page, value in values
        for place in found.get(page, ())
    )
    return LabelCheck(label, LabelOutcome.BESIDE if beside else LabelOutcome.APART)


def _last_line[W: Placed](words: Sequence[W]) -> list[W]:
    """The words on the line of the last one: those whose middle lies within half a height of
    its middle."""
    placed = [word for word in words if word.box is not None]
    if not placed:
        return []
    last = placed[-1].box
    assert last is not None
    return [
        word
        for word in placed
        if word.box is not None
        and abs(_middle(word.box) - _middle(last)) <= max(word.box.height, last.height) / 2
    ]


def _union(words: Sequence[Placed]) -> Box | None:
    boxes = [word.box for word in words if word.box is not None]
    if not boxes:
        return None
    return Box.clamped(
        min(box.x for box in boxes),
        min(box.y for box in boxes),
        max(box.x + box.width for box in boxes),
        max(box.y + box.height for box in boxes),
    )


def _middle(box: Box) -> float:
    return box.y + box.height / 2
