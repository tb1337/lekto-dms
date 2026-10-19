"""A vision language model that reads a page image: its lines, each with its box. OCRmyPDF uses
it as OCR engine (`plugin`) when a person has a document read by the model
(`OcrmypdfEngine.make_archive`, `vision`).

The image goes to the model at no more than `MAX_PIXELS`, so that the service does not scale it
once more, and the model gives the box of each line in pixels of the image it sees: boxes in
thousandths of the image drifted on a dense statement and on a photo, pixel boxes fit every
line (measured on the synthetic documents of issue #53).

The model answers in JSON (`SCHEMA`); an answer that does not fit is asked for once more. Each
page leaves a record in the folder the configuration names (`page-<n>.json`): its words, those
the model could not read (`UNREADABLE`) and what was sent and received. A page the model cannot
read leaves the reason there (`error.json`, `write_error`). The configuration comes
in the environment (`CONFIG_ENV`, the key apart in `KEY_ENV`), since the plugin runs in
OCRmyPDF's process and its workers. Neither the key nor the page's text is logged.
"""

import base64
import contextlib
import functools
import io
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx2
from PIL import Image

from lekto.adapters.outbound.http_client.openai import (
    ProtocolError,
    answer_content,
    auth_headers,
    chat_url,
    response_object,
)
from lekto.core.domain.exchanges import ModelCall

PROMPT = "read-1"
"""The version of `SYSTEM` and `SCHEMA`, for the processing log."""
CONFIG_ENV = "PAPIQ_OCR_VISION"
KEY_ENV = "PAPIQ_OCR_VISION_KEY"
MAX_PIXELS = 1_150_000  # what Claude looks at; larger images are scaled down by the service
MAX_EDGE = 1568
MAX_TOKENS = 16_000  # a dense page with its boxes takes about 2,500
UNREADABLE = "[unreadable]"
_ATTEMPTS = 2
_ERROR_FILE = "error.json"
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

SYSTEM = """\
You transcribe one page of a document (printed, scanned or photographed) into its text lines, \
each with where it stands on the page.

Write out all text on the page exactly as it is printed, in reading order, including the \
letterhead, page headers and footers and the small print. One entry per printed line: text \
that stands side by side in separate columns (a sidebar beside the letter, the cells of a \
table row) gives one entry per column. Do not correct, translate, summarise, explain or add \
anything; write text you cannot read as [unreadable].

For each line give its box: [left, top, right, bottom] of the printed text of that line, in \
pixels of the image as given (its size is stated with it), measured from the image's top left \
corner. The box encloses the ink of the line's characters tightly.

Answer as JSON: {"lines": [{"text": "...", "box": [left, top, right, bottom]}, ...]}. A page \
without text has no lines."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "box": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["text", "box"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


@dataclass(frozen=True, kw_only=True)
class VisionSettings:
    """An OpenAI-compatible endpoint with a vision model (`PAPIQ_VLM_*`); `timeout` per
    request."""

    base_url: str
    model: str
    api_key: str | None = None
    timeout: timedelta


class VisionError(RuntimeError):
    """The model could not read a page: unreachable, an error, or no usable answer."""


@dataclass(frozen=True)
class Line:
    """A line as the model read it; `box` is `(left, top, right, bottom)` in pixels."""

    text: str
    box: tuple[float, float, float, float]


@dataclass(frozen=True)
class PageRecord:
    """What the plugin leaves of a page: its `words`, how many the model could not read, and
    the requests with their answers (two after an answer that did not fit)."""

    page: int
    words: int
    unsure: int
    calls: tuple[ModelCall, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "words": self.words,
            "unsure": self.unsure,
            "calls": [call.to_json() for call in self.calls],
        }

    @classmethod
    def from_json(cls, data: Any) -> "PageRecord":
        return cls(
            page=int(data["page"]),
            words=int(data["words"]),
            unsure=int(data["unsure"]),
            calls=tuple(ModelCall.from_json(call) for call in data["calls"]),
        )


def environment(settings: VisionSettings, records: Path) -> dict[str, str]:
    """The environment for OCRmyPDF's process: where the plugin finds its configuration."""
    config = {
        "base_url": settings.base_url,
        "model": settings.model,
        "timeout": settings.timeout.total_seconds(),
        "records": str(records),
    }
    env = {CONFIG_ENV: json.dumps(config)}
    if settings.api_key:
        env[KEY_ENV] = settings.api_key
    return env


def configuration() -> tuple[VisionSettings, Path]:
    """The settings and the folder for the page records, from the environment."""
    try:
        config = json.loads(os.environ[CONFIG_ENV])
        settings = VisionSettings(
            base_url=str(config["base_url"]),
            model=str(config["model"]),
            api_key=os.environ.get(KEY_ENV) or None,
            timeout=timedelta(seconds=float(config["timeout"])),
        )
        return settings, Path(config["records"])
    except (KeyError, ValueError, TypeError) as error:
        raise VisionError(f"the vision plugin has no usable configuration in {CONFIG_ENV}") from (
            error
        )


def record_path(records: Path, page: int) -> Path:
    return records / f"page-{page}.json"


def write_error(records: Path, page: int, message: str) -> None:
    """Leave why page `page` could not be read in `records`, for the engine: its page and the
    message. Pages are read side by side; the first to fail keeps its reason."""
    with (
        contextlib.suppress(FileExistsError),
        (records / _ERROR_FILE).open("x", encoding="utf-8") as file,
    ):
        json.dump({"page": page, "message": message}, file)


def read_error(records: Path) -> str | None:
    """The message `write_error` left in `records`; None if no page failed."""
    try:
        data = json.loads((records / _ERROR_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    return str(data["message"])


def read_records(records: Path) -> list[PageRecord]:
    """The records of the pages read, in page order."""
    found = [
        PageRecord.from_json(json.loads(path.read_text(encoding="utf-8")))
        for path in records.glob("page-*.json")
    ]
    return sorted(found, key=lambda record: record.page)


def read_page(
    image_file: Path,
    settings: VisionSettings,
    page: int,
    *,
    transport: httpx2.BaseTransport | None = None,
) -> tuple[list[Line], PageRecord]:
    """The lines of the page in `image_file` (page `page`, from 1), their boxes in pixels of
    that image, and its record. VisionError if the model cannot read it."""
    with Image.open(image_file) as opened:
        size = opened.size
        sent = scaled(opened)
    buffer = io.BytesIO()
    sent.save(buffer, format="PNG")
    picture = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    text = f"Page {page}. The image is {sent.width} x {sent.height} pixels."
    calls: list[ModelCall] = []
    errors: list[str] = []
    for _ in range(_ATTEMPTS):
        asked = text if not errors else f"{text}\n\n{_retry_hint(errors[-1])}"
        content, data = _ask(settings, asked, picture, transport)
        usage = data.get("usage")
        calls.append(
            ModelCall(
                system=SYSTEM,
                user=f"{asked}\n[image: page {page}, {sent.width} x {sent.height} pixels, PNG]",
                answer=content,
                model=str(data.get("model") or settings.model),
                usage=usage if isinstance(usage, dict) else {},
            )
        )
        try:
            lines = parse_answer(content, sent.size)
        except ValueError as error:
            errors.append(str(error))
            continue
        factor = (size[0] / sent.width, size[1] / sent.height)
        lines = [_rescaled(line, factor, size) for line in lines]
        words = [word for line in lines for word in line.text.split(" ")]
        unsure = sum(UNREADABLE in word for word in words)
        return lines, PageRecord(page=page, words=len(words), unsure=unsure, calls=tuple(calls))
    raise VisionError(f"page {page}: the vision language model gave no usable answer: {errors[-1]}")


def scaled(image: Image.Image) -> Image.Image:
    """`image` at no more than `MAX_PIXELS` and `MAX_EDGE`, in a mode PNG keeps."""
    width, height = image.size
    factor = min(1.0, math.sqrt(MAX_PIXELS / (width * height)), MAX_EDGE / max(width, height))
    if image.mode not in ("1", "L", "RGB"):
        image = image.convert("RGB")
    if factor >= 1.0:
        return image.copy()
    target = (max(1, math.floor(width * factor)), max(1, math.floor(height * factor)))
    return image.convert("L" if image.mode == "1" else image.mode).resize(
        target, Image.Resampling.LANCZOS
    )


def parse_answer(content: str, size: tuple[int, int]) -> list[Line]:
    """The lines of the model's answer, their boxes within an image of `size`. ValueError if
    the answer does not fit `SCHEMA`."""
    try:
        data = json.loads(_FENCE.sub("", content.strip()))
    except ValueError:
        raise ValueError("the answer is not JSON") from None
    items = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("the answer has no list of lines")
    lines = []
    for item in items:
        text = item.get("text") if isinstance(item, dict) else None
        box = item.get("box") if isinstance(item, dict) else None
        if not (
            isinstance(text, str)
            and isinstance(box, list)
            and len(box) == 4
            and all(isinstance(value, int | float) and not isinstance(value, bool) for value in box)
        ):
            raise ValueError(f"a line needs a text and a box of four numbers: {item!r:.100}")
        text = " ".join(text.split())
        if text:
            lines.append(Line(text, _clamped([float(value) for value in box], size)))
    return lines


def _clamped(box: list[float], size: tuple[int, int]) -> tuple[float, float, float, float]:
    """`box` within an image of `size`, its edges in order, at least a pixel each way."""
    width, height = size
    left, right = sorted(min(max(value, 0.0), width) for value in (box[0], box[2]))
    top, bottom = sorted(min(max(value, 0.0), height) for value in (box[1], box[3]))
    right, bottom = max(right, min(left + 1, width)), max(bottom, min(top + 1, height))
    return left, top, right, bottom


def _rescaled(line: Line, factor: tuple[float, float], size: tuple[int, int]) -> Line:
    left, top, right, bottom = line.box
    box = [left * factor[0], top * factor[1], right * factor[0], bottom * factor[1]]
    return Line(line.text, _clamped(box, size))


def _retry_hint(error: str) -> str:
    return f"Your previous answer could not be used ({error}). Answer with the JSON only."


def _ask(
    settings: VisionSettings, text: str, picture: str, transport: httpx2.BaseTransport | None
) -> tuple[str, dict[str, Any]]:
    """The text of the model's answer to the page, and the whole answer; VisionError if there
    is none to read."""
    body = {
        "model": settings.model,
        "max_tokens": MAX_TOKENS,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "page_lines", "schema": SCHEMA, "strict": True},
        },
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": picture}},
                ],
            },
        ],
    }
    timeout = settings.timeout.total_seconds()
    client = (
        contextlib.nullcontext(_client(timeout))
        if transport is None
        else httpx2.Client(transport=transport, timeout=timeout)
    )
    try:
        with client as http:
            response = http.post(
                chat_url(settings.base_url), json=body, headers=auth_headers(settings.api_key)
            )
    except httpx2.TimeoutException:
        raise VisionError(f"the vision language model gave no answer within {timeout:g} s") from (
            None
        )
    except httpx2.HTTPError as failure:
        raise VisionError(
            f"the vision language model cannot be reached: {type(failure).__name__}"
        ) from None
    try:
        data = response_object(response)
        return answer_content(data), data
    except ProtocolError as problem:
        raise VisionError(f"the vision language model: {problem}") from None


@functools.cache
def _client(timeout: float) -> httpx2.Client:
    """One client per process (OCRmyPDF's workers each have theirs): its connections stay open
    from page to page."""
    return httpx2.Client(timeout=timeout)
