import json
from datetime import date
from decimal import Decimal

import pytest

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.evidence import DocumentText
from papiq.core.domain.json_value import JsonValue
from papiq.core.domain.locations import Box, Location
from papiq.core.domain.reading import (
    READING_VERSION,
    OcrOutput,
    PageReading,
    PageWords,
    ReadWord,
    content_words,
    is_noise,
    reading_from_json,
    reading_to_json,
    readings_from_json,
    readings_to_json,
    value_words,
    words_at,
)


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
    )
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
    assert reading.unsure_share == pytest.approx(4 / 22)  # 18 % of all words
    assert reading.share == pytest.approx(1 / 19)  # 5 % of the content
    assert not reading.poor(0.08)
    assert reading.counted == (19, 1)
    # Read before content was counted: all words, as before.
    old = PageReading(2, words=22, unsure=4)
    assert old.poor(0.08)
    assert old.describe() == "page 2 was poorly read (18% of its words unsure)"
    broken = PageReading(1, words=60, unsure=20, content=50, content_unsure=6)
    assert broken.poor(0.08)
    assert broken.describe() == "page 1 was poorly read (12% of its content words unsure)"


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
    assert reading_from_json({"version": READING_VERSION + 1, "pages": []}) is None


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
