"""Where a passage stands on the pages of a document: page and boxes, for showing the quote
of a field on the page it came from.

Boxes are fractions of the page as it is shown (its rotation applied), measured from the top
left corner, so they fit any rendering of the page whatever its size.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.json_value import JsonObject, JsonValue, as_int, as_number

_DIGITS = 4


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


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
