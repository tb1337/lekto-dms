import pytest

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.reading import PageReading, readings_from_json, readings_to_json


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
