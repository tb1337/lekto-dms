"""The second runs of OCRmyPDF (signed PDFs, failed PDF/A conversion) on a stand-in process:
which arguments go out, and what the result says. The real program runs in the integration
tests."""

import json
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from lekto.adapters.outbound.ocrmypdf import engine as module
from lekto.adapters.outbound.ocrmypdf.engine import (
    COLOUR_NOTE,
    COLOUR_OPTIONS,
    SIGNATURE_NOTE,
    OcrmypdfEngine,
    pdfa_reasons,
)
from lekto.adapters.outbound.ocrmypdf.vision import CONFIG_ENV, VisionSettings, write_error
from lekto.adapters.outbound.system import Completed
from lekto.core.domain import media_types
from lekto.core.domain.errors import LanguageModelError, UnprocessableDocumentError
from lekto.core.domain.reading import PageReading
from lekto.core.ports.ocr import OcrResult
from tests.builders import DEFAULT_SETTINGS

SIGNATURE = (
    "DigitalSignatureError: Input PDF has a digital signature. OCR would alter the document,\n"
    "invalidating the signature.\n"
)
COLOUR = (
    "ColorConversionNeededError: The input PDF has an unusual DeviceN color space that cannot "
    "be\nrepresented in PDF/A; the output may appear blank in some viewers\nsuch as Adobe "
    "Reader. Convert it to a common color space with\n--color-conversion-strategy (RGB, CMYK, "
    "or Gray), or use\n--output-type pdf to skip PDF/A conversion and retain the original\n"
    "color space.\n"
)
GHOSTSCRIPT = "\n".join(
    [
        "Postprocessing...",
        "Running: ['gs', '-dBATCH', '-dPDFA=2', '-o', '/tmp/x/pdfa.pdf', '/tmp/x/pdfa.ps']",
        "GPL Ghostscript 10.05.1 (2025-04-29)",
        "Copyright (C) 2025 Artifex Software, Inc.  All rights reserved.",
        "Processing pages 1 through 7.",
        "Page 1",
        "GPL Ghostscript 10.05.1: Setting Overprint Mode to 1",
        "not permitted in PDF/A-2, overprint mode not set",
        "Page 2",
        "GPL Ghostscript 10.05.1: Setting Overprint Mode to 1",
        "not permitted in PDF/A-2, overprint mode not set",
        "GPL Ghostscript 10.05.1: A CIDFont uses CID 0, which is not legal for PDF/A, "
        "reverting to normal PDF output.",
        "Page 3",
        "Output file is a valid PDF, but conversion to PDF/A did not succeed "
        "(issue: No PDF/A metadata in XMP)",
        "",
    ]
)


def hocr(*confidences: int) -> str:
    """A page of Tesseract's hOCR with a word of each confidence, and an empty one."""
    words = "".join(
        f"<span class='ocrx_word' id='word_1_{n}' title='bbox 1 2 3 4; x_wconf {c}'>"
        f"<strong>w{n}</strong></span>"
        for n, c in enumerate(confidences)
    )
    empty = "<span class='ocrx_word' id='word_1_x' title='bbox 1 2 3 4; x_wconf 5'> </span>"
    return f"<div class='ocr_page' id='page_1'><span class='ocr_line'>{words}{empty}</span></div>"


class Runs:
    """Scripted outcomes of `run_process`: one (exit code, stderr) per OCRmyPDF run; the output
    file is written when the run succeeds (0 or 10). `pages`: the hOCR per page a run keeps in
    its work folder, one mapping per run (none: no page recognised)."""

    def __init__(self, *outcomes: tuple[int, str]) -> None:
        self.outcomes = list(outcomes)
        self.pages: list[dict[int, str]] = []
        self.calls: list[list[str]] = []
        self.hidden_text = False  # the source carries the invisible layer of another OCR
        self.unreadable_text = False  # the source has text in a font without a character map
        self.vision_error: str | None = None  # what the vision plugin leaves of a failed page

    async def __call__(
        self, args: Sequence[str], *, timeout: timedelta, env: dict[str, str] | None = None
    ) -> Completed:
        if args[0] == "tesseract":
            return Completed(returncode=0, stdout="tesseract 5.5.0\n", stderr="")
        self.calls.append(list(args))
        code, stderr = self.outcomes.pop(0)
        assert env is not None and "--keep-temporary-files" in args
        kept = Path(env["TMPDIR"]) / "ocrmypdf.io.test"
        kept.mkdir()
        for page, content in (self.pages.pop(0) if self.pages else {}).items():
            (kept / f"{page:06d}_ocr_hocr.hocr").write_text(content)
        if code in (0, 10):
            Path(args[-1]).write_bytes(b"%PDF-1.7\n%%EOF\n")
        if self.vision_error is not None:
            write_error(Path(json.loads(env[CONFIG_ENV])["records"]), 1, self.vision_error)
        # As OCRmyPDF prints it: before the error, in a container with a line more.
        stderr = (
            f"Temporary working files retained at:\n{kept}\n"
            "OCRmyPDF is running in a Docker container, so the files will be inside the "
            "container.\n" + stderr
        )
        return Completed(returncode=code, stdout="", stderr=stderr)


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> Runs:
    runs = Runs()
    monkeypatch.setattr(module, "run_process", runs)
    monkeypatch.setattr(module, "count_pages", lambda path: 1)
    monkeypatch.setattr(module, "has_hidden_text", lambda path: runs.hidden_text)
    monkeypatch.setattr(module, "has_unreadable_text", lambda path: runs.unreadable_text)
    return runs


def engine(vision: VisionSettings | None = None) -> OcrmypdfEngine:
    return OcrmypdfEngine(
        languages=["deu"],
        timeout=timedelta(minutes=1),
        vision=vision,
        vision_timeout=DEFAULT_SETTINGS.vlm_timeout,
    )


async def read_with_the_model(tmp_path: Path) -> None:
    vision = VisionSettings(
        base_url="https://vlm.example/v1", model="vlm-1", timeout=timedelta(seconds=30)
    )
    await engine(vision).make_archive(
        tmp_path / "source.pdf", tmp_path / "archive.pdf", media_type=media_types.PDF, vision=True
    )


def options(call: list[str]) -> tuple[str, bool]:
    """Output type and whether signatures are invalidated."""
    return call[call.index("--output-type") + 1], "--invalidate-digital-signatures" in call


async def convert(runs: Runs, tmp_path: Path) -> tuple[OcrResult, Path]:
    target = tmp_path / "archive.pdf"
    result = await engine().make_archive(
        tmp_path / "source.pdf", target, media_type=media_types.PDF
    )
    return result, target


async def test_a_clean_run_is_pdfa_without_a_note(runs: Runs, tmp_path: Path) -> None:
    runs.outcomes = [(0, "")]
    result, target = await convert(runs, tmp_path)
    assert (result.pdfa, result.note, result.pages) == (True, None, 1)
    assert [options(call) for call in runs.calls] == [("pdfa", False)]
    assert target.exists() and [p.name for p in tmp_path.iterdir()] == ["archive.pdf"]


async def test_another_ocr_s_layer_is_read_again(runs: Runs, tmp_path: Path) -> None:
    runs.outcomes = [(0, ""), (0, "")]
    result, _ = await convert(runs, tmp_path)
    assert not result.read_again
    runs.hidden_text = True
    again, _ = await convert(runs, tmp_path)
    assert again.read_again
    first, second = runs.calls
    assert "--skip-text" in first and "--deskew" in first and "--redo-ocr" not in first
    # OCRmyPDF does not allow deskewing when it reads a page again.
    assert "--redo-ocr" in second and "--skip-text" not in second and "--deskew" not in second


async def test_text_that_cannot_be_read_is_recognised_from_the_images(
    runs: Runs, tmp_path: Path
) -> None:
    runs.outcomes = [(0, "")]
    runs.unreadable_text = runs.hidden_text = True
    result, _ = await convert(runs, tmp_path)
    assert (result.read_again, result.pdfa, result.note) == (True, True, module.UNREADABLE_NOTE)
    (call,) = runs.calls
    assert "--force-ocr" in call and "--deskew" in call
    assert "--skip-text" not in call and "--redo-ocr" not in call


async def test_the_last_run_s_hocr_tells_how_well_each_page_was_read(
    runs: Runs, tmp_path: Path
) -> None:
    runs.outcomes = [(2, SIGNATURE), (0, "")]
    runs.pages = [{1: hocr(10)}, {1: hocr(96, 41, 90), 3: hocr(59, 60)}]
    result, _ = await convert(runs, tmp_path)
    assert result.readings == (
        PageReading(page=1, words=3, unsure=1, content=3, content_unsure=1),
        PageReading(page=3, words=2, unsure=1, content=2, content_unsure=1),
    )
    assert [(page.page, [word.text for word in page.words]) for page in result.words] == [
        (1, ["w0", "w1", "w2"]),
        (3, ["w0", "w1"]),
    ]
    assert [p.name for p in tmp_path.iterdir()] == ["archive.pdf"]


async def test_where_the_files_were_kept_is_no_reason(runs: Runs, tmp_path: Path) -> None:
    runs.outcomes = [(15, "")]
    with pytest.raises(RuntimeError) as raised:
        await convert(runs, tmp_path)
    assert "retained" not in str(raised.value) and "container" not in str(raised.value)
    assert list(tmp_path.iterdir()) == []


async def test_a_signed_pdf_is_processed_again_without_its_signature(
    runs: Runs, tmp_path: Path
) -> None:
    runs.outcomes = [(2, SIGNATURE), (0, "")]
    result, _ = await convert(runs, tmp_path)
    assert (result.pdfa, result.note) == (True, SIGNATURE_NOTE)
    assert [options(call) for call in runs.calls] == [("pdfa", False), ("pdfa", True)]


def converts_colours(call: list[str]) -> bool:
    joined = " ".join(call)
    return " ".join(COLOUR_OPTIONS) in joined


async def test_a_colour_space_pdfa_cannot_hold_is_converted_to_rgb(
    runs: Runs, tmp_path: Path
) -> None:
    runs.outcomes = [(1, COLOUR), (0, "")]
    result, _ = await convert(runs, tmp_path)
    assert (result.pdfa, result.note) == (True, COLOUR_NOTE)
    assert [options(call) for call in runs.calls] == [("pdfa", False), ("pdfa", False)]
    assert [converts_colours(call) for call in runs.calls] == [False, True]


async def test_ocrmypdfs_own_fallback_for_a_colour_space_is_converted_too(
    runs: Runs, tmp_path: Path
) -> None:
    issue = (
        "Output file is a valid PDF, but conversion to PDF/A did not succeed (issue: color space)"
    )
    runs.outcomes = [(10, f"{issue}\n"), (0, "")]
    result, _ = await convert(runs, tmp_path)
    assert (result.pdfa, result.note) == (True, COLOUR_NOTE)
    assert [converts_colours(call) for call in runs.calls] == [False, True]


async def test_a_colour_space_that_converting_cannot_fix_falls_back_to_a_plain_pdf(
    runs: Runs, tmp_path: Path
) -> None:
    runs.outcomes = [(1, COLOUR), (1, COLOUR), (0, "")]
    result, _ = await convert(runs, tmp_path)
    assert result.pdfa is False
    assert result.note == "not PDF/A: the colour space of the file cannot be represented in PDF/A"
    assert [options(call) for call in runs.calls] == [
        ("pdfa", False),
        ("pdfa", False),
        ("pdf", False),
    ]
    assert [converts_colours(call) for call in runs.calls] == [False, True, False]


async def test_a_signed_pdf_with_such_colours_is_converted_without_its_signature(
    runs: Runs, tmp_path: Path
) -> None:
    runs.outcomes = [(2, SIGNATURE), (1, COLOUR), (0, "")]
    result, _ = await convert(runs, tmp_path)
    assert (result.pdfa, result.note) == (True, f"{SIGNATURE_NOTE}; {COLOUR_NOTE}")
    assert [options(call) for call in runs.calls] == [
        ("pdfa", False),
        ("pdfa", True),
        ("pdfa", True),
    ]


async def test_a_failed_pdfa_conversion_falls_back_to_a_plain_pdf(
    runs: Runs, tmp_path: Path
) -> None:
    runs.outcomes = [(1, "SomethingElseError: odd file\n"), (0, "")]
    result, _ = await convert(runs, tmp_path)
    assert result.pdfa is False
    assert result.note == "not PDF/A: SomethingElseError: odd file"
    assert [options(call) for call in runs.calls] == [("pdfa", False), ("pdf", False)]
    assert not any(converts_colours(call) for call in runs.calls)


async def test_a_signed_pdf_whose_pdfa_conversion_fails_gets_both(
    runs: Runs, tmp_path: Path
) -> None:
    runs.outcomes = [(2, SIGNATURE), (1, "SomethingElseError: odd file\n"), (0, "")]
    result, _ = await convert(runs, tmp_path)
    assert result.pdfa is False
    assert result.note == f"{SIGNATURE_NOTE}; not PDF/A: SomethingElseError: odd file"
    assert [options(call) for call in runs.calls] == [
        ("pdfa", False),
        ("pdfa", True),
        ("pdf", True),
    ]


async def test_ocrmypdfs_own_fallback_names_ghostscripts_reasons(
    runs: Runs, tmp_path: Path
) -> None:
    runs.outcomes = [(10, GHOSTSCRIPT)]
    result, _ = await convert(runs, tmp_path)
    assert result.pdfa is False
    assert result.note == (
        "not PDF/A: Setting Overprint Mode to 1 not permitted in PDF/A-2, overprint mode not "
        "set; A CIDFont uses CID 0, which is not legal for PDF/A, reverting to normal PDF output."
    )
    assert len(runs.calls) == 1


def test_pdfa_reasons_without_ghostscript_messages() -> None:
    assert pdfa_reasons(GHOSTSCRIPT.splitlines()[-1]) == "No PDF/A metadata in XMP"
    assert pdfa_reasons("nothing useful\n") == "Ghostscript could not convert the file"


async def test_other_input_errors_are_unprocessable_at_once(runs: Runs, tmp_path: Path) -> None:
    runs.outcomes = [(2, "InputFileError: not a PDF\n")]
    with pytest.raises(UnprocessableDocumentError, match="not a PDF"):
        await convert(runs, tmp_path)
    assert len(runs.calls) == 1
    assert list(tmp_path.iterdir()) == []


async def test_a_second_failure_is_an_error(runs: Runs, tmp_path: Path) -> None:
    runs.outcomes = [(1, "SomethingElseError: odd file\n"), (1, "BadArgsError: still no\n")]
    with pytest.raises(RuntimeError, match="exit code 1"):
        await convert(runs, tmp_path)
    assert len(runs.calls) == 2


async def test_a_page_the_model_cannot_read_fails_with_the_plugin_s_reason(
    runs: Runs, tmp_path: Path
) -> None:
    """From the plugin's file: the end of OCRmyPDF's output need not hold its exception."""
    runs.outcomes = [(15, "Traceback (most recent call last):\nBrokenProcessPool: a worker died\n")]
    runs.vision_error = "page 2: the vision language model: HTTP 503: down"
    with pytest.raises(LanguageModelError, match=r"^page 2: the vision language model: HTTP 503"):
        await read_with_the_model(tmp_path)
    assert list(tmp_path.iterdir()) == []


async def test_without_the_plugin_s_file_its_reason_comes_from_the_output(
    runs: Runs, tmp_path: Path
) -> None:
    runs.outcomes = [
        (15, "lekto.adapters.outbound.ocrmypdf.vision.VisionError: no usable configuration\n")
    ]
    with pytest.raises(LanguageModelError, match=r"^no usable configuration$"):
        await read_with_the_model(tmp_path)
