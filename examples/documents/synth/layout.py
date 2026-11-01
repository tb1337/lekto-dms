"""What a page shows, in millimetres from its top left corner: text on its baseline, lines,
shapes and pictures (codes). The vector PDF and the raster image draw the same page."""

from dataclasses import dataclass, field

from PIL import Image

from synth.fonts import SANS, Font

type RGB = tuple[int, int, int]
type Point = tuple[float, float]

BLACK: RGB = (0, 0, 0)
WHITE: RGB = (255, 255, 255)
GREY: RGB = (110, 110, 110)
A4 = (210.0, 297.0)


@dataclass(frozen=True)
class Text:
    x: float
    y: float  # the baseline
    text: str
    font: Font
    size: float  # points
    align: str = "left"  # left, right or center
    color: RGB = BLACK


@dataclass(frozen=True)
class Line:
    """An open line through `points`, `width` in points."""

    points: tuple[Point, ...]
    width: float = 0.5
    color: RGB = BLACK


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float
    fill: RGB | None = None
    stroke: RGB | None = None
    width: float = 0.5


@dataclass(frozen=True)
class Ellipse:
    """The ellipse in the box (`x`, `y`, `w`, `h`)."""

    x: float
    y: float
    w: float
    h: float
    fill: RGB | None = None
    stroke: RGB | None = None
    width: float = 0.5


@dataclass(frozen=True)
class Polygon:
    points: tuple[Point, ...]
    fill: RGB | None = None
    stroke: RGB | None = None
    width: float = 0.5


@dataclass(frozen=True, eq=False)
class Picture:
    """A raster picture (a code: mode `1`) in the box (`x`, `y`, `w`, `h`)."""

    x: float
    y: float
    w: float
    h: float
    image: Image.Image


type Item = Text | Line | Rect | Ellipse | Polygon | Picture


@dataclass
class Page:
    width: float = A4[0]
    height: float = A4[1]
    items: list[Item] = field(default_factory=list)

    def text(
        self,
        x: float,
        y: float,
        text: str,
        font: Font = SANS,
        size: float = 10,
        align: str = "left",
        color: RGB = BLACK,
    ) -> None:
        if text:
            self.items.append(Text(x, y, text, font, size, align, color))

    def line(self, *points: Point, width: float = 0.5, color: RGB = BLACK) -> None:
        self.items.append(Line(tuple(points), width, color))

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: RGB | None = None,
        stroke: RGB | None = None,
        width: float = 0.5,
    ) -> None:
        self.items.append(Rect(x, y, w, h, fill, stroke, width))

    def ellipse(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: RGB | None = None,
        stroke: RGB | None = None,
        width: float = 0.5,
    ) -> None:
        self.items.append(Ellipse(x, y, w, h, fill, stroke, width))

    def polygon(
        self,
        *points: Point,
        fill: RGB | None = None,
        stroke: RGB | None = None,
        width: float = 0.5,
    ) -> None:
        self.items.append(Polygon(tuple(points), fill, stroke, width))

    def picture(self, x: float, y: float, w: float, h: float, image: Image.Image) -> None:
        self.items.append(Picture(x, y, w, h, image))
