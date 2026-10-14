"""The text of a PDF as it is set, from its text layer with PDFium: the parser of the archive.

Every line of a page as it is set, its words in columns on the page's grid (like `pdftotext
-layout`), so that a label and its amount, a column of figures or the letterhead beside the
address stay where they are printed. The characters and their lines come from `chars`.

- A word ends where the gap to the next character is wider than `WORD_GAP` character heights.
- After a gap of up to `SPACE` grid columns the next word follows after one space (running
  text); after a wider gap it starts at its column on the grid, at least two spaces on, so that
  columns line up. The grid is the usual width of a character on the page.
- A block of fixed-pitch lines (a printout, see `fixed_pitch`) keeps its own columns exactly.
- A gap between two lines wider than `BLANK_LINE` usual line distances is a blank line.
- A page most of whose text runs across it is read in that direction (`chars.reading_turn`);
  text at an angle to it (a page number up the margin) is read along its own direction, one
  line per run, after the rest of its page.
- A hyphen PDFium marks at the end of a line is written as the hyphen it prints as.

Pages are separated by a form feed on a line of its own (`PAGE_BREAK`). The structure is Papiq's
own JSON: the pages with their size in points, their lines with text, box and words, each word
with its box; a box is `[x1, y1, x2, y2]` in fractions of the page as shown, from its top left.
"""

import asyncio
import importlib.metadata
import itertools
import json
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pypdfium2

from papiq.adapters.outbound.pdfium.chars import (
    Angled,
    Char,
    Geometry,
    lines_of,
    page_chars,
    reading_turn,
)
from papiq.adapters.outbound.pdfium.fixed_pitch import FixedPitchBlock, blocks_of
from papiq.adapters.outbound.pdfium.library import LOCK
from papiq.core.domain.errors import UnprocessableDocumentError
from papiq.core.ports.parser import ParseResult

VERSION = 1
"""The version of the rules above, in the processing log: a change of them shows."""

WORD_GAP = 0.12
SPACE = 2.0
BLANK_LINE = 1.6
PAGE_BREAK = "\n\f\n"
_HYPHENS = {"￾": "-", "­": "-", "\u0002": "-"}

type Words = list[list[Char]]


@dataclass(frozen=True)
class Page:
    number: int
    width: float
    height: float
    text: str
    lines: list[dict[str, Any]]


class LayoutParser:
    """The text as it is set; fast enough to run in a thread of the worker."""

    async def parse(self, source: Path, *, markdown: Path, structure: Path) -> ParseResult:
        pages = await asyncio.to_thread(read_pages, source)
        text = PAGE_BREAK.join(page.text for page in pages)
        data = {
            "parser": "layout",
            "version": VERSION,
            "pages": [
                {"number": page.number, "width": page.width, "height": page.height}
                | {"lines": page.lines}
                for page in pages
            ],
        }
        try:
            await asyncio.to_thread(markdown.write_text, text, encoding="utf-8")
            await asyncio.to_thread(
                structure.write_text, json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except BaseException:
            for path in (markdown, structure):
                await asyncio.to_thread(path.unlink, missing_ok=True)
            raise
        empty = [str(page.number) for page in pages if not page.text.strip()]
        note = None
        if empty and len(empty) < len(pages):
            note = f"no text on page{'s' if len(empty) > 1 else ''} {', '.join(empty)}"
        return ParseResult(
            pages=len(pages),
            parser=f"layout {VERSION}, pypdfium2 {importlib.metadata.version('pypdfium2')}",
            note=note,
        )


def read_pages(path: Path) -> list[Page]:
    """Every page's text and lines (blocking; run it in a thread)."""
    with LOCK:
        try:
            document = pypdfium2.PdfDocument(path)
        except pypdfium2.PdfiumError as error:
            raise UnprocessableDocumentError(f"the PDF cannot be read: {error}") from None
        try:
            pages = []
            for number in range(1, len(document) + 1):
                page = document[number - 1]
                try:
                    geometry = Geometry.of(page)
                    textpage = page.get_textpage()
                    try:
                        geometry = geometry.turned(reading_turn(textpage, geometry))
                        upright, angled = page_chars(textpage, geometry)
                    finally:
                        textpage.close()
                finally:
                    page.close()
                width, height = geometry.size
                text, lines = _page(upright, angled, width, height)
                pages.append(Page(number, round(width, 2), round(height, 2), text, lines))
            return pages
        finally:
            document.close()


def _page(
    chars: list[Char], angled: list[Angled], width: float, height: float
) -> tuple[str, list[dict[str, Any]]]:
    text: list[str] = []
    structure: list[dict[str, Any]] = []
    if chars:
        lines = lines_of(chars, {})
        blocks = blocks_of(0, chars)
        origin = min(char.left for char in chars)
        unit = statistics.median(char.right - char.left for char in chars)
        distances = [above.middle - below.middle for above, below in itertools.pairwise(lines)]
        usual = statistics.median(distances) if distances else 0.0
        written: set[int] = set()
        for index, line in enumerate(lines):
            words = _words(line.chars, lambda char: (char.left, char.right), _height)
            structure.append(_line(words, width, height))
            block = _block(line.chars, blocks)
            if block is not None and id(block) in written:
                continue
            if index and usual and distances[index - 1] > BLANK_LINE * usual:
                text.append("")
            if block is not None:
                written.add(id(block))
                text.extend(block.text.split("\n"))
            else:
                text.append(_columns(words, origin, unit))
    for words in _angled_runs(angled):
        if not text or text[-1]:
            text.append("")
        text.append(" ".join(_spelt(word) for word in words))
        structure.append(_line(words, width, height))
    return "\n".join(text).strip("\n"), structure


def _block(chars: Sequence[Char], blocks: list[FixedPitchBlock]) -> FixedPitchBlock | None:
    """The fixed-pitch block all characters of a line lie in, give or take half a line."""
    for block in blocks:
        slack = block.line / 2
        if all(
            block.left - slack <= char.left
            and char.right <= block.right + slack
            and block.bottom - slack <= char.bottom
            and char.top <= block.top + slack
            for char in chars
        ):
            return block
    return None


def _height(char: Char) -> float:
    return char.height


def _words(
    chars: Sequence[Char],
    extent: Callable[[Char], tuple[float, float]],
    size: Callable[[Char], float],
) -> Words:
    """Characters in reading order into words: a gap wider than `WORD_GAP` of the characters'
    size ends one. `extent`: where a character starts and ends along the line."""
    words: Words = []
    for char in chars:
        last = words[-1][-1] if words else None
        if last is None or extent(char)[0] - extent(last)[1] > WORD_GAP * max(
            size(char), size(last)
        ):
            words.append([char])
        elif char.text != last.text or abs(extent(char)[0] - extent(last)[0]) >= 0.5:
            words[-1].append(char)  # else struck twice for bold
    return words


def _spelt(word: list[Char]) -> str:
    return "".join(_HYPHENS.get(char.text, char.text) for char in word)


def _columns(words: Words, origin: float, unit: float) -> str:
    text = ""
    previous: Char | None = None
    for word in words:
        if previous is None:
            text = " " * round((word[0].left - origin) / unit)
        elif word[0].left - previous.right <= SPACE * unit:
            text += " "
        else:
            column = max(round((word[0].left - origin) / unit), len(text) + 2)
            text += " " * (column - len(text))
        text += _spelt(word)
        previous = word[-1]
    return text.rstrip()


def _angled_runs(angled: list[Angled]) -> list[Words]:
    """Text set at an angle, one run per line: characters of one direction that share their
    middle across the direction, in reading order, into words."""
    runs: list[Words] = []
    by_direction: dict[int, list[Char]] = {}
    for item in angled:
        by_direction.setdefault(round(item.angle / 90) % 4, []).append(item.char)
    for direction, chars in sorted(by_direction.items()):
        vertical = direction in (1, 3)

        def across(char: Char, vertical: bool = vertical) -> float:
            return (char.left + char.right) / 2 if vertical else char.middle

        groups: list[list[Char]] = []
        for char in sorted(chars, key=across):
            if groups and across(char) - across(groups[-1][-1]) <= char.height / 2:
                groups[-1].append(char)
            else:
                groups.append([char])
        for group in groups:
            if direction == 3:  # up the page
                group.sort(key=lambda char: char.bottom)
                runs.append(_words(group, lambda c: (c.bottom, c.top), _width))
            elif direction == 1:  # down the page
                group.sort(key=lambda char: -char.top)
                runs.append(_words(group, lambda c: (-c.top, -c.bottom), _width))
            else:  # upside down
                group.sort(key=lambda char: -char.right)
                runs.append(_words(group, lambda c: (-c.right, -c.left), _height))
    return runs


def _width(char: Char) -> float:
    return char.right - char.left


def _line(words: Words, width: float, height: float) -> dict[str, Any]:
    return {
        "text": " ".join(_spelt(word) for word in words),
        "box": _box([char for word in words for char in word], width, height),
        "words": [{"text": _spelt(word), "box": _box(word, width, height)} for word in words],
    }


def _box(chars: Sequence[Char], width: float, height: float) -> list[float]:
    left = min(char.left for char in chars)
    right = max(char.right for char in chars)
    bottom = min(char.bottom for char in chars)
    top = max(char.top for char in chars)
    return [
        round(max(0.0, left / width), 4),
        round(max(0.0, (height - top) / height), 4),
        round(min(1.0, right / width), 4),
        round(min(1.0, (height - bottom) / height), 4),
    ]
