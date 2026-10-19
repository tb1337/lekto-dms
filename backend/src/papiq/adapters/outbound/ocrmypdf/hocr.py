"""How well Tesseract read each page, from the hOCR OCRmyPDF keeps in its work folder with
`--keep-temporary-files` (`*_ocr_hocr.hocr`, one per page it recognised).

Each word (`ocrx_word`) has a confidence (`x_wconf`) and a box (`bbox`, in pixels of the page
image, `ocr_page`); each line (`ocr_line`, or a heading, caption or floating text) its height
(`x_size`). Boxes and heights become shares of the page, like the places of quotes: the image
Tesseract read is the page as the archive shows it (rotated and deskewed as there).
"""

import logging
import re
from html.parser import HTMLParser
from pathlib import Path

from papiq.core.domain.locations import Box
from papiq.core.domain.reading import PageReading, PageWords, ReadWord

log = logging.getLogger(__name__)

HOCR_FILE = "*_ocr_hocr.hocr"
_LINES = frozenset({"ocr_line", "ocr_header", "ocr_caption", "ocr_textfloat"})
_BBOX = re.compile(r"\bbbox (-?\d+) (-?\d+) (-?\d+) (-?\d+)")
_CONFIDENCE = re.compile(r"\bx_wconf (-?\d+)")
_SIZE = re.compile(r"\bx_size ([\d.]+)")


def read_hocr(work: Path) -> tuple[tuple[PageReading, ...], tuple[PageWords, ...]]:
    """How well each page was read and its words, from the hOCR files OCRmyPDF kept in `work`;
    none for pages it did not recognise (they have text of their own)."""
    pages: list[PageWords] = []
    for path in work.glob(f"**/{HOCR_FILE}"):
        page = path.name.split("_", 1)[0]
        if not page.isdigit() or int(page) < 1:
            continue
        pages.append(PageWords(int(page), hocr_words(path.read_text("utf-8", errors="replace"))))
    if not pages and not any(work.glob("*/")):
        log.warning("ocrmypdf kept no work folder; how well the pages were read is unknown")
    pages.sort(key=lambda item: item.page)
    return tuple(PageReading.of(item.page, item.words) for item in pages), tuple(pages)


def hocr_words(content: str) -> tuple[ReadWord, ...]:
    """The words of a page of hOCR that hold some text, in its order."""
    parser = _HocrParser()
    parser.feed(content)
    parser.close()
    return tuple(parser.words)


class _HocrParser(HTMLParser):
    """Collects the words with the size of their line and the page's."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.words: list[ReadWord] = []
        self._page: tuple[int, int, int, int] | None = None
        self._open: list[tuple[str, str]] = []  # tag and hOCR class of each open element
        self._sizes: list[float | None] = []  # the size of each open line
        self._word: tuple[str, list[str]] | None = None  # the title and text of the open word

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        kind = (values.get("class") or "").strip()
        title = values.get("title") or ""
        self._open.append((tag, kind))
        if kind == "ocr_page" and (box := _BBOX.search(title)) is not None:
            self._page = (int(box[1]), int(box[2]), int(box[3]), int(box[4]))
        elif kind in _LINES:
            size = _SIZE.search(title)
            self._sizes.append(float(size[1]) if size else None)
        elif kind == "ocrx_word":
            self._word = (title, [])

    def handle_endtag(self, tag: str) -> None:
        # Close up to the matching element (hOCR is XHTML, but stay lenient); a stray end
        # tag closes nothing.
        if all(open_tag != tag for open_tag, _ in self._open):
            return
        while self._open:
            open_tag, kind = self._open.pop()
            if kind in _LINES and self._sizes:
                self._sizes.pop()
            elif kind == "ocrx_word":
                self._finish_word()
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._word is not None:
            self._word[1].append(data)

    def _finish_word(self) -> None:
        if self._word is None:
            return
        title, parts = self._word
        self._word = None
        text = " ".join("".join(parts).split())
        confidence = _CONFIDENCE.search(title)
        if not text or confidence is None:
            return
        size = self._sizes[-1] if self._sizes else None
        self.words.append(ReadWord(text, int(confidence[1]), self._box(title), self._share(size)))

    def _box(self, title: str) -> Box | None:
        box = _BBOX.search(title)
        if box is None or self._page is None:
            return None
        left, top, right, bottom = self._page
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            return None
        return Box.clamped(
            (int(box[1]) - left) / width,
            (int(box[2]) - top) / height,
            (int(box[3]) - left) / width,
            (int(box[4]) - top) / height,
        )

    def _share(self, size: float | None) -> float | None:
        if size is None or self._page is None or self._page[3] <= self._page[1]:
            return None
        return round(size / (self._page[3] - self._page[1]), 5)
