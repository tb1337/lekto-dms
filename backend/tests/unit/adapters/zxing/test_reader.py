"""zxing-cpp on pages rendered by PDFium: passes the contract, reads every code of the sample
and nothing where there is none."""

from pathlib import Path

import pytest

from papiq.adapters.outbound.zxing import ZxingCodeReader
from tests.contracts.processing import SAMPLES, CodeReaderContract


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
        ("Data Matrix", "PAPIQ-DM-0001"),
    }
    assert reading.reader.startswith("zxing-cpp ")


@pytest.mark.parametrize("sample", ["scan.pdf", "text.pdf", "poor-scan.pdf", "printout.pdf"])
async def test_no_codes_where_there_are_none(sample: str) -> None:
    """Noise and tables give no codes."""
    assert (await ZxingCodeReader().read_codes(SAMPLES / sample)).codes == ()


async def test_a_long_document_is_read_as_far_as_the_limit(tmp_path: Path) -> None:
    import pypdfium2

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
