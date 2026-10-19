"""The visible characters of a PDF page with PDFium, and their lines.

PDFium's loose character boxes (the advance of a character, not its ink) are turned onto the
page as shown: in points from the bottom left corner of the crop box, the page's rotation
applied, so that text upright on the screen runs left to right here. A page most of whose text
runs in another direction (a table printed across the page, a scan the OCR read sideways) is
turned that way as well (`reading_turn`). A character set at an angle to that (a page number up
the margin) comes apart, with its angle.

Spaces are left out, also those PDFium adds between words: some PDFs place their words without
any, so the gaps between the boxes tell where a word ends.
"""

import ctypes
import dataclasses
import math
import statistics
from collections import Counter
from dataclasses import dataclass

import pypdfium2
import pypdfium2.raw as pdfium_c

from lekto.core.domain.locations import Box

REPLACEMENT = "�"
UPRIGHT = 10.0  # degrees: a character turned less than this is upright
SAME = 0.02  # advances within this fraction of each other are the same
SAME_LINE = 0.5
"""Characters (or word boxes) whose middles lie within this share of a height of each other
stand in one line."""
_FIXED_PITCH_FLAG = 1  # bit of the flags of a font descriptor

type Font = tuple[str, float]  # name and height of its characters' boxes


@dataclass(frozen=True)
class Char:
    text: str
    font: Font
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
class Angled:
    """A character set at an angle on the page as shown, clockwise in degrees: 90 reads down
    the page, 270 up it, 180 is upside down."""

    char: Char
    angle: float


@dataclass(frozen=True)
class Line:
    chars: list[Char]  # left to right
    advance: float | None  # None: not all of the line is fixed-pitch with one advance

    @property
    def middle(self) -> float:
        return statistics.median(char.middle for char in self.chars)

    @property
    def height(self) -> float:
        return max(char.height for char in self.chars)


@dataclass(frozen=True)
class Geometry:
    """The visible part of a page (its crop box) and its rotation, clockwise."""

    left: float
    bottom: float
    right: float
    top: float
    rotation: int

    @classmethod
    def of(cls, page: pypdfium2.PdfPage) -> "Geometry":
        left, bottom, right, top = page.get_cropbox()
        return cls(left, bottom, right, top, page.get_rotation() % 360)

    def turned(self, degrees: int) -> "Geometry":
        """The page turned further, clockwise."""
        return dataclasses.replace(self, rotation=(self.rotation + degrees) % 360)

    @property
    def size(self) -> tuple[float, float]:
        """Width and height of the page as shown."""
        width, height = self.right - self.left, self.top - self.bottom
        return (height, width) if self.rotation in (90, 270) else (width, height)

    def turn(
        self, left: float, bottom: float, right: float, top: float
    ) -> tuple[float, float, float, float]:
        """A box of the unrotated page on the page as shown."""
        match self.rotation:
            case 90:
                return (
                    bottom - self.bottom,
                    self.right - right,
                    top - self.bottom,
                    self.right - left,
                )
            case 180:
                return self.right - right, self.top - top, self.right - left, self.top - bottom
            case 270:
                return self.top - top, left - self.left, self.top - bottom, right - self.left
            case _:
                return left - self.left, bottom - self.bottom, right - self.left, top - self.bottom

    def fraction_box(self, left: float, bottom: float, right: float, top: float) -> Box | None:
        """A box of the unrotated page (in points) on the page as shown, in fractions of it
        from its top left; None on a page without area."""
        width, height = self.size
        if width <= 0 or height <= 0:
            return None
        return Box.clamped(*page_fractions(*self.turn(left, bottom, right, top), (width, height)))


def page_fractions(
    left: float, bottom: float, right: float, top: float, size: tuple[float, float]
) -> tuple[float, float, float, float]:
    """A box on the page as shown (points from its bottom left) in fractions of the page `size`
    from its top left: left, top, right, bottom, each cut to 0 to 1."""
    width, height = size
    return (
        _unit(left / width),
        _unit((height - top) / height),
        _unit(right / width),
        _unit((height - bottom) / height),
    )


def _unit(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def reading_turn(textpage: pypdfium2.PdfTextPage, geometry: Geometry) -> int:
    """How far to turn the page as shown, clockwise, for most of its text to be upright: 0, or
    90, 180 or 270 if more than half of its visible characters run that way."""
    directions: Counter[int] = Counter()
    for index in range(textpage.count_chars()):
        if pdfium_c.FPDFText_IsGenerated(textpage, index) == 1:
            continue
        code = pdfium_c.FPDFText_GetUnicode(textpage, index)
        if code == 0 or chr(code).isspace():
            continue
        directions[round(_angle(textpage, index, geometry) / 90) % 4] += 1
    if not directions:
        return 0
    direction, count = directions.most_common(1)[0]
    return (360 - 90 * direction) % 360 if count * 2 > sum(directions.values()) else 0


def _angle(textpage: pypdfium2.PdfTextPage, index: int, geometry: Geometry) -> float:
    """The angle of a character on the page as shown, clockwise in degrees."""
    return (math.degrees(pdfium_c.FPDFText_GetCharAngle(textpage, index)) + geometry.rotation) % 360


def page_chars(
    textpage: pypdfium2.PdfTextPage, geometry: Geometry
) -> tuple[list[Char], list[Angled]]:
    """The visible characters of a page without spaces: the upright ones and those at an
    angle, on the page as shown."""
    upright: list[Char] = []
    angled: list[Angled] = []
    flags = ctypes.c_int()
    for index in range(textpage.count_chars()):
        if pdfium_c.FPDFText_IsGenerated(textpage, index) == 1:
            continue
        code = pdfium_c.FPDFText_GetUnicode(textpage, index)
        if code == 0:
            continue
        text = REPLACEMENT if 0xD800 <= code <= 0xDFFF or code > 0x10FFFF else chr(code)
        if text.isspace():
            continue
        box = textpage.get_charbox(index, loose=True)
        left, bottom, right, top = geometry.turn(*box)
        if right <= left or top <= bottom:
            continue
        size = pdfium_c.FPDFText_GetFontInfo(textpage, index, None, 0, ctypes.byref(flags))
        name = ctypes.create_string_buffer(max(size, 1))
        pdfium_c.FPDFText_GetFontInfo(textpage, index, name, size, ctypes.byref(flags))
        char = Char(
            text=text,
            font=(name.value.decode("utf-8", "replace"), round(top - bottom, 1)),
            flagged=bool(flags.value & _FIXED_PITCH_FLAG),
            left=left,
            bottom=bottom,
            right=right,
            top=top,
        )
        angle = _angle(textpage, index, geometry)
        if min(angle, 360 - angle) < UPRIGHT:
            upright.append(char)
        else:
            angled.append(Angled(char, angle))
    return upright, angled


def lines_of(chars: list[Char], advances: dict[Font, float]) -> list[Line]:
    """The lines of a page, from the top: characters whose middles lie within half a character
    height of the first one's. `advances`: the fixed-pitch fonts and their advance, for the
    line's own advance (else None)."""
    rows: list[list[Char]] = []
    for char in sorted(chars, key=lambda char: -char.middle):
        first = rows[-1][0] if rows else None
        spread = min(first.height, char.height) * SAME_LINE if first is not None else 0.0
        if first is not None and first.middle - char.middle <= spread:
            rows[-1].append(char)
        else:
            rows.append([char])
    lines = []
    for row in rows:
        # Fonts of one advance (regular and bold, say) set one grid.
        found = [advances.get(char.font) for char in row]
        known = [advance for advance in found if advance is not None]
        alike = bool(known) and len(known) == len(found) and all(same(known[0], x) for x in known)
        lines.append(Line(sorted(row, key=lambda char: char.left), known[0] if alike else None))
    return lines


def same(a: float, b: float) -> bool:
    return abs(a - b) <= SAME * max(a, b)
