"""Reading Tesseract's hOCR: the words with confidence, box and line size, and the counts of
all, content and unsure words per page."""

from pathlib import Path

from papiq.adapters.outbound.ocrmypdf.hocr import hocr_words, read_hocr
from papiq.core.domain.locations import Box
from papiq.core.domain.reading import PageReading, ReadWord
from tests.scans import PAYSLIP, ScanLine, hocr

PAGE = "image &quot;000001_ocr.png&quot;; bbox 0 0 2000 1000; ppageno 0"
HEADER = "bbox 100 100 1900 160; x_size 60; x_descenders 12"
LINE = "bbox 100 300 1900 330; baseline 0 -6; x_size 30"
TESSERACT = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
 <body>
  <div class='ocr_page' id='page_1' title='{PAGE}'>
   <div class='ocr_carea' id='block_1_1' title="bbox 100 100 1900 400">
    <p class='ocr_par' id='par_1_1' lang='deu' title="bbox 100 100 1900 400">
     <span class='ocr_header' id='line_1_1' title="{HEADER}">
      <span class='ocrx_word' id='word_1_1' title='bbox 100 100 700 160; x_wconf 95'
       ><strong>Lohnabrechnung</strong></span>
     </span>
     <span class='ocr_line' id='line_1_2' title="{LINE}">
      <span class='ocrx_word' id='word_1_2' title='bbox 100 300 400 330; x_wconf 96'
       >Müller&amp;Söhne</span>
      <span class='ocrx_word' id='word_1_3' title='bbox 500 300 700 330; x_wconf 31'
       >412,33</span>
      <span class='ocrx_word' id='word_1_4' title='bbox 800 300 900 330; x_wconf 5'> </span>
      <span class='ocrx_word' id='word_1_5' title='bbox 1900 300 2100 330; x_wconf 70'>€</span>
     </span>
    </p>
   </div>
   <span class='ocrx_word' id='word_1_6' title='bbox 10 900 50 920; x_wconf 40'>j</span>
  </div>
 </body>
</html>
"""


def test_words_with_their_box_line_size_and_confidence() -> None:
    assert hocr_words(TESSERACT) == (
        ReadWord("Lohnabrechnung", 95, Box(0.05, 0.1, 0.3, 0.06), 0.06),
        ReadWord("Müller&Söhne", 96, Box(0.05, 0.3, 0.15, 0.03), 0.03),
        ReadWord("412,33", 31, Box(0.25, 0.3, 0.1, 0.03), 0.03),
        # The empty word is left out; a box over the edge is cut to the page.
        ReadWord("€", 70, Box(0.95, 0.3, 0.05, 0.03), 0.03),
        ReadWord("j", 40, Box(0.005, 0.9, 0.02, 0.02), None),  # outside a line
    )


def test_without_a_page_size_words_have_no_box() -> None:
    page = (
        "<span class='ocr_line' title='x_size 30'>"
        "<span class='ocrx_word' title='bbox 1 2 3 4; x_wconf 80'>Wort</span></span>"
    )
    assert hocr_words(page) == (ReadWord("Wort", 80),)
    # A word without a confidence is not one of Tesseract's.
    assert hocr_words("<span class='ocrx_word' title='bbox 1 2 3 4'>Wort</span>") == ()


def test_the_pay_slip_is_poorly_read_by_all_words_but_not_by_its_content() -> None:
    """The case it is shaped like: 10 % of all words unsure, the page well read by content."""
    words = hocr_words(hocr(PAYSLIP))
    reading = PageReading.of(1, words)
    assert (reading.words, reading.unsure) == (237, 23)
    assert reading.unsure_share > 0.09
    assert PageReading(1, reading.words, reading.unsure).poor(0.08)  # as before
    assert (reading.content, reading.content_unsure) == (200, 7)
    assert reading.share < 0.04
    assert not reading.poor(0.08)
    # What stays unsure: the leader read as letters, the rules' long marks, two true amounts.
    unsure = [word.text for word in words if word.unsure and word.size and word.size > 0.0065]
    assert {"«oso:", "see", "EEE", "412,33", "32,99", "cae"} <= set(unsure)


def test_a_broken_scan_stays_poorly_read_by_its_content() -> None:
    lines = [ScanLine(f"Zeile {n} mit Text 12,{n:02d}", confidence=40) for n in range(4)]
    lines += [ScanLine(f"Zeile {n} gut gelesen") for n in range(4, 20)]
    reading = PageReading.of(1, hocr_words(hocr(lines)))
    assert (reading.content, reading.content_unsure) == (84, 20)
    assert reading.poor(0.08)


def test_each_page_the_engine_kept(tmp_path: Path) -> None:
    kept = tmp_path / "ocrmypdf.io.x"
    kept.mkdir()
    (kept / "000003_ocr_hocr.hocr").write_text(hocr([ScanLine("Seite drei 3,00")]))
    (kept / "000001_ocr_hocr.hocr").write_text(TESSERACT)
    (kept / "notes_ocr_hocr.hocr").write_text(TESSERACT)  # not a page
    readings, pages = read_hocr(tmp_path)
    assert [reading.page for reading in readings] == [1, 3]
    assert readings[0] == PageReading(1, words=5, unsure=2, content=3, content_unsure=1)
    assert [page.page for page in pages] == [1, 3]
    assert [word.text for word in pages[1].words] == ["Seite", "drei", "3,00"]
