"""Fixed-pitch text from the characters of a PDF: lines in their columns, as printed."""

from pathlib import Path

import pypdfium2
import pytest

from lekto.adapters.outbound.pdfium.chars import Char, Geometry, page_chars, reading_turn
from lekto.adapters.outbound.pdfium.fixed_pitch import FixedPitchBlock, blocks_of, page_lines
from lekto.adapters.outbound.pdfium.library import LOCK
from tests.builders import SAMPLES
from tests.samples.make_samples import PRINTOUT, pdf, text_lines

FONTS = ("Helvetica", "Courier")


def fixed_pitch_blocks(path: Path) -> list[FixedPitchBlock]:
    """The blocks of fixed-pitch text in a PDF, page by page from the top, as the layout
    parser finds them on each page."""
    with LOCK:
        document = pypdfium2.PdfDocument(path)
        try:
            return [
                block
                for number in range(1, len(document) + 1)
                for block in blocks_of(page_lines(_page_chars(document, number)))
            ]
        finally:
            document.close()


def _page_chars(document: pypdfium2.PdfDocument, number: int) -> list[Char]:
    page = document[number - 1]
    textpage = page.get_textpage()
    try:
        geometry = Geometry.of(page)
        upright, _ = page_chars(textpage, geometry.turned(reading_turn(textpage, geometry)))
        return upright
    finally:
        textpage.close()
        page.close()


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


def test_a_page_shown_turned_is_read_the_way_its_text_runs(tmp_path: Path) -> None:
    (block,) = fixed_pitch_blocks(write(tmp_path, courier(PRINTOUT), "/Rotate 90"))
    assert block.text == "\n".join(PRINTOUT)
