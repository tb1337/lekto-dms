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

import ctypes
import itertools
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pypdfium2
import pypdfium2.raw as pdfium_c

from papiq.adapters.outbound.pdfium.library import LOCK
from papiq.core.domain.errors import UnprocessableDocumentError

MIN_LINES = 3
"""Lines a block needs: one or two lines in a fixed-pitch font are a word set apart (a number,
a code), not a printout."""

_LETTERS = 5  # different letters of a font for its advances to say whether it is fixed-pitch
_SAME = 0.02  # advances within this fraction of each other are the same
_FIXED_PITCH_FLAG = 1  # bit of the flags of a font descriptor
_LINE_GAP = 3.0  # in line heights: a gap that wide between two lines ends the block
_BLANK_LINE = 1.5  # in line distances of the block: a gap that wide is a blank line
_REPLACEMENT = "�"

type _Font = tuple[str, float]  # name and height of its characters' boxes


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


@dataclass(frozen=True)
class _Char:
    text: str
    font: _Font
    flagged: bool  # the font descriptor says fixed-pitch
    left: float
    bottom: float
    right: float
    top: float

    @property
    def middle(self) -> float:
        return (self.bottom + self.top) / 2

    @property
    def height(self) -> float:
        return self.top - self.bottom


@dataclass(frozen=True)
class _Line:
    chars: list[_Char]  # left to right
    advance: float | None  # None: not all of the line is fixed-pitch with one advance

    @property
    def middle(self) -> float:
        return statistics.median(char.middle for char in self.chars)

    @property
    def height(self) -> float:
        return max(char.height for char in self.chars)


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
                blocks.extend(_blocks(number, _page_chars(document, number)))
            return blocks
        finally:
            document.close()


def _page_chars(document: pypdfium2.PdfDocument, number: int) -> list[_Char]:
    try:
        page = document[number - 1]
    except pypdfium2.PdfiumError:
        return []
    try:
        if page.get_rotation() % 360:
            return []
        left, bottom, _, _ = page.get_cropbox()
        textpage = page.get_textpage()
        try:
            return _chars(textpage, left, bottom)
        finally:
            textpage.close()
    except pypdfium2.PdfiumError:
        return []
    finally:
        page.close()


def _chars(textpage: pypdfium2.PdfTextPage, x: float, y: float) -> list[_Char]:
    """The visible characters of a page, without spaces, moved by (-x, -y)."""
    chars = []
    flags = ctypes.c_int()
    for index in range(textpage.count_chars()):
        if pdfium_c.FPDFText_IsGenerated(textpage, index) == 1:
            continue
        code = pdfium_c.FPDFText_GetUnicode(textpage, index)
        if code == 0:
            continue
        text = _REPLACEMENT if 0xD800 <= code <= 0xDFFF or code > 0x10FFFF else chr(code)
        if text.isspace():
            continue
        left, bottom, right, top = textpage.get_charbox(index, loose=True)
        if right <= left or top <= bottom:
            continue
        size = pdfium_c.FPDFText_GetFontInfo(textpage, index, None, 0, ctypes.byref(flags))
        name = ctypes.create_string_buffer(max(size, 1))
        pdfium_c.FPDFText_GetFontInfo(textpage, index, name, size, ctypes.byref(flags))
        chars.append(
            _Char(
                text=text,
                font=(name.value.decode("utf-8", "replace"), round(top - bottom, 1)),
                flagged=bool(flags.value & _FIXED_PITCH_FLAG),
                left=left - x,
                bottom=bottom - y,
                right=right - x,
                top=top - y,
            )
        )
    return chars


def _blocks(page: int, chars: list[_Char]) -> list[FixedPitchBlock]:
    advances = _fixed_pitch_fonts(chars)
    blocks: list[FixedPitchBlock] = []
    run: list[_Line] = []
    for line in [*_lines(chars, advances), None]:
        if line is not None and run and _continues(run[-1], line):
            run.append(line)
            continue
        if len(run) >= MIN_LINES:
            blocks.append(_block(page, run))
        run = [line] if line is not None and line.advance is not None else []
    return blocks


def _fixed_pitch_fonts(chars: list[_Char]) -> dict[_Font, float]:
    """The fixed-pitch fonts of a page and their advance."""
    widths: dict[_Font, dict[str, float]] = defaultdict(dict)
    flagged: dict[_Font, bool] = {}
    for char in chars:
        widths[char.font].setdefault(char.text, char.right - char.left)
        flagged[char.font] = flagged.get(char.font, False) or char.flagged
    fixed = {}
    for font, advances in widths.items():
        if not _same(min(advances.values()), max(advances.values())):
            continue
        if flagged[font] or sum(text.isalpha() for text in advances) >= _LETTERS:
            fixed[font] = statistics.median(advances.values())
    return fixed


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= _SAME * max(a, b)


def _lines(chars: list[_Char], advances: dict[_Font, float]) -> list[_Line]:
    """The lines of a page, from the top: characters whose middles lie within half a character
    height of the first one's."""
    rows: list[list[_Char]] = []
    for char in sorted(chars, key=lambda char: -char.middle):
        first = rows[-1][0] if rows else None
        if first is not None and first.middle - char.middle <= min(first.height, char.height) / 2:
            rows[-1].append(char)
        else:
            rows.append([char])
    lines = []
    for row in rows:
        # Fonts of one advance (regular and bold, say) set one grid.
        found = [advances.get(char.font) for char in row]
        known = [advance for advance in found if advance is not None]
        same = len(known) == len(found) and all(_same(known[0], other) for other in known)
        lines.append(_Line(sorted(row, key=lambda char: char.left), known[0] if same else None))
    return lines


def _continues(last: _Line, line: _Line) -> bool:
    return (
        last.advance is not None
        and line.advance is not None
        and _same(last.advance, line.advance)
        and last.middle - line.middle <= _LINE_GAP * max(last.height, line.height)
    )


def _block(page: int, lines: list[_Line]) -> FixedPitchBlock:
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


def _pitch(lines: list[_Line]) -> float:
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


def _columns(line: _Line, origin: float, pitch: float) -> str:
    cells: dict[int, str] = {}
    for char in line.chars:
        column = round((char.left - origin) / pitch)
        if cells.get(column) == char.text:
            continue  # struck twice for bold
        while column in cells:
            column += 1
        cells[column] = char.text
    return "".join(cells.get(column, " ") for column in range(max(cells) + 1)).rstrip()
