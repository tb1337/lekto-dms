"""Places on a page: boxes stay on the page, and both go to JSON and back."""

import pytest

from lekto.core.domain.classification import FieldCheck
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.locations import Box, Location, locations_from_json, locations_to_json
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
