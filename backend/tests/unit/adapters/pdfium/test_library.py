"""What the text layer of a PDF tells before OCR."""

import pytest

from papiq.adapters.outbound.pdfium import has_unreadable_text
from papiq.adapters.outbound.pdfium.library import unreadable_share
from tests.contracts.processing import SAMPLES


@pytest.mark.parametrize(
    ("text", "share"),
    [
        ("", 0.0),
        (" \n\t", 0.0),
        ("Rechnung 4711", 0.0),
        ("\x17\x1b5\x1b", 0.75),
        ("ab�", 0.5),
    ],
)
def test_the_share_of_characters_that_map_to_nothing(text: str, share: float) -> None:
    assert unreadable_share(text) == share


def test_a_font_without_a_character_map_makes_the_text_unreadable() -> None:
    assert has_unreadable_text(SAMPLES / "unmapped.pdf")
    for sample in ("text.pdf", "printout.pdf", "scan.pdf", "blank.pdf", "damaged.pdf"):
        assert not has_unreadable_text(SAMPLES / sample), sample
