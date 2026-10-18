"""The OCR engine plugin of OCRmyPDF (`--plugin`) that has the vision language model read each
page (`vision`).

OCRmyPDF prepares every page as usual (rasterised, turned upright and deskewed; Tesseract still
tells the orientation and the skew) and hands its image to `generate_ocr`. The model's lines
become the page's OCR tree; the words of a line share its box by their length. OCRmyPDF writes
the text layer from it (its fpdf2 renderer). Each page leaves its record in the folder the
configuration names; a page the model cannot read leaves the reason there (`write_error`).
"""

import json
from pathlib import Path

from ocrmypdf import OcrOptions, hookimpl
from ocrmypdf.builtin_plugins.tesseract_ocr import TesseractOcrEngine
from ocrmypdf.hocrtransform import BoundingBox, OcrClass, OcrElement
from ocrmypdf.pluginspec import OcrEngine
from PIL import Image

from papiq.adapters.outbound.ocrmypdf.vision import (
    PROMPT,
    UNREADABLE,
    Line,
    VisionError,
    configuration,
    read_page,
    record_path,
    write_error,
)

_DEFAULT_DPI = 72  # of an image that states no resolution: a pixel per PDF point


def page_element(lines: list[Line], size: tuple[int, int], dpi: float, page: int) -> OcrElement:
    """The OCR tree of a page for OCRmyPDF: the lines, each with its words; a word read as
    `UNREADABLE` has no confidence."""
    width, height = size
    return OcrElement(
        ocr_class=OcrClass.PAGE,
        bbox=BoundingBox(left=0, top=0, right=width, bottom=height),
        dpi=dpi,
        page_number=page,
        children=[_line_element(line) for line in lines],
    )


def _line_element(line: Line) -> OcrElement:
    left, top, right, bottom = line.box
    step = (right - left) / len(line.text)
    words = []
    start = 0
    for word in line.text.split(" "):
        end = start + len(word)
        words.append(
            OcrElement(
                ocr_class=OcrClass.WORD,
                bbox=BoundingBox(
                    left=left + start * step, top=top, right=left + end * step, bottom=bottom
                ),
                text=word,
                confidence=0.0 if UNREADABLE in word else 1.0,
            )
        )
        start = end + 1
    return OcrElement(
        ocr_class=OcrClass.LINE,
        bbox=BoundingBox(left=left, top=top, right=right, bottom=bottom),
        children=words,
    )


class VisionOcrEngine(TesseractOcrEngine):
    """Reads each page with the vision language model; orientation, skew and the languages
    OCRmyPDF checks are still Tesseract's."""

    @staticmethod
    def version() -> str:
        settings, _ = configuration()
        return f"{settings.model} ({PROMPT})"

    @staticmethod
    def creator_tag(options: OcrOptions) -> str:
        return f"Papiq, vision language model {VisionOcrEngine.version()}"

    def __str__(self) -> str:
        return f"vision language model {VisionOcrEngine.version()}"

    @staticmethod
    def supports_generate_ocr() -> bool:
        return True

    @staticmethod
    def generate_ocr(
        input_file: Path, options: OcrOptions, page_number: int = 0
    ) -> tuple[OcrElement, str]:
        settings, records = configuration()
        page = page_number + 1
        try:
            lines, record = read_page(input_file, settings, page)
        except VisionError as error:
            write_error(records, page, str(error))
            raise
        record_path(records, page).write_text(json.dumps(record.to_json()), encoding="utf-8")
        with Image.open(input_file) as image:
            size = image.size
            dpi = image.info.get("dpi", (_DEFAULT_DPI, _DEFAULT_DPI))
        resolution = float(dpi[0] if isinstance(dpi, tuple) else dpi)
        text = "\n".join(line.text for line in lines)
        return page_element(lines, size, resolution, page_number), text

    @staticmethod
    def generate_hocr(
        input_file: Path, output_hocr: Path, output_text: Path, options: OcrOptions
    ) -> None:
        raise NotImplementedError("the vision engine reads pages through generate_ocr (fpdf2)")

    @staticmethod
    def generate_pdf(
        input_file: Path, output_pdf: Path, output_text: Path, options: OcrOptions
    ) -> None:
        raise NotImplementedError("the vision engine reads pages through generate_ocr (fpdf2)")


@hookimpl
def get_ocr_engine(options: OcrOptions | None) -> OcrEngine:
    return VisionOcrEngine()
