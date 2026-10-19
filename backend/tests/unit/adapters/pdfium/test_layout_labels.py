"""The label check on a parsed PDF: the words of the layout parser's structure and the places
the locator finds a quote at lie on the same page as shown, so a value is found by its quote's
place and measured against its label."""

import json
from decimal import Decimal
from pathlib import Path

from lekto.adapters.outbound.pdfium import PdfiumTextLocator
from lekto.adapters.outbound.pdfium.layout import LayoutParser
from lekto.core.domain.evidence import DocumentText
from lekto.core.domain.labels import LabelOutcome, LaidWord, check_label, layout_words
from tests.samples.make_samples import printout_pdf

PAYSLIP = [
    "Bezuege                                Betrag",
    "Grundgehalt                      3.980,00 EUR",
    "Zulage                             580,00 EUR",
    "Gesamtbrutto                     3.980,00 EUR",
    "",
    "Monatsbeitrag",
    "89,90 EUR",
]


async def parsed(tmp_path: Path) -> tuple[Path, dict[int, tuple[LaidWord, ...]]]:
    pdf = tmp_path / "payslip.pdf"
    pdf.write_bytes(printout_pdf("Entgeltabrechnung", PAYSLIP))
    text, structure = tmp_path / "content.txt", tmp_path / "content.json"
    await LayoutParser().parse(pdf, text=text, structure=structure)
    pages = layout_words(json.loads(structure.read_text(encoding="utf-8")))
    assert pages is not None
    return pdf, pages


async def outcome(tmp_path: Path, label: str, quote: str, amount: str) -> LabelOutcome:
    pdf, pages = await parsed(tmp_path)
    (places,) = await PdfiumTextLocator().locate(pdf, [quote])
    assert places, quote

    def shows(text: DocumentText) -> bool:
        return text.has_amount(Decimal(amount))

    return check_label(label, pages, places, shows).outcome


async def test_the_quote_s_place_tells_which_of_two_equal_values_is_meant(tmp_path: Path) -> None:
    gross, base = "Gesamtbrutto 3.980,00 EUR", "Grundgehalt 3.980,00 EUR"
    assert await outcome(tmp_path, "Gesamtbrutto", gross, "3980.00") is LabelOutcome.BESIDE
    assert await outcome(tmp_path, "Gesamtbrutto", base, "3980.00") is LabelOutcome.APART


async def test_a_value_below_its_label_on_a_printed_page(tmp_path: Path) -> None:
    assert await outcome(tmp_path, "Monatsbeitrag", "89,90 EUR", "89.90") is LabelOutcome.BESIDE
    assert await outcome(tmp_path, "Betrag", "580,00 EUR", "580.00") is LabelOutcome.BESIDE
    assert await outcome(tmp_path, "Bezuege", "580,00 EUR", "580.00") is LabelOutcome.APART
