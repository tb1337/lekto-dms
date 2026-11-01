"""Names for IDs: an unknown name is an error that suggests similar ones."""

from uuid import uuid4

import pytest

from lekto.adapters.inbound.mcp.names import find, similar_names
from lekto.core.domain.errors import ValidationError

CONTACTS = ["Stadtwerke Musterstadt", "Stadtsparkasse", "Finanzamt Nord", "AOK", "Allianz"]


def test_a_name_matches_regardless_of_case() -> None:
    names = {uuid4(): name for name in CONTACTS}
    found = find("contact", "finanzamt nord", names)
    assert names[found] == "Finanzamt Nord"


@pytest.mark.parametrize(
    ("asked", "suggested"),
    [
        ("Stadtwerk", ["Stadtwerke Musterstadt", "Stadtsparkasse"]),  # stands in it, alike
        ("Stadtwerke Musterstadt GmbH", ["Stadtwerke Musterstadt"]),  # it stands in the one asked
        ("Finanzamt Süd", ["Finanzamt Nord"]),  # spelt alike
        ("Alianz", ["Allianz"]),
        ("Bundesagentur", []),
    ],
)
def test_similar_names(asked: str, suggested: list[str]) -> None:
    assert similar_names(asked, CONTACTS) == suggested


def test_names_under_three_characters_are_not_suggested_for_standing_in_another() -> None:
    assert similar_names("Verlag AG", ["AG"]) == []
    assert similar_names("AOK Nordwest", ["AOK"]) == ["AOK"]


def test_an_unknown_name_suggests_similar_ones() -> None:
    names = {uuid4(): name for name in CONTACTS}
    with pytest.raises(ValidationError) as raised:
        find("contact", "Stadtwerk", names)
    assert str(raised.value) == (
        "no contact named 'Stadtwerk'; similar: Stadtwerke Musterstadt, Stadtsparkasse"
    )
    with pytest.raises(ValidationError) as raised:
        find("contact", "Bundesagentur", names)
    assert str(raised.value) == "no contact named 'Bundesagentur'"
