"""Contracts of the processing ports: OCR, parser, page renderer, text locator. The samples
are in `tests/samples` (see `make_samples.py`)."""

import json
from pathlib import Path

import pytest

from papiq.core.domain import media_types
from papiq.core.domain.errors import UnprocessableDocumentError
from papiq.core.domain.locations import Location
from papiq.core.ports import DocumentParser, Ocr, PageRenderer, TextLocator

SAMPLES = Path(__file__).parent.parent / "samples"


class OcrContract:
    """Needs the fixture `ocr`."""

    @pytest.mark.parametrize(
        ("sample", "media_type"),
        [
            ("scan.pdf", media_types.PDF),
            ("text.pdf", media_types.PDF),
            ("photo.jpg", media_types.JPEG),
            ("screenshot.png", media_types.PNG),
        ],
    )
    async def test_makes_an_archive_pdf(
        self, ocr: Ocr, tmp_path: Path, sample: str, media_type: str
    ) -> None:
        target = tmp_path / "archive.pdf"
        result = await ocr.make_archive(SAMPLES / sample, target, media_type=media_type)
        assert target.read_bytes().startswith(b"%PDF-")
        assert result.pages == 1
        assert result.engine
        assert sorted(path.name for path in tmp_path.iterdir()) == ["archive.pdf"]

    async def test_replaces_the_target(self, ocr: Ocr, tmp_path: Path) -> None:
        target = tmp_path / "archive.pdf"
        target.write_bytes(b"old")
        await ocr.make_archive(SAMPLES / "scan.pdf", target, media_type=media_types.PDF)
        assert target.read_bytes().startswith(b"%PDF-")

    async def test_a_damaged_file_is_unprocessable(self, ocr: Ocr, tmp_path: Path) -> None:
        target = tmp_path / "archive.pdf"
        with pytest.raises(UnprocessableDocumentError):
            await ocr.make_archive(SAMPLES / "damaged.pdf", target, media_type=media_types.PDF)
        assert list(tmp_path.iterdir()) == []


class ParserContract:
    """Needs the fixture `parser`."""

    async def test_writes_markdown_and_structure(
        self, parser: DocumentParser, tmp_path: Path
    ) -> None:
        markdown, structure = tmp_path / "content.md", tmp_path / "content.json"
        result = await parser.parse(SAMPLES / "text.pdf", markdown=markdown, structure=structure)
        assert markdown.read_text(encoding="utf-8").strip()
        assert isinstance(json.loads(structure.read_text(encoding="utf-8")), dict)
        assert result.pages == 1
        assert result.parser
        assert sorted(path.name for path in tmp_path.iterdir()) == ["content.json", "content.md"]

    async def test_a_damaged_file_is_unprocessable(
        self, parser: DocumentParser, tmp_path: Path
    ) -> None:
        with pytest.raises(UnprocessableDocumentError):
            await parser.parse(
                SAMPLES / "damaged.pdf",
                markdown=tmp_path / "content.md",
                structure=tmp_path / "content.json",
            )
        assert list(tmp_path.iterdir()) == []


class PageRendererContract:
    """Needs the fixture `page_renderer`."""

    @pytest.mark.parametrize(
        ("sample", "media_type"),
        [("scan.pdf", media_types.PDF), ("photo.jpg", media_types.JPEG)],
    )
    async def test_renders_every_page_and_the_preview_as_webp(
        self, page_renderer: PageRenderer, tmp_path: Path, sample: str, media_type: str
    ) -> None:
        rendered = await page_renderer.render_pages(
            SAMPLES / sample, media_type=media_type, target=tmp_path
        )
        assert rendered.pages >= 1 and rendered.renderer
        expected = {f"{number}.webp" for number in range(1, rendered.pages + 1)} | {"preview.webp"}
        assert {path.name for path in tmp_path.iterdir()} == expected
        for path in tmp_path.iterdir():
            data = path.read_bytes()
            assert data[:4] == b"RIFF" and data[8:12] == b"WEBP", path.name

    async def test_a_damaged_pdf_is_unprocessable(
        self, page_renderer: PageRenderer, tmp_path: Path
    ) -> None:
        with pytest.raises(UnprocessableDocumentError):
            await page_renderer.render_pages(
                SAMPLES / "damaged.pdf", media_type=media_types.PDF, target=tmp_path
            )
        assert list(tmp_path.iterdir()) == []


class TextLocatorContract:
    """Needs the fixture `text_locator`, which knows `text.pdf`: one page with the lines
    "Rechnung Nummer 4711", "Papiq Testdokument" and "Betrag 123,45 EUR"."""

    @staticmethod
    def on_the_page(location: Location) -> None:
        assert location.page == 1
        assert location.boxes
        for box in location.boxes:
            assert box.width > 0 and box.height > 0
            assert box.x + box.width <= 1 and box.y + box.height <= 1

    async def test_finds_a_quote_with_page_and_box(self, text_locator: TextLocator) -> None:
        (places,) = await text_locator.locate(SAMPLES / "text.pdf", ["Betrag 123,45 EUR"])
        (place,) = places
        self.on_the_page(place)
        assert len(place.boxes) == 1

    async def test_case_spacing_and_line_breaks_do_not_matter(
        self, text_locator: TextLocator
    ) -> None:
        spaced, broken = await text_locator.locate(
            SAMPLES / "text.pdf", ["betrag   123,45 eur", "Testdokument\nBetrag"]
        )
        assert len(spaced) == 1
        (place,) = broken
        self.on_the_page(place)
        assert len(place.boxes) == 2  # one per line
        assert place.boxes[0].y < place.boxes[1].y

    async def test_markdown_marks_do_not_hide_a_quote(self, text_locator: TextLocator) -> None:
        (places,) = await text_locator.locate(SAMPLES / "text.pdf", ["**Betrag** | 123,45 EUR"])
        assert len(places) == 1

    async def test_one_answer_per_text_in_order(self, text_locator: TextLocator) -> None:
        second, missing, first = await text_locator.locate(
            SAMPLES / "text.pdf", ["Papiq Testdokument", "Kündigung", "Rechnung Nummer 4711"]
        )
        assert missing == ()
        assert first[0].boxes[0].y < second[0].boxes[0].y  # the first line is higher up

    async def test_no_texts_no_answers(self, text_locator: TextLocator) -> None:
        assert await text_locator.locate(SAMPLES / "damaged.pdf", []) == []

    async def test_a_damaged_pdf_is_unprocessable(self, text_locator: TextLocator) -> None:
        with pytest.raises(UnprocessableDocumentError):
            await text_locator.locate(SAMPLES / "damaged.pdf", ["Betrag"])
