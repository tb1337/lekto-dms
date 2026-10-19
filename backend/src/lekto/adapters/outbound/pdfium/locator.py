"""Quotes on the pages of a PDF, from its text layer with PDFium.

Each page's text is matched character by character, first with case and spacing evened out
(a line break counts as a space, a hyphen at the end of a line joins the word), then, for a
quote still not found, on its letters and digits alone: that passes over the marks the parsed
text adds (table bars, emphasis) and punctuation the text layer spells otherwise. PDFium gives
the boxes of the matched characters, one per line; they are turned into fractions of the page
as shown, its rotation applied.

A quote found neither way is looked for once more in the page's lines as they stand, as the
parse node reads them (`layout`): the text layer of an OCR'd scan holds Tesseract's blocks one
after the other, so a line across two of them (`Entgeltbescheinigung` on the left, its date on
the right) is not one run of characters there, though it is one line of the parsed text the
quote comes from.
"""

import asyncio
import html
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pypdfium2

from lekto.adapters.outbound.pdfium.chars import (
    SAME_LINE,
    Char,
    Geometry,
    page_chars,
    page_fractions,
)
from lekto.adapters.outbound.pdfium.fixed_pitch import page_lines
from lekto.adapters.outbound.pdfium.layout import WORD_GAP
from lekto.adapters.outbound.pdfium.library import LOCK
from lekto.core.domain.errors import UnprocessableDocumentError
from lekto.core.domain.locations import Box, Location

log = logging.getLogger(__name__)

MAX_PLACES = 5
"""Places reported per text: a quote is a passage, more than a few hits mean a common word."""

_SHORTEST_LOOSE = 3  # letters and digits a quote needs to be matched on those alone
_HYPHENS = "-\u2010\u2011"  # hyphen-minus, hyphen, non-breaking hyphen
_SOFT_HYPHEN = "\u00ad"
_LINE_BREAKS = "\r\n"


class PdfiumTextLocator:
    async def locate(self, pdf: Path, texts: Sequence[str]) -> list[tuple[Location, ...]]:
        if not texts:
            return []
        return await asyncio.to_thread(_locate, pdf, list(texts))


def _locate(pdf: Path, texts: list[str]) -> list[tuple[Location, ...]]:
    found: list[list[Location]] = [[] for _ in texts]
    with LOCK:
        try:
            document = pypdfium2.PdfDocument(pdf)
        except pypdfium2.PdfiumError as error:
            raise UnprocessableDocumentError(f"the PDF cannot be read: {error}") from None
        try:
            for number in range(1, len(document) + 1):
                _search_or_skip(document, number, texts, found)
        finally:
            document.close()
    return [tuple(places) for places in found]


def _search_or_skip(
    document: pypdfium2.PdfDocument, number: int, texts: list[str], found: list[list[Location]]
) -> None:
    """A page PDFium cannot read has no places; the others still count."""
    try:
        page = document[number - 1]
    except pypdfium2.PdfiumError:
        log.warning("page %d of a PDF cannot be read", number)
        return
    try:
        textpage = page.get_textpage()
        try:
            _search_page(number, page, textpage, texts, found)
        finally:
            textpage.close()
    except pypdfium2.PdfiumError:
        log.warning("page %d of a PDF has no readable text layer", number)
    finally:
        page.close()


def _search_page(
    number: int,
    page: pypdfium2.PdfPage,
    textpage: pypdfium2.PdfTextPage,
    texts: list[str],
    found: list[list[Location]],
) -> None:
    chars = _page_text(textpage)
    if not chars.strip():
        return
    strict, loose = _normalize(chars, loose=False), _normalize(chars, loose=True)
    geometry = Geometry.of(page)
    lined: _Lined | None = None
    for index, text in enumerate(texts):
        limit = MAX_PLACES - len(found[index])
        matches = _matches(strict, loose, text, limit)
        for first, last in matches:
            boxes = _boxes(textpage, first, last, geometry)
            if boxes:
                found[index].append(Location(number, boxes))
        if matches or limit <= 0:
            continue
        if lined is None:
            lined = _Lined.of(textpage, geometry)
        found[index].extend(Location(number, boxes) for boxes in lined.places(text, limit))


def _page_text(textpage: pypdfium2.PdfTextPage) -> str:
    """The page's text with one character per PDFium character index."""
    count = textpage.count_chars()
    if count <= 0:
        return ""
    text = str(textpage.get_text_range(0, count))
    if len(text) == count:
        return text
    # A character outside the basic plane (or one PDFium cannot name) breaks the alignment.
    return "".join((str(textpage.get_text_range(index, 1)) or "\0")[:1] for index in range(count))


@dataclass(frozen=True)
class _Normalized:
    text: str
    origin: list[int]  # the index of the character each one of `text` comes from


def _normalize(chars: str, *, loose: bool) -> _Normalized:
    out: list[str] = []
    origin: list[int] = []
    index = 0
    while index < len(chars):
        char = chars[index]
        if char == _SOFT_HYPHEN or char == "\0":
            index += 1
            continue
        if char in _HYPHENS and _line_ends_after(chars, index):
            index = _after_line_break(chars, index + 1)
            continue
        if char.isspace():
            if not loose and out and out[-1] != " ":
                out.append(" ")
                origin.append(index)
            index += 1
            continue
        if loose and not char.isalnum():
            index += 1
            continue
        for folded in char.casefold():
            out.append(folded)
            origin.append(index)
        index += 1
    return _Normalized("".join(out), origin)


def _line_ends_after(chars: str, index: int) -> bool:
    return chars[index + 1 :].lstrip(" \t")[:1] in ("\r", "\n")


def _after_line_break(chars: str, index: int) -> int:
    while index < len(chars) and chars[index] in " \t":
        index += 1
    while index < len(chars) and chars[index] in _LINE_BREAKS:
        index += 1
    return index


def _matches(
    strict: _Normalized, loose: _Normalized, text: str, limit: int
) -> list[tuple[int, int]]:
    """Character ranges (first, last) of the page where `text` stands, at most `limit`."""
    if limit <= 0:
        return []
    for page, is_loose in ((strict, False), (loose, True)):
        # A quote from a text parsed before 0.2.0 may carry its HTML entities.
        needle = _normalize(html.unescape(text), loose=is_loose).text.strip()
        if not needle or (is_loose and len(needle) < _SHORTEST_LOOSE):
            continue
        places: list[tuple[int, int]] = []
        start = page.text.find(needle)
        while start >= 0 and len(places) < limit:
            places.append((page.origin[start], page.origin[start + len(needle) - 1]))
            start = page.text.find(needle, start + len(needle))
        if places:
            return places
    return []


@dataclass(frozen=True)
class _Lined:
    """The upright characters of a page in its lines, top to bottom and each left to right
    (`page_lines`, as the parse node reads them), spelt evened out (`strict`: a gap wider than
    `WORD_GAP` of the characters' height and the end of a line count as a space) and on letters
    and digits alone (`loose`), each with the character every one of its letters comes from."""

    strict: tuple[str, list[Char]]
    loose: tuple[str, list[Char]]
    size: tuple[float, float]

    @classmethod
    def of(cls, textpage: pypdfium2.PdfTextPage, geometry: Geometry) -> "_Lined":
        upright, _ = page_chars(textpage, geometry)
        return cls(_spelt(upright, loose=False), _spelt(upright, loose=True), geometry.size)

    def places(self, text: str, limit: int) -> list[tuple[Box, ...]]:
        """The boxes of each place `text` stands at in the lines, at most `limit`."""
        for (spelt, origin), is_loose in ((self.strict, False), (self.loose, True)):
            needle = _normalize(html.unescape(text), loose=is_loose).text.strip()
            if not needle or (is_loose and len(needle) < _SHORTEST_LOOSE):
                continue
            places: list[tuple[Box, ...]] = []
            start = spelt.find(needle)
            while start >= 0 and len(places) < limit:
                matched = origin[start : start + len(needle)]
                boxes = _lines([box for char in matched if (box := self._box(char))])
                if boxes:
                    places.append(boxes)
                start = spelt.find(needle, start + len(needle))
            if places:
                return places
        return []

    def _box(self, char: Char) -> Box | None:
        width, height = self.size
        if width <= 0 or height <= 0:
            return None
        box = Box.clamped(*page_fractions(char.left, char.bottom, char.right, char.top, self.size))
        return box if box.width > 0 and box.height > 0 else None


def _spelt(chars: list[Char], *, loose: bool) -> tuple[str, list[Char]]:
    out: list[str] = []
    origin: list[Char] = []
    for line in page_lines(chars) if chars else []:
        last: Char | None = None
        for char in line.chars:
            apart = last is not None and char.left - last.right > WORD_GAP * max(
                char.height, last.height
            )
            if not loose and apart and out[-1:] != [" "]:
                out.append(" ")
                origin.append(char)
            last = char
            if loose and not char.text.isalnum():
                continue
            for folded in char.text.casefold():
                out.append(folded)
                origin.append(char)
        if not loose and out and out[-1] != " ":
            out.append(" ")
            origin.append(line.chars[-1])
    return "".join(out), origin


def _boxes(
    textpage: pypdfium2.PdfTextPage, first: int, last: int, geometry: Geometry
) -> tuple[Box, ...]:
    boxes = []
    for index in range(textpage.count_rects(first, last - first + 1)):
        box = geometry.fraction_box(*textpage.get_rect(index))
        if box is not None and box.width > 0 and box.height > 0:
            boxes.append(box)
    return _lines(boxes)


def _lines(boxes: list[Box]) -> tuple[Box, ...]:
    """One box per line: an OCR text layer places every word on its own, PDFium gives a box
    per word then. Boxes whose middles lie within half a box height of each other form a line
    (top to bottom); in a line, boxes that stand close are joined (left to right), a wide gap
    (another column) keeps them apart."""
    rows: list[list[Box]] = []
    for box in sorted(boxes, key=_middle):
        row = rows[-1] if rows else None
        if (
            row is not None
            and abs(_middle(box) - _middle(row[-1])) <= max(box.height, row[-1].height) * SAME_LINE
        ):
            row.append(box)
        else:
            rows.append([box])
    joined: list[Box] = []
    for row in rows:
        pieces: list[Box] = []
        for box in sorted(row, key=lambda box: box.x):
            last = pieces[-1] if pieces else None
            gap = box.x - (last.x + last.width) if last is not None else 0.0
            if last is not None and gap <= 2 * max(last.height, box.height):
                pieces[-1] = Box.clamped(
                    last.x,
                    min(last.y, box.y),
                    max(last.x + last.width, box.x + box.width),
                    max(last.y + last.height, box.y + box.height),
                )
            else:
                pieces.append(box)
        joined.extend(pieces)
    return tuple(joined)


def _middle(box: Box) -> float:
    return box.y + box.height / 2
