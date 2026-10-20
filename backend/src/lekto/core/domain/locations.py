"""Where a passage stands on the pages of a document: page and boxes, for showing the quote
of a field on the page it came from.

Boxes are fractions of the page as it is shown (its rotation applied), measured from the top
left corner, so they fit any rendering of the page whatever its size.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.json_value import JsonObject, JsonValue, as_int, as_number

_DIGITS = 4

SAME_LINE = 0.5
"""Characters or boxes whose middles lie within this share of a height of each other stand in
one line."""


@dataclass(frozen=True)
class Box:
    """A rectangle: `x`, `y` of its top left corner, `width` and `height`, each from 0 to 1."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "width", "height"):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValidationError(f"a box's {name} must be between 0 and 1, got {value}")
        if self.x + self.width > 1.0001 or self.y + self.height > 1.0001:
            raise ValidationError("a box must lie on the page")

    @classmethod
    def clamped(cls, left: float, top: float, right: float, bottom: float) -> "Box":
        """The box between two corners, cut to the page and rounded."""
        left, right = sorted((_clamp(left), _clamp(right)))
        top, bottom = sorted((_clamp(top), _clamp(bottom)))
        x, y = round(left, _DIGITS), round(top, _DIGITS)
        width = round(min(right - left, 1 - x), _DIGITS)
        height = round(min(bottom - top, 1 - y), _DIGITS)
        return cls(x, y, width, height)

    def to_json(self) -> JsonObject:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_json(cls, data: JsonValue) -> "Box":
        if not isinstance(data, dict):
            raise ValidationError(f"invalid box {data!r}")
        values = [data.get(name) for name in ("x", "y", "width", "height")]
        numbers = [number for value in values if (number := as_number(value)) is not None]
        if len(numbers) != 4:
            raise ValidationError(f"invalid box {data!r}")
        return cls(*numbers)


@dataclass(frozen=True)
class Location:
    """One place of a passage: its page (from 1) and a box per line it covers."""

    page: int
    boxes: tuple[Box, ...]

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValidationError("pages are numbered from 1")

    def to_json(self) -> JsonObject:
        return {"page": self.page, "boxes": [box.to_json() for box in self.boxes]}

    @classmethod
    def from_json(cls, data: JsonValue) -> "Location":
        if not isinstance(data, dict):
            raise ValidationError(f"invalid location {data!r}")
        page, boxes = as_int(data.get("page")), data.get("boxes")
        if page is None or not isinstance(boxes, list):
            raise ValidationError(f"invalid location {data!r}")
        return cls(page, tuple(Box.from_json(box) for box in boxes))


def locations_to_json(locations: Sequence[Location]) -> list[JsonValue]:
    return [location.to_json() for location in locations]


def locations_from_json(data: JsonValue) -> tuple[Location, ...]:
    """Locations of stored JSON; none if there are none (entries from before they existed)."""
    if data is None:
        return ()
    if not isinstance(data, list):
        raise ValidationError(f"invalid locations {data!r}")
    return tuple(Location.from_json(item) for item in data)


def line_boxes(boxes: Sequence[Box]) -> tuple[Box, ...]:
    """One box per line of `boxes` (of words or characters, an OCR text layer places every word
    on its own): boxes whose middles lie within `SAME_LINE` of a height of each other form a
    line (top to bottom); in a line, boxes that stand close are joined (left to right), a wide
    gap (another column) keeps them apart."""
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


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
