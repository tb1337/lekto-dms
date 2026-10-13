"""Fixed-pitch text from the characters of a PDF: lines in their columns, as printed."""

from pathlib import Path

import pytest

from papiq.adapters.outbound.pdfium.fixed_pitch import fixed_pitch_blocks
from tests.contracts.processing import SAMPLES
from tests.samples.make_samples import PRINTOUT, pdf, text_lines

FONTS = ("Helvetica", "Courier")


def write(tmp_path: Path, content: str, page: str = "") -> Path:
    path = tmp_path / "printout.pdf"
    data = pdf(content, fonts=FONTS)
    if page:
        data = data.replace(b"/MediaBox [0 0 595 842]", f"/MediaBox [0 0 595 842] {page}".encode())
    path.write_bytes(data)
    return path


def courier(lines: list[str], y: float = 750) -> str:
    return text_lines("F2", 9.5, 13.5, 60, y, lines)


def test_a_printout_keeps_its_columns() -> None:
    (block,) = fixed_pitch_blocks(SAMPLES / "printout.pdf")
    assert block.text == "\n".join(PRINTOUT)
    assert block.page == 1
    # From the left edge of the dashes to the top of the first line, below the title.
    assert block.left == pytest.approx(60, abs=0.5)
    assert 750 < block.top < 760
    assert block.bottom < 750 - 13.5 * (len(PRINTOUT) - 1)


def test_proportional_text_has_no_blocks() -> None:
    assert fixed_pitch_blocks(SAMPLES / "text.pdf") == []


def test_two_lines_are_no_block(tmp_path: Path) -> None:
    assert (
        fixed_pitch_blocks(write(tmp_path, courier(["IBAN DE02 1203", "BIC  BYLADEM1001"]))) == []
    )


def test_a_line_in_another_font_ends_the_block(tmp_path: Path) -> None:
    content = " ".join(
        [
            courier(["Tag  Kommen", "Mo   07:31", "Di   07:47"]),
            text_lines("F1", 9.5, 0, 60, 750 - 3 * 13.5, ["Summe der Woche"]),
            courier(["Mi   07:27", "Do   07:46"], y=750 - 4 * 13.5),
        ]
    )
    (block,) = fixed_pitch_blocks(write(tmp_path, content))
    assert block.text == "Tag  Kommen\nMo   07:31\nDi   07:47"


def test_a_proportional_word_in_a_line_ends_the_block(tmp_path: Path) -> None:
    content = " ".join(
        [
            courier(["Tag  Kommen", "Mo   07:31", "Di   07:47", "Mi"]),
            text_lines("F1", 9.5, 0, 200, 750 - 3 * 13.5, ["Urlaub"]),
        ]
    )
    (block,) = fixed_pitch_blocks(write(tmp_path, content))
    assert block.text == "Tag  Kommen\nMo   07:31\nDi   07:47"


def test_a_wide_gap_starts_another_block(tmp_path: Path) -> None:
    content = " ".join(
        [
            courier(["Tag  Kommen", "Mo   07:31", "Di   07:47"]),
            courier(["Summe  Std.", "Soll   38.00", "Ist    39.49"], y=500),
        ]
    )
    first, second = fixed_pitch_blocks(write(tmp_path, content))
    assert (first.text, second.text) == (
        "Tag  Kommen\nMo   07:31\nDi   07:47",
        "Summe  Std.\nSoll   38.00\nIst    39.49",
    )
    assert first.bottom > second.top


def test_the_box_counts_from_the_visible_page(tmp_path: Path) -> None:
    path = write(tmp_path, courier(PRINTOUT), "/CropBox [10 20 585 822]")
    (block,) = fixed_pitch_blocks(path)
    assert block.left == pytest.approx(50, abs=0.5)
    assert 730 < block.top < 740


def test_a_rotated_page_is_left_alone(tmp_path: Path) -> None:
    assert fixed_pitch_blocks(write(tmp_path, courier(PRINTOUT), "/Rotate 90")) == []
