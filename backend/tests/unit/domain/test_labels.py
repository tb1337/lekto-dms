from collections.abc import Callable
from decimal import Decimal

import pytest

from lekto.core.domain.evidence import DocumentText
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.labels import (
    LABEL_LINES,
    LabelCheck,
    LabelOutcome,
    LaidWord,
    check_label,
    grid_layout,
    label_places,
    layout_words,
)
from lekto.core.domain.locations import Box, Location


def pages_of(text: str) -> dict[int, tuple[LaidWord, ...]]:
    pages = layout_words(grid_layout(text))
    assert pages is not None
    return pages


def amount(value: str) -> Callable[[DocumentText], bool]:
    return lambda text: text.has_amount(Decimal(value))


def outcome(text: str, label: str | None, value: str = "3980.00") -> LabelOutcome:
    return check_label(label, pages_of(text), (), amount(value)).outcome


def test_the_value_on_the_label_s_line_to_its_right_stands_by_it() -> None:
    text = "Grundgehalt          3.400,00 €\nGesamtbrutto                       3.980,00 €"
    assert outcome(text, "Gesamtbrutto") is LabelOutcome.BESIDE
    # The value of another line, or left of its label, is apart.
    assert outcome(text, "Grundgehalt") is LabelOutcome.APART
    assert outcome("3.980,00 €     Gesamtbrutto", "Gesamtbrutto") is LabelOutcome.APART


@pytest.mark.parametrize(
    ("lines", "beside"), [(1, True), (2, True), (LABEL_LINES, True), (4, False)]
)
def test_a_value_below_its_label_in_its_column_stands_by_it_within_three_lines(
    lines: int, beside: bool
) -> None:
    rows = ["Gesamtbrutto", *(f"Zeile {index}" for index in range(1, lines)), "  3.980,00 €"]
    expected = LabelOutcome.BESIDE if beside else LabelOutcome.APART
    assert outcome("\n".join(rows), "Gesamtbrutto") is expected


def test_the_line_is_measured_on_the_page() -> None:
    """Double spaced, three lines below are six rows of the grid."""
    text = "\n\n".join(["Gesamtbrutto", "Zeile 1", "Zeile 2", "3.980,00 €", "Zeile 4", "Ende"])
    assert outcome(text, "Gesamtbrutto") is LabelOutcome.BESIDE


def test_a_value_in_another_column_is_apart() -> None:
    text = (
        "Gesamtbrutto                          Betrag\nGrundgehalt                       3.980,00 €"
    )
    assert outcome(text, "Gesamtbrutto") is LabelOutcome.APART
    # The column of a label is where the value overlaps it or starts within a few characters.
    assert outcome(text, "Betrag") is LabelOutcome.BESIDE
    assert outcome("Nr\n   3.980,00 €", "Nr") is LabelOutcome.BESIDE
    assert outcome("Nr\n      3.980,00 €", "Nr") is LabelOutcome.APART


def test_any_place_of_the_label_with_the_value_beside_it_passes() -> None:
    text = "\n".join(
        ["Gesamtbrutto des Jahres", "", "", "", "", "", "Gesamtbrutto      3.980,00 €"]
    )
    pages = pages_of(text)
    assert len(label_places(pages[1], "Gesamtbrutto")) == 2
    assert outcome(text, "Gesamtbrutto") is LabelOutcome.BESIDE
    assert outcome(text.replace("Gesamtbrutto      ", "Brutto            "), "Gesamtbrutto") is (
        LabelOutcome.APART
    )


def test_the_label_is_matched_as_quotes_are() -> None:
    text = "GESAMT   BRUTTO      3.980,00 €"
    # Case and spacing evened out, then on letters and digits alone.
    assert outcome(text, "gesamt brutto") is LabelOutcome.BESIDE
    assert outcome(text, "Gesamt-Brutto:") is LabelOutcome.BESIDE
    places = label_places(pages_of(text)[1], "gesamt brutto")
    assert [[word.text for word in place] for place in places] == [["GESAMT", "BRUTTO"]]
    # Too short to be matched loosely, and not at all.
    assert label_places(pages_of("A.B 12,00 €")[1], "AB") == []
    assert outcome(text, "Nettolohn") is LabelOutcome.LABEL_MISSING
    # An entity of an older parse's quote, as the locator reads it.
    assert outcome("Brutto & Zulage   3.980,00 €", "Brutto &amp; Zulage") is LabelOutcome.BESIDE


def test_the_label_is_matched_as_whole_words() -> None:
    text = "Steuerbrutto      3.400,00 €\nGesamtbrutto      3.980,00 €"
    assert outcome(text, "Brutto", value="3400.00") is LabelOutcome.LABEL_MISSING
    assert outcome(text, "Gesamtbrutto", value="3400.00") is LabelOutcome.APART
    # On letters and digits alone, the marks around a word do not stand in the way.
    assert outcome("**Gesamtbrutto:**    3.980,00 €", "Gesamtbrutto") is LabelOutcome.BESIDE


def test_a_label_over_two_lines_is_measured_where_it_ends() -> None:
    text = "Summe\nbrutto       3.980,00 €\n\n\n\n\nZeile"
    assert outcome(text, "Summe brutto") is LabelOutcome.BESIDE
    # Words of two places in reading order make no box across them: under the first word, not
    # under the last one, is apart.
    across = "Summe\n               brutto\n  3.980,00 €"
    assert outcome(across, "Summe brutto") is LabelOutcome.APART


def test_a_value_in_the_label_s_own_word_stands_by_it() -> None:
    assert outcome("Brutto:3.980,00", "Brutto:") is LabelOutcome.BESIDE


def test_without_a_label_or_without_words_or_value_nothing_is_checked() -> None:
    text = "Gesamtbrutto      3.980,00 €"
    assert check_label(None, pages_of(text), (), amount("3980.00")) == LabelCheck(
        None, LabelOutcome.NO_LABEL
    )
    assert check_label("Gesamtbrutto", {}, (), amount("3980.00")) == LabelCheck(
        "Gesamtbrutto", LabelOutcome.UNKNOWN
    )
    assert check_label("Gesamtbrutto", {1: ()}, (), amount("3980.00")).outcome is (
        LabelOutcome.UNKNOWN
    )
    assert outcome(text, "Gesamtbrutto", value="4000.00") is LabelOutcome.UNKNOWN
    assert check_label("Gesamtbrutto", pages_of(text), (), None).outcome is LabelOutcome.UNKNOWN


def test_a_value_standing_twice_is_found_by_its_quote_s_place() -> None:
    text = "Gehalt            3.980,00 €\n\n\n\n\n\nGesamtbrutto      3.980,00 €"
    pages = pages_of(text)
    assert outcome(text, "Gesamtbrutto") is LabelOutcome.UNKNOWN  # where is not known
    lines = len(text.split("\n"))
    first = Location(1, (Box.clamped(0, 0.15 / 60, 28 / 80, 0.85 / 60),))
    last = Location(1, (Box.clamped(0, (lines - 0.85) / 60, 28 / 80, (lines - 0.15) / 60),))
    assert check_label("Gesamtbrutto", pages, (first,), amount("3980.00")).outcome is (
        LabelOutcome.APART
    )
    assert check_label("Gesamtbrutto", pages, (first, last), amount("3980.00")).outcome is (
        LabelOutcome.BESIDE
    )


def test_the_words_of_the_parsed_text() -> None:
    data: JsonValue = {
        "parser": "layout",
        "pages": [
            {
                "number": 1,
                "lines": [
                    {
                        "text": "Gesamt 1,00",
                        "words": [
                            {"text": "Gesamt", "box": [0.1, 0.1, 0.2, 0.12]},
                            {"text": "1,00", "box": [0.5, 0.1, 0.55, 0.12]},
                            {"text": "flat", "box": [0.6, 0.1, 0.6, 0.12]},
                            {"text": "", "box": [0.6, 0.1, 0.7, 0.12]},
                            {"text": "boxless"},
                        ],
                    }
                ],
            },
            {"number": "two"},
        ],
    }
    pages = layout_words(data)
    assert pages is not None and list(pages) == [1]
    assert [word.text for word in pages[1]] == ["Gesamt", "1,00"]
    assert pages[1][0].box == Box(0.1, 0.1, 0.1, 0.02)
    # Docling's structure, before 0.2, and the fake parser's.
    assert layout_words({"text": "Fake text"}) is None
    assert layout_words([]) is None


def test_the_grid_keeps_lines_columns_and_pages() -> None:
    pages = pages_of("Betrag\n    12,00 €\f\nSeite 2")
    assert sorted(pages) == [1, 2]
    label, value, currency = pages[1]
    assert (label.box.x, value.box.x) == (0, 4 / 80)
    assert value.box.y > label.box.y + label.box.height
    assert currency.text == "€"
    assert [word.text for word in pages[2]] == ["Seite", "2"]


def test_a_label_check_as_the_log_keeps_it() -> None:
    check = LabelCheck("Gesamtbrutto", LabelOutcome.APART)
    assert check.to_json() == {"text": "Gesamtbrutto", "outcome": "apart"}
    assert LabelCheck.from_json(check.to_json()) == check
    assert LabelCheck.from_json({"text": None, "outcome": "no_label"}) == LabelCheck(
        None, LabelOutcome.NO_LABEL
    )
    assert LabelCheck.from_json({"text": "x", "outcome": "nearby"}) is None
    assert LabelCheck.from_json(None) is None
