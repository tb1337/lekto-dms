"""The text of a PDF as it is set: lines with their words in columns, printouts as printed,
text across the page read along its direction, and Papiq's own structure."""

import json
from pathlib import Path
from typing import Any

import pikepdf
import pytest

from lekto.adapters.outbound.pdfium.layout import PAGE_BREAK, LayoutParser
from tests.builders import SAMPLES
from tests.contracts.processing import ParserContract
from tests.samples.make_samples import PRINTOUT, PRINTOUT_TITLE, pdf


@pytest.fixture
def parser() -> LayoutParser:
    return LayoutParser()


class TestLayoutParser(ParserContract):
    pass


def at(x: float, y: float, text: str, *, size: float = 10, up: bool = False) -> str:
    """`text` from (x, y) in Helvetica; `up`: running up the page."""
    matrix = "0 1 -1 0" if up else "1 0 0 1"
    return f"BT /F1 {size} Tf {matrix} {x} {y} Tm ({text}) Tj ET"


async def parse(tmp_path: Path, content: str | bytes, page: str = "") -> tuple[str, dict[str, Any]]:
    data = pdf(content) if isinstance(content, str) else content
    if page:
        data = data.replace(b"/MediaBox [0 0 595 842]", f"/MediaBox [0 0 595 842] {page}".encode())
    source = tmp_path / "source.pdf"
    source.write_bytes(data)
    text, structure = tmp_path / "content.txt", tmp_path / "content.json"
    await LayoutParser().parse(source, text=text, structure=structure)
    return text.read_text(encoding="utf-8"), json.loads(structure.read_text(encoding="utf-8"))


async def test_a_label_keeps_its_amounts_and_columns_line_up(tmp_path: Path) -> None:
    text, _ = await parse(
        tmp_path,
        " ".join(
            [
                at(60, 700, "Gesamtbrutto \\(EBeschV\\)"),
                at(330, 700, "6.767,00"),
                at(430, 700, "63.023,50"),
                at(60, 686, "Steuer-Brutto, EZ"),
                at(430, 686, "3.544,50"),
            ]
        ),
    )
    first, second = text.splitlines()
    assert first.startswith("Gesamtbrutto (EBeschV)  ") and "6.767,00" in first
    assert first.index("63.023,50") == second.index("3.544,50")
    assert second.startswith("Steuer-Brutto, EZ  ")


async def test_running_text_has_single_spaces_and_a_gap_a_blank_line(tmp_path: Path) -> None:
    text, _ = await parse(
        tmp_path,
        " ".join(
            [
                at(60, 700, "Sehr geehrte Frau Musterfrau,"),
                at(60, 686, "wir passen Ihren Abschlag an."),
                at(60, 600, "Mit freundlichen Grüßen"),
            ]
        ),
    )
    assert text == (
        "Sehr geehrte Frau Musterfrau,\nwir passen Ihren Abschlag an.\n\nMit freundlichen Grüßen"
    )


async def test_words_placed_without_spaces_are_apart(tmp_path: Path) -> None:
    text, _ = await parse(
        tmp_path, "BT /F1 10 Tf 1 0 0 1 60 700 Tm [(Sehr) -300 (geehrte) -300 (Frau)] TJ ET"
    )
    assert text == "Sehr geehrte Frau"


async def test_a_sidebar_stays_beside_the_address(tmp_path: Path) -> None:
    text, _ = await parse(
        tmp_path, " ".join([at(60, 700, "Erika Musterfrau"), at(400, 700, "Telefon 0341 555-2400")])
    )
    name, phone = text.split("  ", 1)
    assert name == "Erika Musterfrau" and phone.strip() == "Telefon 0341 555-2400"


async def test_a_printout_keeps_its_columns(tmp_path: Path) -> None:
    text, _ = await parse(tmp_path, (SAMPLES / "printout.pdf").read_bytes())
    assert text == f"{PRINTOUT_TITLE}\n\n" + "\n".join(PRINTOUT)


async def test_text_up_the_margin_is_read_along_it(tmp_path: Path) -> None:
    text, _ = await parse(
        tmp_path,
        " ".join([at(60, 700, "Rechnung Nummer 4711"), at(560, 300, "Seite 1/4", up=True)]),
    )
    assert text == "Rechnung Nummer 4711\n\nSeite 1/4"


@pytest.mark.parametrize("page", ["/Rotate 90", ""])
async def test_a_page_whose_text_runs_across_it_is_read_that_way(tmp_path: Path, page: str) -> None:
    """Shown turned (`/Rotate`), or not turned at all (a table printed across the page)."""
    lines = [
        at(100, 100, "Rechnung Nummer 4711", up=True),
        at(120, 100, "Betrag 123,45 EUR", up=True),
    ]
    text, structure = await parse(tmp_path, " ".join(lines), page)
    assert text == "Rechnung Nummer 4711\nBetrag 123,45 EUR"
    if page:
        assert (structure["pages"][0]["width"], structure["pages"][0]["height"]) == (842, 595)


async def test_the_structure_has_pages_lines_and_words_with_boxes(tmp_path: Path) -> None:
    _, structure = await parse(tmp_path, (SAMPLES / "text.pdf").read_bytes())
    assert structure["parser"] == "layout"
    (page,) = structure["pages"]
    assert (page["number"], page["width"], page["height"]) == (1, 595, 842)
    first = page["lines"][0]
    assert first["text"] == "Rechnung Nummer 4711"
    assert [word["text"] for word in first["words"]] == ["Rechnung", "Nummer", "4711"]
    x1, y1, x2, y2 = first["box"]
    assert x1 == pytest.approx(72 / 595, abs=0.01) and 0 < y1 < y2 < 0.15 and x1 < x2 <= 1


async def test_pages_are_apart_and_one_without_text_is_empty(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    with (
        pikepdf.open(SAMPLES / "text.pdf") as document,
        pikepdf.open(SAMPLES / "text.pdf") as other,
    ):
        document.add_blank_page(page_size=(595, 842))
        document.pages.append(other.pages[0])
        document.save(source)
    text, structure = tmp_path / "content.txt", tmp_path / "content.json"
    result = await LayoutParser().parse(source, text=text, structure=structure)
    first, empty, third = text.read_text(encoding="utf-8").split(PAGE_BREAK)
    assert first == third and first.startswith("Rechnung Nummer 4711") and empty == ""
    assert result.pages == 3
    assert result.parser.startswith("layout 1, pypdfium2 ")
