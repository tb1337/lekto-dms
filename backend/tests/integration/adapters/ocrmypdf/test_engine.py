"""OCRmyPDF with Tesseract and Ghostscript: passes the contract and recognises text. Skips if
the programs are not installed (the devcontainer has them)."""

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pypdfium2
import pytest

from lekto.adapters.outbound.ocrmypdf import OcrmypdfEngine
from lekto.adapters.outbound.ocrmypdf.engine import UNREADABLE_NOTE
from lekto.adapters.outbound.ocrmypdf.vision import VisionSettings
from lekto.adapters.outbound.pdfium import PdfiumTextLocator, has_hidden_text
from lekto.adapters.outbound.pdfium.library import unreadable_share
from lekto.composition.container import VISION_REQUEST_TIMEOUT
from lekto.core.domain import media_types
from lekto.core.domain.errors import LanguageModelError
from lekto.core.domain.reading import words_at
from lekto.core.domain.reasons import text_of as reasons_text
from tests import probes
from tests.builders import DEFAULT_SETTINGS, SAMPLES
from tests.contracts.processing import OcrContract
from tests.vision_stub import VisionStub, serve

pytestmark = probes.requires_ocr


def engine(
    timeout: timedelta = timedelta(minutes=2), vision: VisionStub | None = None
) -> OcrmypdfEngine:
    settings = None
    if vision is not None:
        settings = VisionSettings(
            base_url=vision.url,
            model=vision.model,
            api_key="stub-key",
            timeout=VISION_REQUEST_TIMEOUT,
        )
    return OcrmypdfEngine(
        languages=["deu", "eng"],
        timeout=timeout,
        vision=settings,
        vision_timeout=DEFAULT_SETTINGS.vlm_timeout,
    )


@pytest.fixture
def ocr() -> OcrmypdfEngine:
    return engine()


@pytest.fixture
def stub() -> Iterator[VisionStub]:
    with serve(VisionStub()) as served:
        yield served


@pytest.fixture
def vision_ocr(stub: VisionStub) -> OcrmypdfEngine:
    return engine(vision=stub)


class TestOcrmypdfEngine(OcrContract):
    pass


def text_of(pdf: Path) -> str:
    document = pypdfium2.PdfDocument(pdf)
    try:
        return " ".join(page.get_textpage().get_text_range() for page in document)
    finally:
        document.close()


@pytest.mark.parametrize(
    ("sample", "media_type", "pages"),
    [
        ("scan.pdf", media_types.PDF, 1),
        ("photo.jpg", media_types.JPEG, 1),
        ("lowres.jpg", media_types.JPEG, 1),
        ("screenshot.png", media_types.PNG, 1),
        ("pages.tiff", media_types.TIFF, 2),
    ],
)
async def test_scans_and_images_get_a_text_layer(
    tmp_path: Path, sample: str, media_type: str, pages: int
) -> None:
    target = tmp_path / "archive.pdf"
    assert "Rechnung" not in text_of(SAMPLES / "scan.pdf")
    result = await engine().make_archive(SAMPLES / sample, target, media_type=media_type)
    assert result.pages == pages
    assert sorted(path.name for path in tmp_path.iterdir()) == ["archive.pdf"]
    text = " ".join(text_of(target).split())
    assert "Rechnung Nummer 4711" in text
    assert "123,45 EUR" in text
    assert result.pdfa
    assert result.engine.startswith("ocrmypdf ")
    assert "tesseract" in result.engine
    # Tesseract's hOCR, kept by OCRmyPDF: every page read, the clean sample without doubt.
    assert [reading.page for reading in result.readings] == list(range(1, pages + 1))
    assert all(reading.words > 0 for reading in result.readings)
    assert all(reading.content is not None for reading in result.readings)
    assert [page.page for page in result.words] == list(range(1, pages + 1))


async def test_the_words_stand_where_the_text_layer_puts_them(tmp_path: Path) -> None:
    """The boxes of Tesseract's words and those the locator finds in the archive agree: the
    words of a quote are found in its boxes."""
    target = tmp_path / "archive.pdf"
    result = await engine().make_archive(SAMPLES / "scan.pdf", target, media_type=media_types.PDF)
    (page,) = result.words
    assert all(word.box is not None and word.size is not None for word in page.words)
    for quote, words in [
        ("Rechnung Nummer 4711", ["Rechnung", "Nummer", "4711"]),
        ("123,45 EUR", ["123,45", "EUR"]),
    ]:
        ((location,),) = await PdfiumTextLocator().locate(target, [quote])
        assert [word.text for word in words_at(location, page.words)] == words


async def test_existing_text_is_kept(tmp_path: Path) -> None:
    target = tmp_path / "archive.pdf"
    result = await engine().make_archive(SAMPLES / "text.pdf", target, media_type=media_types.PDF)
    assert text_of(target).split() == text_of(SAMPLES / "text.pdf").split()
    assert result.readings == ()


async def test_another_ocr_s_layer_is_read_again(tmp_path: Path) -> None:
    """An archive of ours stands in for a scan another program made searchable."""
    searchable = tmp_path / "searchable.pdf"
    await engine().make_archive(SAMPLES / "scan.pdf", searchable, media_type=media_types.PDF)
    assert await asyncio.to_thread(has_hidden_text, searchable)
    assert not await asyncio.to_thread(has_hidden_text, SAMPLES / "text.pdf")
    assert not await asyncio.to_thread(has_hidden_text, SAMPLES / "scan.pdf")
    target = tmp_path / "archive.pdf"
    result = await engine().make_archive(searchable, target, media_type=media_types.PDF)
    assert result.read_again
    assert [reading.page for reading in result.readings] == [1]
    assert "Rechnung Nummer 4711" in " ".join(text_of(target).split())


async def test_text_in_a_font_without_a_character_map_is_read_from_the_image(
    tmp_path: Path,
) -> None:
    """Its codes come out as control characters; `--skip-text` would keep them."""
    assert unreadable_share(text_of(SAMPLES / "unmapped.pdf")) == 1.0
    target = tmp_path / "archive.pdf"
    result = await engine().make_archive(
        SAMPLES / "unmapped.pdf", target, media_type=media_types.PDF
    )
    assert (result.read_again, result.pdfa, reasons_text(result.notes)) == (
        True,
        True,
        UNREADABLE_NOTE.text,
    )
    text = text_of(target)
    assert "Rechnung Nummer 4711" in " ".join(text.split())
    assert unreadable_share(text) == 0.0
    assert [reading.page for reading in result.readings] == [1]


async def test_an_empty_page_has_no_text(tmp_path: Path) -> None:
    target = tmp_path / "archive.pdf"
    result = await engine().make_archive(SAMPLES / "blank.pdf", target, media_type=media_types.PDF)
    assert result.pages == 1
    assert text_of(target).strip() == ""


async def test_the_time_limit_stops_ocr(tmp_path: Path) -> None:
    target = tmp_path / "archive.pdf"
    with pytest.raises(TimeoutError, match="did not finish"):
        await engine(timeout=timedelta(milliseconds=50)).make_archive(
            SAMPLES / "scan.pdf", target, media_type=media_types.PDF
        )
    assert list(tmp_path.iterdir()) == []


async def test_a_signed_pdf_gets_its_archive_without_the_signature(tmp_path: Path) -> None:
    target = tmp_path / "archive.pdf"
    result = await engine().make_archive(SAMPLES / "signed.pdf", target, media_type=media_types.PDF)
    assert (result.pages, result.pdfa) == (1, True)
    assert "signature" in (reasons_text(result.notes) or "")
    assert "Rechnung Nummer 4711" in " ".join(text_of(target).split())
    assert sorted(path.name for path in tmp_path.iterdir()) == ["archive.pdf"]


def char_boxes(pdf: Path, needle: str) -> tuple[float, float]:
    """Where `needle` starts on the first page: its left and top in fractions of the page."""
    document = pypdfium2.PdfDocument(pdf)
    try:
        page = document[0]
        width, height = page.get_size()
        textpage = page.get_textpage()
        start = textpage.get_text_range().index(needle)
        left, _, _, top = textpage.get_charbox(start)
        return left / width, 1 - top / height
    finally:
        document.close()


async def test_the_vision_model_s_lines_become_the_text_layer(
    tmp_path: Path, stub: VisionStub
) -> None:
    """At the places it gives, also on a scan Tesseract would read itself."""
    stub.pages = [
        [
            ("Rechnung Nummer 4711", (0.1, 0.11, 0.6, 0.14)),
            ("Betrag 123,45 EUR [unreadable]", (0.1, 0.5, 0.7, 0.53)),
        ]
    ]
    target = tmp_path / "archive.pdf"
    result = await engine(vision=stub).make_archive(
        SAMPLES / "scan.pdf", target, media_type=media_types.PDF, vision=True
    )
    text = " ".join(text_of(target).split())
    assert text == "Rechnung Nummer 4711 Betrag 123,45 EUR [unreadable]"
    left, top = char_boxes(target, "Betrag")
    assert left == pytest.approx(0.1, abs=0.02)
    assert top == pytest.approx(0.5, abs=0.02)
    assert result.pdfa
    assert "vision language model stub-vlm (read-1)" in result.engine
    (reading,) = result.readings
    assert (reading.page, reading.words, reading.unsure, reading.content) == (1, 7, 1, None)
    assert result.words == ()
    assert result.vision is not None
    (call,) = result.vision.calls
    assert call.model == "stub-vlm"
    assert call.usage == {"prompt_tokens": 1500, "completion_tokens": 120}
    assert "[image: page 1," in call.user
    assert "base64" not in call.user
    # The page went at no more than about a megapixel, with the key.
    image = stub.requests[0]["messages"][1]["content"][1]["image_url"]["url"]
    assert image.startswith("data:image/png;base64,")
    assert stub.keys == ["stub-key"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["archive.pdf"]


async def test_every_page_of_a_tiff_is_read(tmp_path: Path, stub: VisionStub) -> None:
    stub.pages = [
        [("Seite eins", (0.1, 0.1, 0.4, 0.13))],
        [("Seite zwei", (0.1, 0.1, 0.4, 0.13))],
    ]
    target = tmp_path / "archive.pdf"
    result = await engine(vision=stub).make_archive(
        SAMPLES / "pages.tiff", target, media_type=media_types.TIFF, vision=True
    )
    assert result.pages == 2
    assert [reading.page for reading in result.readings] == [1, 2]
    assert " ".join(text_of(target).split()) == "Seite eins Seite zwei"
    assert result.vision is not None and len(result.vision.calls) == 2


async def test_a_model_that_cannot_read_fails_the_archive(tmp_path: Path, stub: VisionStub) -> None:
    stub.status = 503
    target = tmp_path / "archive.pdf"
    with pytest.raises(LanguageModelError, match="HTTP 503: the stub is down"):
        await engine(vision=stub).make_archive(
            SAMPLES / "scan.pdf", target, media_type=media_types.PDF, vision=True
        )
    assert list(tmp_path.iterdir()) == []
