"""The PDFium page renderer passes the contract, keeps the widths and reads images."""

from pathlib import Path

import pytest
from PIL import Image

from lekto.adapters.outbound.pdfium import PdfiumPageRenderer
from lekto.core.domain import media_types
from tests.builders import SAMPLES
from tests.contracts.processing import PageRendererContract


@pytest.fixture
def page_renderer() -> PdfiumPageRenderer:
    return PdfiumPageRenderer()


class TestPdfiumPageRenderer(PageRendererContract):
    pass


def size(path: Path) -> tuple[str | None, int, int]:
    with Image.open(path) as image:
        return image.format, image.width, image.height


async def test_pages_and_preview_have_the_configured_widths(tmp_path: Path) -> None:
    renderer = PdfiumPageRenderer(width=300, preview_width=100)
    rendered = await renderer.render_pages(
        SAMPLES / "text.pdf", media_type=media_types.PDF, target=tmp_path
    )
    assert rendered.pages == 1 and rendered.renderer.startswith("pdfium ")
    assert size(tmp_path / "1.webp") == ("WEBP", 300, round(300 * 842 / 595))  # A4 portrait
    assert size(tmp_path / "preview.webp") == ("WEBP", 100, round(100 * 842 / 595))


async def test_every_frame_of_a_tiff_is_a_page(tmp_path: Path) -> None:
    rendered = await PdfiumPageRenderer(width=300).render_pages(
        SAMPLES / "pages.tiff", media_type=media_types.TIFF, target=tmp_path
    )
    assert rendered.pages == 2 and rendered.renderer.startswith("pillow ")
    assert {path.name for path in tmp_path.iterdir()} == {"1.webp", "2.webp", "preview.webp"}
    assert size(tmp_path / "2.webp")[1] == 300


async def test_a_small_image_keeps_its_size_and_transparency_turns_white(tmp_path: Path) -> None:
    rendered = await PdfiumPageRenderer(width=1200).render_pages(
        SAMPLES / "screenshot.png", media_type=media_types.PNG, target=tmp_path
    )
    assert rendered.pages == 1
    with Image.open(tmp_path / "1.webp") as image:
        assert (image.width, image.height) == (1000, 600)  # not scaled up
        assert image.convert("RGB").getpixel((0, 0)) == (255, 255, 255)


async def test_a_file_that_is_no_image_is_unprocessable(tmp_path: Path) -> None:
    from lekto.core.domain.errors import UnprocessableDocumentError

    with pytest.raises(UnprocessableDocumentError, match="cannot be read"):
        await PdfiumPageRenderer().render_pages(
            SAMPLES / "damaged.pdf", media_type=media_types.JPEG, target=tmp_path
        )
    assert list(tmp_path.iterdir()) == []
