"""zxing-cpp on pages rendered by PDFium: passes the contract, reads every code of the sample
and nothing where there is none."""

from pathlib import Path

import pypdfium2
import pytest

from lekto.adapters.outbound.pdfium.library import LOCK
from lekto.adapters.outbound.zxing import ZxingCodeReader
from tests.builders import SAMPLES
from tests.contracts.processing import CodeReaderContract


@pytest.fixture
def code_reader() -> ZxingCodeReader:
    return ZxingCodeReader()


class TestZxingCodeReader(CodeReaderContract):
    pass


async def test_every_code_of_the_sample_with_its_format() -> None:
    reading = await ZxingCodeReader().read_codes(SAMPLES / "codes.pdf")
    found = {(code.format, code.text.split("\n")[0]) for code in reading.codes}
    assert found == {
        ("QR Code", "BCD"),
        ("Code 128", "K-20047718"),
        ("Data Matrix", "LEKTO-DM-0001"),
    }
    assert reading.reader.startswith("zxing-cpp ")


@pytest.mark.parametrize("sample", ["scan.pdf", "text.pdf", "poor-scan.pdf", "printout.pdf"])
async def test_no_codes_where_there_are_none(sample: str) -> None:
    """Noise and tables give no codes."""
    assert (await ZxingCodeReader().read_codes(SAMPLES / sample)).codes == ()


async def test_a_long_document_is_read_as_far_as_the_limit(tmp_path: Path) -> None:
    source = pypdfium2.PdfDocument(SAMPLES / "codes.pdf")
    target = pypdfium2.PdfDocument.new()
    for _ in range(3):
        target.import_pages(source)
    path = tmp_path / "three.pdf"
    target.save(path)
    source.close()
    target.close()
    reading = await ZxingCodeReader(max_pages=2).read_codes(path)
    assert reading.pages == 2
    assert sorted({code.page for code in reading.codes}) == [1, 2]


async def test_the_copy_of_a_page_does_not_hold_the_pdfium_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pixels of a rendered page lie in a buffer of our own; copying them into an image is
    no PDFium call and must not hold up the other users of PDFium."""
    to_pil = pypdfium2.PdfBitmap.to_pil
    held: list[bool] = []

    def observed(self: pypdfium2.PdfBitmap) -> object:
        held.append(LOCK.locked())
        return to_pil(self)

    monkeypatch.setattr(pypdfium2.PdfBitmap, "to_pil", observed)
    reading = await ZxingCodeReader().read_codes(SAMPLES / "codes.pdf")
    assert reading.pages == 1
    assert held == [False]
