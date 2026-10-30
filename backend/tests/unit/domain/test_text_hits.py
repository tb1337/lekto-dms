"""Where text conditions hit: whole words with any whitespace, long values without spaces,
patterns on the collapsed text mapped back."""

from lekto.core.domain.text_hits import collapsed, contained

TEXT = "Stadtwerke  Süd\nIhre Stromrechnung\n  Nr. 4711\nIBAN DE89 3704 0044 0532 0130 00"


def test_whole_words_any_case_any_whitespace() -> None:
    (hit,) = contained(TEXT, "stadtwerke süd")
    assert TEXT[slice(*hit)] == "Stadtwerke  Süd"
    assert contained(TEXT, "Strom") == ()  # not a whole word
    (number,) = contained(TEXT, "nr. 4711")
    assert TEXT[slice(*number)] == "Nr. 4711"


def test_a_long_value_without_its_spaces() -> None:
    (iban,) = contained(TEXT, "DE89370400440532013000")
    assert TEXT[slice(*iban)] == "DE89 3704 0044 0532 0130 00"


def test_the_collapsed_text_maps_back() -> None:
    folded = collapsed(TEXT)
    assert folded.text.startswith("Stadtwerke Süd Ihre Stromrechnung Nr. 4711")
    start = folded.text.index("Süd Ihre")
    begin, end = folded.span(start, start + len("Süd Ihre"))
    assert TEXT[begin:end] == "Süd\nIhre"
