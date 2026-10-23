from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lekto.core.domain.exchanges import ModelCall
from lekto.core.domain.reading import PageReading, PageWords


@dataclass(frozen=True, kw_only=True)
class VisionModel:
    """The vision language model an OCR engine can read pages with (`LEKTO_VLM_*`)."""

    model: str
    endpoint: str  # where the page images go (host and port, no credentials)


@dataclass(frozen=True, kw_only=True)
class VisionReading:
    """The pages were read by the vision language model: what was sent and received, one or
    more calls per page in page order (`prompt` is the version of the request)."""

    model: str
    endpoint: str
    prompt: str
    calls: tuple[ModelCall, ...]


@dataclass(frozen=True, kw_only=True)
class OcrResult:
    pages: int
    engine: str  # name and version of the engine, for the processing log
    pdfa: bool  # False if the archive could not be made PDF/A; it is a plain PDF then
    # Why the archive is not what was asked for, for the processing log: the reason it is not
    # PDF/A, or that a digital signature of the original was not carried over.
    note: str | None = None
    # How well each page the engine recognised was read; pages with text of their own are
    # not recognised and have none.
    readings: tuple[PageReading, ...] = ()
    # The words of each page Tesseract recognised, with confidence, box and line size; none
    # for pages with text of their own, and for pages the vision language model read.
    words: tuple[PageWords, ...] = ()
    # The text the PDF had was replaced by a reading of its own: the layer another OCR had put
    # over the scan (invisible text), or text that cannot be read.
    read_again: bool = False
    # Every page was read by the vision language model (`make_archive` with `vision`).
    vision: VisionReading | None = None
    # The colours were converted to RGB to make the archive PDF/A (a colour space PDF/A cannot
    # hold); `note` says so too.
    rgb: bool = False


class Ocr(Protocol):
    """Produces a searchable archive PDF with a text layer. First adapter: OCRmyPDF.

    Recognition runs outside the event loop (adapters use processes) and is limited in time.
    """

    @property
    def vision(self) -> VisionModel | None:
        """The vision language model pages can be read with; None if none is configured."""
        ...

    async def make_archive(
        self, source: Path, target: Path, *, media_type: str, vision: bool = False
    ) -> OcrResult:
        """Write the archive PDF of `source` (a PDF or an image of `media_type`) to `target`:
        PDF/A with a text layer. Pages that already contain text are not recognised again,
        unless it is the invisible layer another OCR put over a scan, or text that cannot be
        read (a font without a character map): that one is replaced by a reading of its own
        (`read_again`). Images become a PDF.

        With `vision` (a person asked for it), the vision language model reads every page from
        its image instead, text of its own or not; the text layer is the model's lines at the
        places it gives, `readings` count the words it could not read as unsure, and `vision`
        in the result holds what was sent. ValueError if no vision model is configured;
        LanguageModelError if the model cannot read a page (unreachable, an error, no usable
        answer), which may be temporary.

        A digitally signed original is processed anyway; the archive does not carry the
        signature (the original is never changed) and `note` says so. If PDF/A is not possible
        for the file, a plain PDF is written and `pdfa` is False, `note` naming the reason.
        `readings` tell how well each recognised page was read, `words` what Tesseract read on
        it.

        UnprocessableDocumentError if the file cannot be processed (damaged, encrypted);
        repeating would not help. TimeoutError if recognition takes too long. Other errors may
        be temporary. On error, `target` is not created.
        """
        ...
