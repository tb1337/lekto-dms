"""Where a stretch of the text stands on the pages: the words of the parsed text found in it in
their order, a box per line of those a stretch touches."""

from lekto.core.domain.labels import LaidWord, grid_layout, layout_words
from lekto.core.domain.locations import Box, Location
from lekto.core.domain.text_places import TextPlaces

TEXT = """\
Stadtwerke Süd GmbH                       Kundennummer 2004-7718
IBAN DE89 3704 0044 0532 0130 00
Betreff: Abschlag
\f
Seite 2
Lastschrift von DE02120300000000202051"""


def places_of(text: str) -> TextPlaces:
    pages = layout_words(grid_layout(text))
    assert pages is not None
    return TextPlaces(text, pages)


def at(text: str, part: str) -> tuple[int, int]:
    start = text.index(part)
    return start, start + len(part)


def cells(row: int, first: int, last: int, *, rows: int = 60, columns: int = 80) -> Box:
    """The box of characters `first` to `last` (exclusive) of `row` on `grid_layout`'s grid,
    its corners rounded as there."""
    corners = (first / columns, (row + 0.15) / rows, last / columns, (row + 0.85) / rows)
    return Box.clamped(*(round(corner, 4) for corner in corners))


def test_a_stretch_stands_where_its_words_stand_a_box_per_line() -> None:
    places = places_of(TEXT)
    (iban,) = places.locations(*at(TEXT, "DE89 3704 0044 0532 0130 00"))
    assert iban.page == 1
    (box,) = iban.boxes
    assert box == cells(1, 5, 32)
    # Over two lines: a box for each.
    (both,) = places.locations(*at(TEXT, "0130 00\nBetreff"))
    assert [round(box.y * 60) for box in both.boxes] == [1, 2]


def test_the_words_of_a_later_page_are_found_on_it() -> None:
    places = places_of(TEXT)
    assert places.locations(*at(TEXT, "DE02120300000000202051")) == (
        Location(2, (cells(1, 16, 38),)),
    )
    # Across the break: on both pages.
    span = at(TEXT, "Abschlag\n\f\nSeite")
    assert [location.page for location in places.locations(*span)] == [1, 2]


def test_a_stretch_within_a_word_stands_where_the_word_stands() -> None:
    places = places_of(TEXT)
    start, _ = at(TEXT, "2004-7718")
    (location,) = places.locations(start + 5, start + 9)
    assert location.boxes == (cells(0, 55, 64),)


def test_columns_stay_apart_on_their_line() -> None:
    places = places_of(TEXT)
    start, _ = at(TEXT, "GmbH")
    _, end = at(TEXT, "Kundennummer")
    (location,) = places.locations(start, end)
    assert location.boxes == (cells(0, 15, 19), cells(0, 42, 54))


def test_a_word_the_text_spells_otherwise_does_not_put_the_rest_out_of_step() -> None:
    text = "Rechnung 4711 vom 12.03.2026\nBetrag 84,20 EUR"
    pages = layout_words(grid_layout(text))
    assert pages is not None
    words = list(pages[1])
    # The structure spells a hyphen where the text has none, and has a word the text lacks.
    words[1] = LaidWord("47-11", words[1].box)
    words.insert(3, LaidWord("Seite", Box(0.9, 0.9, 0.05, 0.01)))
    places = TextPlaces(text, {1: tuple(words)})
    assert places.locations(*at(text, "4711")) == ()
    (location,) = places.locations(*at(text, "84,20"))
    assert location.boxes == (words[-2].box,)
    assert places.locations(len(text), len(text)) == ()


def test_without_words_nothing_has_a_place() -> None:
    assert TextPlaces(TEXT, {}).locations(0, len(TEXT)) == ()
