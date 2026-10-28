import json
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest

from lekto.adapters.outbound.ocrmypdf.hocr import hocr_words
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.evidence import DocumentText
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.locations import Box, Location
from lekto.core.domain.reading import (
    READING_VERSION,
    SURROUNDING,
    OcrOutput,
    PageReading,
    PageWords,
    ReadWord,
    Surroundings,
    beside_leaders,
    content_words,
    gap,
    is_noise,
    read_from_dots,
    reading_from_json,
    reading_to_json,
    readings_from_json,
    readings_to_json,
    surroundings,
    value_on_pages,
    value_words,
    words_at,
)
from tests.scans import BAD_TABLE, PAYSLIP, hocr


@pytest.mark.parametrize(
    ("words", "unsure", "poor"),
    [
        (224, 23, True),  # a broken scan: 10 % unsure
        (409, 8, False),  # a good one: 2 %
        (100, 8, True),  # just at the threshold
        (9, 9, False),  # too few words to tell: a blank back side, a page number
        (0, 0, False),
    ],
)
def test_a_page_is_poorly_read_from_the_threshold_on(words: int, unsure: int, poor: bool) -> None:
    assert PageReading(page=1, words=words, unsure=unsure).poor(0.08) is poor


def test_a_reading_is_consistent() -> None:
    with pytest.raises(ValidationError):
        PageReading(page=0, words=1, unsure=0)
    with pytest.raises(ValidationError):
        PageReading(page=1, words=1, unsure=2)


def test_readings_as_the_log_keeps_them() -> None:
    readings = (PageReading(page=1, words=224, unsure=23), PageReading(page=3, words=5, unsure=0))
    assert readings_from_json(readings_to_json(readings)) == readings
    # Entries from before readings, or with something else in them.
    assert readings_from_json(None) == ()
    assert readings_from_json([{"page": 1}, "x", {"page": 0, "words": 1, "unsure": 0}]) == ()


def test_the_ocr_output_round_trip_and_what_an_old_entry_lacks() -> None:
    output = OcrOutput(
        archive="documents/x/archive.pdf",
        pages=2,
        pdfa=True,
        readings=(PageReading(page=1, words=10, unsure=1),),
        vision={"model": "vlm", "endpoint": "vlm.lan", "prompt": "p", "calls": 1},
        tokens=({"prompt": 3, "completion": 1, "usage": {}},),
        rgb=True,
    )
    assert output.to_json()["rgb"] is True
    assert OcrOutput.from_json(output.to_json()) == output
    plain = OcrOutput(archive="documents/x/archive.pdf", pages=1, pdfa=False)
    assert plain.to_json() == {"archive": "documents/x/archive.pdf", "pages": 1, "pdfa": False}
    assert OcrOutput.from_json({}) == OcrOutput(archive="", pages=0, pdfa=False)


def word(text: str, confidence: int = 93, size: float | None = 0.012) -> ReadWord:
    return ReadWord(text, confidence, None, size)


@pytest.mark.parametrize(
    ("text", "noise"),
    [
        ("Gesamtbetrag", False),
        ("2.235,81", False),
        ("24.06.2022", False),
        ("12", False),  # a number of two digits
        ("5%", False),
        ("«oso:", False),  # a leader read as letters cannot be told from a word
        ("cae", False),
        ("..........", True),  # a dot leader
        ("Datum..........", True),  # a label with its leader: the dots drag the label down
        ("___", True),
        ("———", True),
        ("·", True),
        ("|", True),
        ("gy", True),  # stray marks of one or two characters
        ("TI", True),
        ("j", True),
        ("€", True),
        ("(—)", True),  # under half letters or digits
        (" ", True),
    ],
)
def test_noise_is_neither_content_nor_unsure(text: str, noise: bool) -> None:
    assert is_noise(word(text)) is noise


def test_dots_and_rules_read_as_letters_are_noise_by_their_low_box() -> None:
    """Their box stays as low as the dots; a word of small letters has the x-height."""
    assert is_noise(ReadWord("see", 47, Box(0.3, 0.5, 0.04, 0.002), 0.012))
    assert is_noise(ReadWord("EEE", 30, Box(0.3, 0.5, 0.2, 0.004), 0.012))
    assert not is_noise(ReadWord("nur", 96, Box(0.3, 0.5, 0.04, 0.007), 0.012))
    assert not is_noise(ReadWord("see", 47, Box(0.3, 0.5, 0.04, 0.002)))  # no line size


@pytest.mark.parametrize(
    ("text", "confidence", "leader"),
    [
        ("11111", 0, True),  # a leader read as ones
        ("02.00.0000.", 0, True),  # as seen on a speckled scan
        ("1111.1111", 41, True),
        ("0000000", 30, True),
        ("11111", 93, False),  # read sure: a value
        ("1111", 0, False),  # too short
        ("0000", 35, False),  # a masked number
        ("01.01.2020", 20, False),  # an unsure date: three digits
        ("1.000,00", 20, False),  # an unsure amount: three zeros in a row
        ("100.000,00", 20, False),
        ("12345", 10, False),  # a misread number
        ("Il1111", 10, False),  # letters: not four in five dot-like
    ],
)
def test_a_dot_leader_read_as_digits_is_noise(text: str, confidence: int, leader: bool) -> None:
    """Tesseract reads the dots of a speckled leader as ones and zeros, unsure."""
    read = word(text, confidence)
    assert read_from_dots(read) is leader
    assert is_noise(read) is leader


def test_a_label_beside_a_leader_read_as_digits_is_neither_content_nor_unsure() -> None:
    """The specks make the box of the dots high: the digits alone tell the leader."""
    words = [
        placed("Krankenkasse", 0.1, confidence=0),
        placed("02.00.0000.", 0.205, confidence=0),
        placed("Gesundkasse", 0.31),
    ]
    assert beside_leaders(words) == {0, 2}
    assert content_words(words) == []


def test_small_print_is_noise_against_the_page_s_typical_line() -> None:
    body = [word(f"Wort{n}") for n in range(10)]
    letterhead = [word("Lohnbüro", 41, 0.007), word("Musterstadt", 70, 0.007)]
    footnote = word("Fußnote", 50, 0.009)  # 8 pt beside 11 pt stays content
    heading = word("Lohnabrechnung", 90, 0.03)
    content = content_words([*letterhead, *body, footnote, heading])
    assert content == [*body, footnote, heading]
    # Without sizes, nothing is small.
    assert content_words([word("Lohnbüro", 41, None)]) == [word("Lohnbüro", 41, None)]


def test_a_page_reading_counts_content_and_decides_by_it() -> None:
    noise = [word("..........", 20), word("gy", 30), word("en", 25)]
    words = [word(f"Wort{n}") for n in range(18)] + [word("412,33", 31), *noise]
    reading = PageReading.of(2, words)
    assert reading == PageReading(2, words=22, unsure=4, content=19, content_unsure=1)
    assert reading.share == pytest.approx(1 / 19)  # 5 % of the content
    assert not reading.poor(0.08)
    assert reading.counted == (19, 1)
    # Read before content was counted: all words, as before.
    old = PageReading(2, words=22, unsure=4)
    assert old.poor(0.08)
    assert old.describe().text == "page 2 was poorly read (18% of its words unsure)"
    broken = PageReading(1, words=60, unsure=20, content=50, content_unsure=6)
    assert broken.poor(0.08)
    assert broken.describe().text == "page 1 was poorly read (12% of its content words unsure)"


def test_too_few_content_words_say_nothing_about_a_page() -> None:
    assert not PageReading(1, words=40, unsure=20, content=9, content_unsure=9).poor(0.08)
    assert PageReading(1, words=40, unsure=20, content=10, content_unsure=1).poor(0.08)


@pytest.mark.parametrize(
    ("content", "content_unsure"), [(1, None), (None, 0), (11, 0), (5, 6), (10, 4)]
)
def test_content_counts_are_consistent(content: int | None, content_unsure: int | None) -> None:
    with pytest.raises(ValidationError):
        PageReading(1, words=10, unsure=3, content=content, content_unsure=content_unsure)


def test_content_counts_as_the_log_keeps_them_and_entries_from_before() -> None:
    readings = (PageReading(1, 224, 23, 180, 6), PageReading(2, 50, 1))
    data = readings_to_json(readings)
    assert data[0] == {"page": 1, "words": 224, "unsure": 23, "content": 180, "content_unsure": 6}
    assert data[1] == {"page": 2, "words": 50, "unsure": 1}
    assert readings_from_json(data) == readings
    # Inconsistent counts are left out as any broken entry.
    assert readings_from_json([{"page": 1, "words": 5, "unsure": 1, "content": 9}]) == ()


BOX = Box(0.1, 0.2, 0.15, 0.01)


def test_the_stored_words_round_trip() -> None:
    pages = (
        PageWords(1, (ReadWord("Datum", 95, BOX, 0.012), ReadWord("j", 12))),
        PageWords(3, (ReadWord("24.06.2022", 96, BOX),)),
    )
    data = json.loads(json.dumps(reading_to_json(pages)))
    assert data["version"] == READING_VERSION
    assert data["pages"][0]["words"] == [
        {"text": "Datum", "confidence": 95, "box": [0.1, 0.2, 0.15, 0.01], "size": 0.012}
    ]
    # A word without a box cannot be found by a quote and is not kept.
    assert reading_from_json(data) == {1: (pages[0].words[0],), 3: pages[1].words}
    # Of another version, whatever its shape: read again.
    assert reading_from_json({"version": READING_VERSION + 1, "pages": []}) is None
    assert reading_from_json({"version": READING_VERSION + 1, "words": {}}) is None


@pytest.mark.parametrize(
    "data",
    [
        None,
        {"version": READING_VERSION},
        {"version": READING_VERSION, "pages": [{"page": 0, "words": []}]},
        {"version": READING_VERSION, "pages": [{"page": 1}]},
        {"version": READING_VERSION, "pages": [{"page": 1, "words": [{"text": "x"}]}]},
        {"version": READING_VERSION, "pages": [{"page": 1, "words": ["x"]}]},
        {
            "version": READING_VERSION,
            "pages": [{"page": 1, "words": [{"text": "x", "confidence": 1, "box": [0, 0]}]}],
        },
    ],
)
def test_a_broken_reading_is_invalid(data: JsonValue) -> None:
    with pytest.raises(ValidationError):
        reading_from_json(data)


def line(*texts: str, y: float = 0.5, unsure: dict[str, int] | None = None) -> list[ReadWord]:
    """Words side by side on one line, a tenth of the page wide each."""
    confidences = unsure or {}
    return [
        ReadWord(text, confidences.get(text, 93), Box(0.1 * n, y, 0.09, 0.01), 0.012)
        for n, text in enumerate(texts)
    ]


def test_the_words_of_a_quote_are_those_in_its_boxes() -> None:
    words = [
        *line("Lohnsteuer", "412,33", y=0.3),
        *line("Datum", "24.06.2022", "Juni", y=0.5),
        *line("Kirchensteuer", "32,99", y=0.52),  # the next line, close below
    ]
    # The text layer's box of "Datum 24.06.2022": a little higher than Tesseract's.
    location = Location(1, (Box(0.0, 0.497, 0.19, 0.008),))
    assert [word.text for word in words_at(location, words)] == ["Datum", "24.06.2022"]
    both = Location(1, (Box(0.0, 0.3, 0.2, 0.01), Box(0.1, 0.52, 0.1, 0.01)))
    assert [word.text for word in words_at(both, words)] == ["Lohnsteuer", "412,33", "32,99"]
    assert words_at(location, [ReadWord("Datum", 95)]) == []  # no box


def shows_date(text: DocumentText) -> bool:
    return text.has_date(date(2022, 6, 24))


def texts(words: tuple[ReadWord, ...] | None) -> list[str] | None:
    return None if words is None else [word.text for word in words]


def test_the_words_of_a_value_are_the_shortest_runs_that_show_it() -> None:
    words = line("Datum", "«oso:", "see", "24.06.2022", unsure={"«oso:": 22, "see": 47})
    assert texts(value_words(words, shows_date)) == ["24.06.2022"]
    # An amount with its currency apart counts as written by its number alone.
    amount = line("Lohnsteuer", "412,33", "EUR")
    found = value_words(amount, lambda text: text.has_amount(Decimal("412.33")))
    assert texts(found) == ["412,33"]
    # A date written in three words.
    spread = line("am", "24.", "Juni", "2022", "gezahlt")
    assert texts(value_words(spread, shows_date)) == ["24.", "Juni", "2022"]
    # Twice in the quote: both.
    twice = line("24.06.2022", "bis", "24.06.2022")
    assert texts(value_words(twice, shows_date)) == ["24.06.2022", "24.06.2022"]
    # Only all of them together.
    assert texts(value_words(line("24.", "Juni", "2022"), shows_date)) == ["24.", "Juni", "2022"]


def test_a_value_the_words_do_not_show_has_no_words() -> None:
    assert value_words(line("Datum", "Juni", "2022"), shows_date) is None
    assert value_words([], shows_date) is None


def test_a_value_without_a_place_is_found_where_it_stands_once() -> None:
    header = line("Entgeltbescheinigung", "24.06.2022")
    table = line("Lohnsteuer", "412,33", "EUR")
    assert value_on_pages({1: header, 2: table}, shows_date) == (1, (header[1],))
    amount = value_on_pages({1: header, 2: table}, lambda text: text.has_amount(Decimal("412.33")))
    assert amount == (2, (table[1],))
    # Written in three words: the shortest run that shows it.
    spread = line("gezahlt", "am", "24.", "Juni", "2022")
    assert value_on_pages({3: spread}, shows_date) == (3, tuple(spread[2:]))


def test_a_value_standing_twice_or_nowhere_is_not_found() -> None:
    twice = {1: line("24.06.2022", "Lohnsteuer"), 2: line("bis", "24.06.2022")}
    assert value_on_pages(twice, shows_date) is None
    assert value_on_pages({1: line("Datum", "Juni", "2022")}, shows_date) is None
    assert value_on_pages({}, shows_date) is None


# --- the value's surroundings ----------------------------------------------------------------


def the(words: Sequence[ReadWord], text: str) -> ReadWord:
    return next(word for word in words if word.text == text)


def test_a_date_in_a_well_read_header_above_a_badly_read_table_stands_well() -> None:
    """The real pay slip: none of the header's content words unsure, the table read badly, 9 %
    of the page's content words unsure, so that the page as a whole counts as poorly read."""
    words = hocr_words(hocr(BAD_TABLE))
    page = PageReading.of(1, words)
    assert page.poor(0.08) and page.share == pytest.approx(0.09, abs=0.005)
    place = surroundings(words, [the(words, "24.06.2022")])
    assert place is not None
    assert len(place.words) == SURROUNDING and place.unsure == 0
    assert not place.poor()
    # The words around it are the header's: the address and the lines of the date.
    assert {"Personalnummer", "Brutto/Netto-Bezüge", "Musterweg"} <= {
        word.text for word in place.words
    }


def test_an_amount_inside_a_badly_read_table_stands_in_a_poorly_read_place() -> None:
    words = hocr_words(hocr(BAD_TABLE))
    amount = the(words, "317,22")
    assert not amount.unsure  # the value itself was read sure
    place = surroundings(words, [amount])
    assert place is not None and place.poor()
    assert place.describe().text == (
        f"the text around the value was poorly read ({place.unsure} of 20 content words unsure)"
    )
    # On the pay slip with its table read well, fewer words around it are unsure.
    clean = hocr_words(hocr(PAYSLIP))
    good = surroundings(clean, [the(clean, "317,22")])
    assert good is not None and good.unsure < place.unsure


@pytest.mark.parametrize(("unsure", "poor"), [(0, False), (2, False), (3, True), (20, True)])
def test_a_place_is_poorly_read_from_three_of_twenty_on(unsure: int, poor: bool) -> None:
    around = Surroundings(tuple(word(f"Wort{n}", 30 if n < unsure else 93) for n in range(20)))
    assert around.unsure == unsure
    assert around.poor() is poor  # 2 of 20 is 10 %, 3 are 15 %


def grid(
    rows: int, columns: int, unsure: frozenset[tuple[int, int]] = frozenset()
) -> list[ReadWord]:
    """Words of five characters in rows and columns, in reading order. A line is a 32nd of the
    page high, a line's slot a 16th, so a line's height lies between two lines; a word is 3/64
    of the page wide, a column 1/16, so a word's character is 3/320 and a gap between words
    1/64, that is 5/3 characters. Fractions of two, so that equal gaps are equal."""
    return [
        ReadWord(
            f"w{row:02d}{column:02d}",
            30 if (row, column) in unsure else 93,
            Box(column / 16, row / 16, 3 / 64, 1 / 32),
            1 / 32,
        )
        for row in range(rows)
        for column in range(columns)
    ]


def test_a_gap_is_euclidean_between_edges_in_lines_and_characters() -> None:
    value = Box(0.3, 0.3, 0.05, 0.02)

    def to(box: Box) -> float:
        return gap(value, box, line=0.02, character=0.01)

    assert to(Box(0.36, 0.3, 0.05, 0.02)) == pytest.approx(0.5)  # a character to the right
    assert to(Box(0.32, 0.31, 0.05, 0.02)) == 0  # overlapping
    assert to(Box(0.3, 0.36, 0.05, 0.02)) == pytest.approx(2.0)  # two lines straight below
    assert to(Box(0.2, 0.29, 0.05, 0.02)) == pytest.approx(2.5)  # five characters to the left
    assert to(Box(0.39, 0.34, 0.05, 0.02)) == pytest.approx((2.0**2 + 1.0**2) ** 0.5)
    # A word on the same line a little to the right is nearer than one two lines down.
    assert to(Box(0.38, 0.3, 0.05, 0.02)) < to(Box(0.3, 0.36, 0.05, 0.02))
    # So too at the usual leading (a row 1.2 lines high): two rows down is 1.4 lines away,
    # two characters to the right one line; the next but one word on the line is farther.
    assert to(Box(0.3, 0.348, 0.05, 0.02)) == pytest.approx(1.4)
    assert to(Box(0.37, 0.3, 0.05, 0.02)) < to(Box(0.3, 0.348, 0.05, 0.02))


def test_the_same_line_is_nearer_than_the_lines_below() -> None:
    words = grid(5, 9)
    place = surroundings(words, [the(words, "w0004")], count=8)
    assert place is not None
    assert [word.text for word in place.words] == [
        "w0003",  # beside it on its line: 5/6 of a line
        "w0005",
        "w0104",  # straight below: a line
        "w0103",
        "w0105",
        "w0204",  # two lines down: three lines
        "w0203",
        "w0205",
    ]  # the next but one word on its line, more than four lines away, comes after


def test_ties_go_by_reading_order() -> None:
    words = grid(3, 9)
    value = [the(words, "w0104")]
    place = surroundings(words, value, count=3)
    assert place is not None and place == surroundings(words, value, count=3)
    # Left and right are as near, then above and below.
    assert [word.text for word in place.words] == ["w0103", "w0105", "w0004"]
    backwards = surroundings(words[::-1], value, count=3)
    assert backwards is not None
    assert [word.text for word in backwards.words] == ["w0105", "w0103", "w0204"]
    # Gaps that differ only in the last digits of their floats are equal too.
    plain = [
        ReadWord(f"Wort{n:02d}", 93, Box(round(0.1 * (n % 7), 4), 0.1 * (n // 7), 0.05, 0.02))
        for n in range(28)
    ]
    middle = [the(plain, "Wort10")]  # the fourth column of the second row
    beside = surroundings(plain, middle, count=2)
    reversed_ = surroundings(plain[::-1], middle, count=2)
    assert beside is not None and reversed_ is not None
    assert [word.text for word in beside.words] == ["Wort09", "Wort11"]
    assert [word.text for word in reversed_.words] == ["Wort11", "Wort09"]


def test_the_value_s_own_words_are_not_counted() -> None:
    words = grid(3, 8, unsure=frozenset({(1, 3), (1, 4)}))
    value = [the(words, "w0103"), the(words, "w0104")]  # a value of two words, read unsure
    place = surroundings(words, value)
    assert place is not None and len(place.words) == SURROUNDING
    assert not set(value) & set(place.words)
    assert place.unsure == 0


def placed(text: str, x: float, confidence: int = 93, height: float = 0.01) -> ReadWord:
    """A word on one line (a hundredth of the page high) at `x`, a tenth of the page wide."""
    return ReadWord(text, confidence, Box(x, 0.3, 0.1, height), 0.012)


def test_a_label_right_beside_a_leader_is_neither_content_nor_unsure() -> None:
    """Tesseract reads a clean label unsure beside its dots (`Krankenkasse` 38 %)."""
    words = [
        placed("Krankenkasse", 0.1, confidence=38),
        placed("................", 0.205),
        placed("Gesundkasse", 0.31),
    ]
    assert beside_leaders(words) == {0, 2}
    assert content_words(words) == []
    # Dots read as letters (a flat box) are a leader as well.
    flat = [placed("Steuerklasse", 0.1, confidence=59), placed("cence", 0.205, height=0.002)]
    assert beside_leaders(flat) == {0}


def test_a_word_apart_from_a_leader_or_on_another_line_stays_content() -> None:
    far = [placed("Krankenkasse", 0.1, confidence=38), placed("..........", 0.5)]
    assert beside_leaders(far) == set()  # four tenths of the page away
    below = ReadWord("Krankenkasse", 38, Box(0.1, 0.4, 0.1, 0.01), 0.012)
    assert beside_leaders([below, placed("..........", 0.205)]) == set()
    assert content_words(far) == [far[0]]


def test_noise_around_a_value_is_not_counted() -> None:
    words = grid(3, 8)
    noise = [
        ReadWord("..........", 18, Box(0.14, 0.0625, 0.04, 0.03125), 1 / 32),
        ReadWord("gy", 31, Box(0.25, 0.0625, 0.02, 0.03125), 1 / 32),
    ]
    place = surroundings([*words, *noise], [the(words, "w0103")])
    assert place is not None and place.unsure == 0
    assert not set(noise) & set(place.words)


def test_with_too_few_words_besides_the_value_the_page_decides() -> None:
    words = grid(3, 7)  # 21 words: 20 besides a value of one
    assert surroundings(words, [the(words, "w0103")]) is not None
    assert surroundings(words[:-1], [the(words, "w0103")]) is None
    assert surroundings(words, [the(words, "w0103"), the(words, "w0104")]) is None
    # Without the value's words, or without boxes, nothing is near.
    assert surroundings(words, []) is None
    assert surroundings([ReadWord(f"Wort{n}", 93) for n in range(30)], [word("Wort1")]) is None
    # Boxes without height and words without a line's size: nothing to measure by.
    flat = [ReadWord(f"Wort{n}", 93, Box(0.03 * n, 0.5, 0.02, 0.0)) for n in range(30)]
    assert surroundings(flat, [flat[3]]) is None
    assert surroundings(words[10:11], words[10:11], count=0) is None  # no other content
