"""Text set in a fixed-pitch font, as it is set: lines of characters in columns.

A program that prints in a fixed-pitch font (a time sheet from a payroll system, a terminal
listing) lines its columns up with spaces and draws its tables with `|` and `-`. A layout
analysis takes that for paragraphs and tables of its own and loses the alignment. Here a run of
at least `MIN_LINES` lines whose characters are all set with one advance in fixed-pitch fonts
becomes a block: each character goes to its column (counted in characters from the left edge of
the block), and a wider gap between two lines becomes one blank line.

Whether a font is fixed-pitch is measured: all its characters on the page have the same advance
(PDFium's loose character box), over at least `_LETTERS` different letters. With fewer letters,
the FixedPitch flag of its font descriptor decides, as long as the advances agree. The text layer
OCR puts on a scan is set in a proportional font, so a scan keeps the layout analysis' reading.

A rotated page is left alone: its boxes would have to be turned the way the layout analysis
turns them.
"""

import itertools
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pypdfium2

from papiq.adapters.outbound.pdfium.chars import (
    Char,
    Font,
    Geometry,
    Line,
    lines_of,
    page_chars,
    same,
)
from papiq.adapters.outbound.pdfium.library import LOCK
from papiq.core.domain.errors import UnprocessableDocumentError

MIN_LINES = 3
"""Lines a block needs: one or two lines in a fixed-pitch font are a word set apart (a number,
a code), not a printout."""

_LETTERS = 5  # different letters of a font for its advances to say whether it is fixed-pitch
_LINE_GAP = 3.0  # in line heights: a gap that wide between two lines ends the block
_BLANK_LINE = 1.5  # in line distances of the block: a gap that wide is a blank line


@dataclass(frozen=True)
class FixedPitchBlock:
    """Lines set in a fixed-pitch font on page `page` (from 1). The box is in points, from the
    bottom left corner of the visible page (its crop box); `line` is the usual distance from one
    line to the next."""

    page: int
    left: float
    bottom: float
    right: float
    top: float
    line: float
    text: str


def fixed_pitch_blocks(path: Path) -> list[FixedPitchBlock]:
    """The blocks of fixed-pitch text in a PDF, page by page from the top (blocking; run it in a
    thread). A page PDFium cannot read has none."""
    with LOCK:
        try:
            document = pypdfium2.PdfDocument(path)
        except pypdfium2.PdfiumError as error:
            raise UnprocessableDocumentError(f"the PDF cannot be read: {error}") from None
        try:
            blocks: list[FixedPitchBlock] = []
            for number in range(1, len(document) + 1):
                blocks.extend(blocks_of(number, _page_chars(document, number)))
            return blocks
        finally:
            document.close()


def _page_chars(document: pypdfium2.PdfDocument, number: int) -> list[Char]:
    try:
        page = document[number - 1]
    except pypdfium2.PdfiumError:
        return []
    try:
        if page.get_rotation() % 360:
            return []
        textpage = page.get_textpage()
        try:
            upright, _ = page_chars(textpage, Geometry.of(page))
            return upright
        finally:
            textpage.close()
    except pypdfium2.PdfiumError:
        return []
    finally:
        page.close()


def blocks_of(page: int, chars: list[Char]) -> list[FixedPitchBlock]:
    """The blocks of fixed-pitch text among the upright characters of page `page`."""
    advances = fixed_pitch_fonts(chars)
    blocks: list[FixedPitchBlock] = []
    run: list[Line] = []
    for line in [*lines_of(chars, advances), None]:
        if line is not None and run and _continues(run[-1], line):
            run.append(line)
            continue
        if len(run) >= MIN_LINES:
            blocks.append(_block(page, run))
        run = [line] if line is not None and line.advance is not None else []
    return blocks


def fixed_pitch_fonts(chars: list[Char]) -> dict[Font, float]:
    """The fixed-pitch fonts of a page and their advance."""
    widths: dict[Font, dict[str, float]] = defaultdict(dict)
    flagged: dict[Font, bool] = {}
    for char in chars:
        widths[char.font].setdefault(char.text, char.right - char.left)
        flagged[char.font] = flagged.get(char.font, False) or char.flagged
    fixed = {}
    for font, advances in widths.items():
        if not same(min(advances.values()), max(advances.values())):
            continue
        if flagged[font] or sum(text.isalpha() for text in advances) >= _LETTERS:
            fixed[font] = statistics.median(advances.values())
    return fixed


def _continues(last: Line, line: Line) -> bool:
    return (
        last.advance is not None
        and line.advance is not None
        and same(last.advance, line.advance)
        and last.middle - line.middle <= _LINE_GAP * max(last.height, line.height)
    )


def _block(page: int, lines: list[Line]) -> FixedPitchBlock:
    chars = [char for line in lines for char in line.chars]
    origin = min(char.left for char in chars)
    pitch = _pitch(lines)
    distances = [above.middle - below.middle for above, below in itertools.pairwise(lines)]
    usual = statistics.median(distances)
    text: list[str] = []
    for index, line in enumerate(lines):
        if index and distances[index - 1] > _BLANK_LINE * usual:
            text.append("")
        text.append(_columns(line, origin, pitch))
    return FixedPitchBlock(
        page=page,
        left=origin,
        bottom=min(char.bottom for char in chars),
        right=max(char.right for char in chars),
        top=max(char.top for char in chars),
        line=usual,
        text="\n".join(text),
    )


def _pitch(lines: list[Line]) -> float:
    """The distance from one column to the next: that of neighbouring characters (it includes
    any character spacing), else the advance."""
    steps = [
        right.left - left.left
        for line in lines
        if line.advance is not None
        for left, right in itertools.pairwise(line.chars)
        if 0 < right.left - left.left < 1.5 * line.advance
    ]
    if steps:
        return statistics.median(steps)
    return statistics.median(line.advance for line in lines if line.advance is not None)


def _columns(line: Line, origin: float, pitch: float) -> str:
    cells: dict[int, str] = {}
    for char in line.chars:
        column = round((char.left - origin) / pitch)
        if cells.get(column) == char.text:
            continue  # struck twice for bold
        while column in cells:
            column += 1
        cells[column] = char.text
    return "".join(cells.get(column, " ") for column in range(max(cells) + 1)).rstrip()
