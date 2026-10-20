"""The places of the text on a parsed PDF: the layout parser writes its text from the words of
its structure, so every word of the text is found in the structure, on its page, with its box:
in columns, in a printout's fixed pitch, along the margin and on later pages."""

import json
import re
from collections.abc import Callable
from pathlib import Path

import pikepdf
import pytest

from lekto.adapters.outbound.pdfium.layout import LayoutParser
from lekto.core.domain.labels import layout_words
from lekto.core.domain.text_places import TextPlaces
from tests.builders import SAMPLES
from tests.samples.make_samples import pdf

COLUMNS = " ".join(
    [
        "BT /F1 10 Tf 1 0 0 1 60 700 Tm (Gesamtbrutto \\(EBeschV\\)) Tj ET",
        "BT /F1 10 Tf 1 0 0 1 330 700 Tm (6.767,00) Tj ET",
        "BT /F1 10 Tf 1 0 0 1 430 700 Tm (63.023,50) Tj ET",
        "BT /F1 10 Tf 1 0 0 1 60 600 Tm [(Sehr) -300 (geehrte) -300 (Frau)] TJ ET",
        "BT /F1 10 Tf 0 1 -1 0 560 300 Tm (Seite 1/4) Tj ET",
    ]
)


async def parsed(tmp_path: Path, source: Path) -> tuple[str, TextPlaces]:
    text, structure = tmp_path / "content.txt", tmp_path / "content.json"
    await LayoutParser().parse(source, text=text, structure=structure)
    content = text.read_text(encoding="utf-8")
    pages = layout_words(json.loads(structure.read_text(encoding="utf-8")))
    assert pages is not None
    return content, TextPlaces(content, pages)


def three_pages(tmp_path: Path) -> Path:
    """The text sample, a blank page, the text sample again."""
    source = tmp_path / "pages.pdf"
    with (
        pikepdf.open(SAMPLES / "text.pdf") as document,
        pikepdf.open(SAMPLES / "text.pdf") as other,
    ):
        document.add_blank_page(page_size=(595, 842))
        document.pages.append(other.pages[0])
        document.save(source)
    return source


def drawn(tmp_path: Path) -> Path:
    source = tmp_path / "columns.pdf"
    source.write_bytes(pdf(COLUMNS))
    return source


@pytest.mark.parametrize(
    "source",
    [
        lambda _: SAMPLES / "text.pdf",
        lambda _: SAMPLES / "printout.pdf",
        lambda _: SAMPLES / "unmapped.pdf",
        three_pages,
        drawn,
    ],
    ids=["text", "printout", "unmapped", "pages", "columns"],
)
async def test_every_word_of_the_text_has_its_place(
    tmp_path: Path, source: Callable[[Path], Path]
) -> None:
    content, places = await parsed(tmp_path, source(tmp_path))
    runs = list(re.finditer(r"\S+", content))
    assert runs
    for run in runs:
        assert places.locations(run.start(), run.end()), run.group()


async def test_a_word_stands_on_its_page(tmp_path: Path) -> None:
    content, places = await parsed(tmp_path, three_pages(tmp_path))
    first = content.index("Rechnung")
    last = content.rindex("Rechnung")
    ((page, (box,)),) = [(item.page, item.boxes) for item in places.locations(first, first + 8)]
    assert page == 1 and box.x == pytest.approx(72 / 595, abs=0.01)
    assert [item.page for item in places.locations(last, last + 8)] == [3]
