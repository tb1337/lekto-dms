"""Places on a page: boxes stay on the page, and both go to JSON and back."""

import pytest

from lekto.core.domain.classification import FieldCheck
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.locations import (
    Box,
    Location,
    line_boxes,
    locations_from_json,
    locations_to_json,
)
from lekto.core.domain.pipeline import Outcome


def test_boxes_lie_on_the_page() -> None:
    with pytest.raises(ValidationError):
        Box(0.5, 0.5, 0.6, 0.1)
    with pytest.raises(ValidationError):
        Box(-0.1, 0, 0.1, 0.1)


def test_a_box_between_corners_is_cut_to_the_page() -> None:
    assert Box.clamped(0.9, 0.2, 1.2, -0.1) == Box(0.9, 0.0, 0.1, 0.2)
    assert Box.clamped(0.123456, 0.5, 0.2, 0.6) == Box(0.1235, 0.5, 0.0765, 0.1)


def test_locations_go_to_json_and_back() -> None:
    places = (Location(2, (Box(0.1, 0.2, 0.3, 0.02), Box(0.1, 0.22, 0.1, 0.02))),)
    assert locations_from_json(locations_to_json(places)) == places
    assert locations_from_json(None) == ()
    with pytest.raises(ValidationError):
        locations_from_json([{"page": 0, "boxes": []}])
    with pytest.raises(ValidationError):
        locations_from_json([{"page": 1, "boxes": [{"x": 0.1}]}])


def test_a_check_keeps_its_quote_and_places() -> None:
    check = FieldCheck(
        field="document_date",
        outcome=Outcome.OK,
        confidence=1,
        evidence="31.03.2026",
        value="2026-03-31",
        quote_shows_value=True,
        locations=(Location(1, (Box(0.5, 0.1, 0.2, 0.02),)),),
    )
    assert FieldCheck.from_json(check.to_json()) == check
    # Checks from before: neither key.
    older = check.to_json()
    del older["quote_shows_value"], older["locations"]
    restored = FieldCheck.from_json(older)
    assert (restored.quote_shows_value, restored.locations) == (None, ())


def test_the_words_of_a_line_make_one_box() -> None:
    words = [Box(0.1, 0.5, 0.1, 0.02), Box(0.21, 0.502, 0.05, 0.018), Box(0.27, 0.5, 0.08, 0.02)]
    below = Box(0.1, 0.55, 0.2, 0.02)
    far = Box(0.9, 0.5, 0.05, 0.02)  # in another column
    assert line_boxes([*reversed(words), below, far]) == (
        Box(0.1, 0.5, 0.25, 0.02),
        far,
        below,
    )
    # Tops on either side of a rounding step, lines closer than 1 % of the page: still apart.
    tight = [
        Box(0.1, 0.3049, 0.1, 0.008),
        Box(0.21, 0.3051, 0.1, 0.008),
        Box(0.1, 0.3135, 0.2, 0.008),
    ]
    assert line_boxes(tight) == (Box(0.1, 0.3049, 0.21, 0.0082), Box(0.1, 0.3135, 0.2, 0.008))
