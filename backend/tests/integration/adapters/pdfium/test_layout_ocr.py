"""The layout text of an archive OCRmyPDF made from a scan: the parser reads the text layer OCR
put on it. Skips if the OCR programs are not installed (the devcontainer has them)."""

from datetime import timedelta
from pathlib import Path

from papiq.adapters.outbound.ocrmypdf import OcrmypdfEngine
from papiq.adapters.outbound.pdfium import LayoutParser
from papiq.core.domain import media_types
from tests import probes
from tests.builders import DEFAULT_SETTINGS, SAMPLES
from tests.samples.make_samples import LINES

pytestmark = probes.requires_ocr


async def test_the_text_layer_of_a_scan_is_read_line_by_line(tmp_path: Path) -> None:
    archive = tmp_path / "archive.pdf"
    engine = OcrmypdfEngine(
        languages=["deu", "eng"],
        timeout=timedelta(minutes=2),
        vision_timeout=DEFAULT_SETTINGS.vlm_timeout,
    )
    await engine.make_archive(SAMPLES / "scan.pdf", archive, media_type=media_types.PDF)
    text = tmp_path / "content.txt"
    result = await LayoutParser().parse(archive, text=text, structure=tmp_path / "s.json")
    assert [line.strip() for line in text.read_text(encoding="utf-8").splitlines() if line] == LINES
    assert result.pages == 1
