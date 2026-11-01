"""The type families of the documents: sans, serif and mono as the PDF standard fonts Helvetica,
Times and Courier, drawn on paper with URW's fonts of the same metrics (the fonts Ghostscript
brings, in the devcontainer). `hand` is for handwriting on paper only."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from PIL import ImageFont

URW = Path("/usr/share/fonts/opentype/urw-base35")

_PDF = {
    "sans": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "serif": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "mono": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
    # Handwriting stands only on paper; a PDF falls back to italics.
    "hand": ("Times-Italic",) * 4,
}
_FILES = {
    "sans": ("NimbusSans-Regular", "NimbusSans-Bold", "NimbusSans-Italic", "NimbusSans-BoldItalic"),
    "serif": (
        "NimbusRoman-Regular",
        "NimbusRoman-Bold",
        "NimbusRoman-Italic",
        "NimbusRoman-BoldItalic",
    ),
    "mono": (
        "NimbusMonoPS-Regular",
        "NimbusMonoPS-Bold",
        "NimbusMonoPS-Italic",
        "NimbusMonoPS-BoldItalic",
    ),
    "hand": ("Z003-MediumItalic",) * 4,
}

MM_PER_PT = 25.4 / 72


@dataclass(frozen=True)
class Font:
    family: str = "sans"
    bold: bool = False
    italic: bool = False

    @property
    def _index(self) -> int:
        return int(self.bold) + 2 * int(self.italic)

    @property
    def pdf_name(self) -> str:
        """The standard font of a PDF with these metrics."""
        return _PDF[self.family][self._index]

    @property
    def path(self) -> Path:
        return URW / f"{_FILES[self.family][self._index]}.otf"

    def bolder(self) -> "Font":
        return Font(self.family, True, self.italic)


SANS = Font("sans")
SANS_BOLD = Font("sans", bold=True)
SERIF = Font("serif")
MONO = Font("mono")
HAND = Font("hand")


@cache
def truetype(font: Font, px: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font.path), round(px, 1), layout_engine=ImageFont.Layout.BASIC)


def width(text: str, font: Font, size: float) -> float:
    """The width of `text` in `font` at `size` points, in millimetres."""
    return truetype(font, 1000).getlength(text) / 1000 * size * MM_PER_PT


def wrap(text: str, font: Font, size: float, room: float) -> list[str]:
    """`text` broken into lines no wider than `room` millimetres, at spaces; a word wider than
    the room stands alone."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if line and width(candidate, font, size) > room:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines
