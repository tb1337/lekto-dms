"""The PDFium text locator passes the contract, measures on the page as shown and joins words
across a hyphen at a line end."""

from pathlib import Path

import pytest

from papiq.adapters.outbound.pdfium import PdfiumTextLocator
from papiq.core.domain.locations import Box
from tests.contracts.processing import SAMPLES, TextLocatorContract
from tests.samples.make_samples import LINES, text_pdf


@pytest.fixture
def text_locator() -> PdfiumTextLocator:
    return PdfiumTextLocator()


class TestPdfiumTextLocator(TextLocatorContract):
    pass


def near(box: Box, x: float, y: float, width: float, height: float) -> bool:
    return all(
        abs(a - b) < 0.01
        for a, b in zip((box.x, box.y, box.width, box.height), (x, y, width, height), strict=True)
    )


# "123,45" in text.pdf: PDFium's box (151.8, 684.5) to (221.8, 704.9) on a 595 x 842 page.
LEFT, BOTTOM, RIGHT, TOP = 151.8, 684.5, 221.8, 704.9
X, Y = LEFT / 595, (842 - TOP) / 842
WIDTH, HEIGHT = (RIGHT - LEFT) / 595, (TOP - BOTTOM) / 842


async def test_the_box_is_a_fraction_of_the_page() -> None:
    (places,) = await PdfiumTextLocator().locate(SAMPLES / "text.pdf", ["123,45"])
    assert near(places[0].boxes[0], X, Y, WIDTH, HEIGHT)


@pytest.mark.parametrize(
    ("rotation", "expected"),
    [
        (90, (1 - Y - HEIGHT, X, HEIGHT, WIDTH)),
        (180, (1 - X - WIDTH, 1 - Y - HEIGHT, WIDTH, HEIGHT)),
        (270, (Y, 1 - X - WIDTH, HEIGHT, WIDTH)),
    ],
)
async def test_boxes_follow_the_rotation_of_the_page(
    tmp_path: Path, rotation: int, expected: tuple[float, float, float, float]
) -> None:
    pdf = tmp_path / "rotated.pdf"
    pdf.write_bytes(
        text_pdf(LINES).replace(
            b"/MediaBox [0 0 595 842]", f"/MediaBox [0 0 595 842] /Rotate {rotation}".encode()
        )
    )
    (places,) = await PdfiumTextLocator().locate(pdf, ["123,45"])
    assert near(places[0].boxes[0], *expected)


async def test_a_hyphen_at_a_line_end_joins_the_word(tmp_path: Path) -> None:
    pdf = tmp_path / "hyphen.pdf"
    pdf.write_bytes(text_pdf(["Strom-", "rechnung fuer Maerz"]))
    (places,) = await PdfiumTextLocator().locate(pdf, ["Stromrechnung"])
    (place,) = places
    assert len(place.boxes) == 2


async def test_a_word_found_often_is_reported_a_few_times(tmp_path: Path) -> None:
    pdf = tmp_path / "many.pdf"
    pdf.write_bytes(text_pdf(["EUR EUR EUR", "EUR EUR EUR"]))
    (places,) = await PdfiumTextLocator().locate(pdf, ["EUR"])
    assert len(places) == 5


async def test_a_page_without_text_has_no_places() -> None:
    assert await PdfiumTextLocator().locate(SAMPLES / "scan.pdf", ["Rechnung"]) == [()]
