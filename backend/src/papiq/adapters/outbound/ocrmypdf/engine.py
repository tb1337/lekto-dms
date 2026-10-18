"""OCR with OCRmyPDF (Tesseract, Ghostscript), run as a child process per document.

`--skip-text` leaves pages that already have text alone; `--output-type pdfa` makes the archive
PDF/A. The output is written next to the target and renamed when complete. A PDF with invisible
text carries the layer of another OCR (a scanner's, an older archive's) that may be poor and
says nothing of how well it read: it gets `--redo-ocr` instead, which replaces that layer and
keeps visible text. OCRmyPDF does not deskew then (`--deskew` is not allowed with it). A PDF
whose text cannot be read (a font without a character map: its codes come out as control
characters) gets `--force-ocr`: `--skip-text` would take such a page as read and `--redo-ocr`
keeps visible text, so every page is recognised from its image and the archive holds the pages
as images (`UNREADABLE_NOTE`).

Two things make OCRmyPDF refuse or downgrade a file, and both get a second run:

- A digitally signed PDF (exit code 2, "digital signature"): the second run passes
  `--invalidate-digital-signatures`. The original is never changed; only the archive lacks the
  signature, and `OcrResult.note` says so.
- A file whose PDF/A conversion fails outright (exit code 1, e.g. an unusual colour space):
  the second run writes a plain PDF (`--output-type pdf`); `pdfa` is False and `note` names the
  reason. Exit code 10 means OCRmyPDF itself fell back to a plain PDF (Ghostscript refused a
  construct of the file); the reason is read from its output.

Images are prepared before OCRmyPDF sees them (`prepare_image`):

- The page size follows from the resolution. Photos often state none, or 72 dpi, which gives
  pages of several feet; tiny or huge pages are hard to read and the layout analysis of the
  parser takes their text for a picture. An image whose stated resolution gives a page outside
  `PLAUSIBLE_PAGE` is scaled to the long edge of A4. The resolution is always passed on, since
  OCRmyPDF refuses images that state 96 dpi or less.
- OCRmyPDF refuses transparency and some colour modes: transparent images are put on white,
  CMYK and high bit depths are converted. All pages of a multi-page TIFF are kept.

OCRmyPDF's exit codes tell permanent problems (damaged or encrypted input) from others.

When a person asks for it (`vision`), the vision language model reads every page instead of
Tesseract: `--force-ocr --deskew` with the plugin (`PLUGIN`) as OCR engine, so that every page
is read from its image, text of its own or not, and the archive holds the pages as images under
the model's text. The plugin runs in OCRmyPDF's process; its configuration goes there in the
environment, and it leaves a record of each page in a folder of our own: its words, the ones the
model could not read, and what was sent. Such a run has a time limit of its own
(`vision_timeout`). A page the model cannot read fails the run (exit code 15) with the plugin's
reason.

How well a page was read comes from Tesseract's hOCR, which OCRmyPDF keeps in its work folder
with `--keep-temporary-files` (`*_ocr_hocr.hocr`, one per page it recognised): the words with
a confidence and how many fall below `UNSURE_BELOW`. The work folder is one of our own
(`TMPDIR`), removed afterwards.
"""

import asyncio
import html
import importlib.metadata
import logging
import re
import shutil
import sys
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from PIL import Image, ImageSequence

from papiq.adapters.outbound.http_client import endpoint_of
from papiq.adapters.outbound.imaging import flatten_on_white
from papiq.adapters.outbound.ocrmypdf.vision import (
    PROMPT,
    PageRecord,
    VisionSettings,
    environment,
    read_records,
)
from papiq.adapters.outbound.pdfium import count_pages, has_hidden_text, has_unreadable_text
from papiq.adapters.outbound.system import Completed, run_process
from papiq.core.domain import media_types
from papiq.core.domain.errors import LanguageModelError, UnprocessableDocumentError
from papiq.core.domain.reading import PageReading
from papiq.core.ports.ocr import OcrResult, VisionModel, VisionReading

log = logging.getLogger(__name__)

# ocrmypdf.ExitCode
_BAD_ARGS = 1  # also raised for files that need other options, e.g. a colour conversion
_INPUT_FILE = 2
_ALREADY_DONE_OCR = 6
_ENCRYPTED_PDF = 8
_PDFA_CONVERSION_FAILED = 10
_UNPROCESSABLE = {
    _INPUT_FILE: "the file is damaged or not a valid document",
    _ALREADY_DONE_OCR: "the file cannot be processed",
    _ENCRYPTED_PDF: "the PDF is encrypted",
}
_SIGNATURE_HINT = "digital signature"
UNREADABLE_NOTE = (
    "the text in the PDF cannot be read (a font without a character map); every page was "
    "recognised from its image"
)
SIGNATURE_NOTE = (
    "the original is digitally signed; the archive does not carry the signature "
    "(the original is unchanged)"
)
# Known reasons a first run fails with exit code 1, in words for the processing log.
_KNOWN_ERRORS = {
    "ColorConversionNeededError": "the colour space of the file cannot be represented in PDF/A",
}
_ERROR_LINE = re.compile(r"^(\w+Error): ?(.*)$")
_GHOSTSCRIPT_LINE = re.compile(r"^GPL Ghostscript [\d.]+: (.*)$")
# Tesseract's confidence (0 to 100) below which a word counts as unsure.
UNSURE_BELOW = 60
_HOCR_FILE = "*_ocr_hocr.hocr"
_HOCR_WORD = re.compile(
    r"<span class=['\"]ocrx_word['\"][^>]*?x_wconf (\d+)[^>]*>(.*?)</span>", re.S
)
_TAG = re.compile(r"<[^>]+>")
# What `--keep-temporary-files` prints where it kept them, in the middle of the output (before
# an error), with a line about containers when it runs in one.
_KEPT = re.compile(
    r"^Temporary working files retained at:\n[^\n]*\n(?:OCRmyPDF is running in a [^\n]*\n)?",
    re.M,
)
_PDFA_ISSUE = re.compile(r"conversion to PDF/A did not succeed \(issue: (.+?)\)")
_VISION_ERROR = re.compile(r"^\S*VisionError: (.+)$", re.M)
PLUGIN = "papiq.adapters.outbound.ocrmypdf.plugin"
"""The plugin OCRmyPDF loads to read pages with the vision language model."""
_NOTE_MAX = 300

A4_LONG_EDGE = 11.69  # inches
PLAUSIBLE_PAGE = (3.0, 17.0)  # long edge in inches: from a receipt to A3


class OcrmypdfEngine:
    def __init__(
        self,
        *,
        languages: Sequence[str],
        timeout: timedelta,
        jobs: int = 1,
        vision: VisionSettings | None = None,
        vision_timeout: timedelta,
    ) -> None:
        """`languages`: Tesseract language codes, e.g. `deu`, `eng`. `jobs`: CPU cores for
        the pages of one document. `vision`: the model that reads pages when asked to, all
        pages of a document within `vision_timeout` (a setting, like `timeout`)."""
        if not languages:
            raise ValueError("at least one OCR language is needed")
        self._languages = "+".join(languages)
        self._timeout = timeout
        self._jobs = jobs
        self._vision = vision
        self._vision_timeout = vision_timeout
        self._engine: str | None = None

    @property
    def vision(self) -> VisionModel | None:
        if self._vision is None:
            return None
        return VisionModel(model=self._vision.model, endpoint=endpoint_of(self._vision.base_url))

    async def make_archive(
        self, source: Path, target: Path, *, media_type: str, vision: bool = False
    ) -> OcrResult:
        if vision and self._vision is None:
            raise ValueError("no vision language model is configured")
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp.pdf")
        prepared = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp.tiff")
        work = target.with_name(f".{target.name}.{uuid.uuid4().hex}.work")
        records = target.with_name(f".{target.name}.{uuid.uuid4().hex}.vision")
        try:
            extra: list[str] = []
            env: dict[str, str] = {}
            timeout = self._timeout
            unreadable = hidden = False
            if media_type != media_types.PDF:
                source, dpi = await asyncio.to_thread(prepare_image, source, prepared)
                extra = ["--image-dpi", str(dpi)]
            elif not vision:
                unreadable = await asyncio.to_thread(has_unreadable_text, source)
                hidden = not unreadable and await asyncio.to_thread(has_hidden_text, source)
            if vision:
                assert self._vision is not None
                await asyncio.to_thread(records.mkdir)
                mode = ["--force-ocr", "--deskew", "--plugin", PLUGIN]
                env = environment(self._vision, records)
                timeout = self._vision_timeout
            elif unreadable:
                mode = ["--force-ocr", "--deskew"]
            elif hidden:
                mode = ["--redo-ocr"]
            else:
                mode = ["--skip-text", "--deskew"]
            pdfa, notes = await self._convert(
                source, temporary, [*mode, *extra], work, env=env, timeout=timeout
            )
            if unreadable:
                notes = [UNREADABLE_NOTE, *notes]
            pages = await asyncio.to_thread(count_pages, temporary)
            read: list[PageRecord] = []
            if vision:
                read = await asyncio.to_thread(read_records, records)
                readings = tuple(
                    PageReading(page=record.page, words=record.words, unsure=record.unsure)
                    for record in read
                )
            else:
                readings = await asyncio.to_thread(read_hocr, work)
            await asyncio.to_thread(temporary.replace, target)
        finally:
            for path in (temporary, prepared):
                await asyncio.to_thread(path.unlink, missing_ok=True)
            for folder in (work, records):
                await asyncio.to_thread(shutil.rmtree, folder, ignore_errors=True)
        if not pdfa:
            log.warning("archive is not PDF/A", extra={"source": str(source), "notes": notes})
        reading = None
        if vision:
            assert self._vision is not None
            reading = VisionReading(
                model=self._vision.model,
                endpoint=endpoint_of(self._vision.base_url),
                prompt=PROMPT,
                calls=tuple(call for record in read for call in record.calls),
            )
        return OcrResult(
            pages=pages,
            engine=await self._engine_name(vision=vision),
            pdfa=pdfa,
            note=_join(notes),
            readings=readings,
            read_again=unreadable or hidden,
            vision=reading,
        )

    async def _convert(
        self,
        source: Path,
        output: Path,
        extra: Sequence[str],
        work: Path,
        *,
        env: dict[str, str],
        timeout: timedelta,
    ) -> tuple[bool, list[str]]:
        """Run OCRmyPDF, with a second run where it helps (see the module). Returns whether the
        output is PDF/A, and the notes for the processing log; `work` keeps the files of the
        last run."""
        notes: list[str] = []
        invalidate = False

        async def run(*, pdfa: bool, invalidate: bool) -> Completed:
            return await self._run(
                source,
                output,
                extra,
                work,
                pdfa=pdfa,
                invalidate=invalidate,
                env=env,
                timeout=timeout,
            )

        completed = await run(pdfa=True, invalidate=False)
        if completed.returncode == _INPUT_FILE and _SIGNATURE_HINT in completed.stderr:
            invalidate = True
            notes.append(SIGNATURE_NOTE)
            completed = await run(pdfa=True, invalidate=True)
        pdfa = True
        if completed.returncode == _BAD_ARGS:
            notes.append(f"not PDF/A: {_error_reason(completed.stderr)}")
            pdfa = False
            completed = await run(pdfa=False, invalidate=invalidate)
        code = completed.returncode
        if code in _UNPROCESSABLE:
            raise UnprocessableDocumentError(
                f"{_UNPROCESSABLE[code]}: {_last_line(completed.stderr)}"
            )
        if code not in (0, _PDFA_CONVERSION_FAILED):
            if failure := _VISION_ERROR.findall(completed.stderr):
                raise LanguageModelError(failure[-1].strip())
            raise RuntimeError(
                f"ocrmypdf failed with exit code {code}: {_last_line(completed.stderr)}"
            )
        if code == _PDFA_CONVERSION_FAILED:
            pdfa = False
            notes.append(f"not PDF/A: {pdfa_reasons(completed.stderr)}")
        return pdfa, notes

    async def _run(
        self,
        source: Path,
        output: Path,
        extra: Sequence[str],
        work: Path,
        *,
        pdfa: bool,
        invalidate: bool,
        env: dict[str, str],
        timeout: timedelta,
    ) -> Completed:
        """One run of OCRmyPDF, its work folder kept in an empty `work` (for the hOCR); `env`
        adds to the environment."""
        await asyncio.to_thread(_empty_folder, work)
        args = [
            sys.executable,
            "-m",
            "ocrmypdf",
            "-v1",  # Ghostscript's messages name the reason when PDF/A fails
            "--keep-temporary-files",  # the hOCR tells how well each page was read
            "--output-type",
            "pdfa" if pdfa else "pdf",
            "--rotate-pages",
            "--language",
            self._languages,
            "--jobs",
            str(self._jobs),
            *extra,
        ]
        if invalidate:
            args.append("--invalidate-digital-signatures")
        completed = await run_process(
            [*args, str(source), str(output)], timeout=timeout, env={**env, "TMPDIR": str(work)}
        )
        # Where it kept the files is no reason for anything.
        return replace(completed, stderr=_KEPT.sub("", completed.stderr))

    async def _engine_name(self, *, vision: bool = False) -> str:
        if self._engine is None:
            tesseract = await run_process(["tesseract", "--version"], timeout=timedelta(seconds=30))
            first = (tesseract.stdout or tesseract.stderr).strip().splitlines()
            self._engine = (
                f"ocrmypdf {importlib.metadata.version('ocrmypdf')}, "
                f"{first[0] if first else 'tesseract (unknown version)'}"
            )
        if vision:
            assert self._vision is not None
            return f"{self._engine}, vision language model {self._vision.model} ({PROMPT})"
        return self._engine


def read_hocr(work: Path) -> tuple[PageReading, ...]:
    """How well each page was read, from the hOCR files OCRmyPDF kept in `work`; none for
    pages it did not recognise (they have text of their own)."""
    readings: list[PageReading] = []
    for path in work.glob(f"**/{_HOCR_FILE}"):
        page = path.name.split("_", 1)[0]
        if not page.isdigit():
            continue
        confidences = [
            int(confidence)
            for confidence, word in _HOCR_WORD.findall(path.read_text("utf-8", errors="replace"))
            if html.unescape(_TAG.sub("", word)).strip()
        ]
        unsure = sum(confidence < UNSURE_BELOW for confidence in confidences)
        readings.append(PageReading(page=int(page), words=len(confidences), unsure=unsure))
    if not readings and not any(work.glob("*/")):
        log.warning("ocrmypdf kept no work folder; how well the pages were read is unknown")
    return tuple(sorted(readings, key=lambda reading: reading.page))


def _empty_folder(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir()


def prepare_image(source: Path, prepared: Path) -> tuple[Path, int]:
    """The image to give OCRmyPDF and its resolution. `source` itself if it can be used as it
    is, otherwise a TIFF written to `prepared`. UnprocessableDocumentError if the image cannot
    be read."""
    try:
        with Image.open(source) as image:
            dpi = image_dpi(image.size, image.info.get("dpi"))
            frames = [frame.copy() for frame in ImageSequence.Iterator(image)]
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise UnprocessableDocumentError(f"the image cannot be read: {error}") from None
    converted = [_ocr_ready(frame) for frame in frames]
    if len(frames) == 1 and converted[0] is frames[0]:
        return source, dpi
    first, *rest = converted
    first.save(
        prepared, "TIFF", save_all=True, append_images=rest, dpi=(dpi, dpi), compression="tiff_lzw"
    )
    return prepared, dpi


def image_dpi(size: tuple[int, int], stated: object) -> int:
    """The resolution for an image of `size` pixels that states `stated` (Pillow's `dpi`)."""
    long_edge = max(size)
    if isinstance(stated, tuple) and stated:
        resolution = min(float(value) for value in stated)
        if resolution > 0 and PLAUSIBLE_PAGE[0] <= long_edge / resolution <= PLAUSIBLE_PAGE[1]:
            return max(1, round(resolution))
    return max(1, round(long_edge / A4_LONG_EDGE))


def pdfa_reasons(stderr: str) -> str:
    """Why OCRmyPDF (exit code 10) wrote a plain PDF, from its verbose output: Ghostscript's
    messages about PDF/A, else the issue OCRmyPDF names, else a generic word."""
    reasons: list[str] = []
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    for number, line in enumerate(lines):
        match = _GHOSTSCRIPT_LINE.match(line)
        if match is None:
            continue
        message = match.group(1)
        # Ghostscript wraps a message over two lines.
        if number + 1 < len(lines) and not _GHOSTSCRIPT_LINE.match(lines[number + 1]):
            follower = lines[number + 1]
            if "PDF/A" in follower and not follower.startswith("Page "):
                message = f"{message} {follower}"
        if "PDF/A" in message and message not in reasons:
            reasons.append(message)
    if not reasons:
        issue = _PDFA_ISSUE.search(stderr)
        reasons.append(issue.group(1) if issue else "Ghostscript could not convert the file")
    return "; ".join(reasons)


def _error_reason(stderr: str) -> str:
    """The error OCRmyPDF reported, in words where known, else its first line."""
    for line in stderr.strip().splitlines():
        match = _ERROR_LINE.match(line.strip())
        if match is not None:
            name, rest = match.groups()
            return _KNOWN_ERRORS.get(name, f"{name}: {rest}".strip(": "))
    return _last_line(stderr)


def _join(notes: Sequence[str]) -> str | None:
    if not notes:
        return None
    text = "; ".join(notes)
    return text if len(text) <= _NOTE_MAX else text[: _NOTE_MAX - 1] + "…"


def _ocr_ready(image: Image.Image) -> Image.Image:
    """`image` itself if OCRmyPDF takes it, otherwise a converted copy."""
    image = flatten_on_white(image)
    if image.mode in ("1", "L", "RGB", "P"):
        return image
    if image.mode.startswith(("I", "F")):
        return image.convert("L")
    return image.convert("RGB")  # CMYK, YCbCr, LAB, HSV


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "no details"
