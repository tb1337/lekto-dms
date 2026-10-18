"""The vision language model's reading of a page: the request, the answer and its boxes, the
OCR tree OCRmyPDF gets."""

import base64
import io
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
from ocrmypdf.hocrtransform import BoundingBox
from PIL import Image

from papiq.adapters.outbound.ocrmypdf.plugin import page_element
from papiq.adapters.outbound.ocrmypdf.vision import (
    CONFIG_ENV,
    KEY_ENV,
    MAX_PIXELS,
    SYSTEM,
    Line,
    PageRecord,
    VisionError,
    VisionSettings,
    configuration,
    environment,
    parse_answer,
    read_page,
    read_records,
    record_path,
    scaled,
)
from papiq.composition.container import VISION_REQUEST_TIMEOUT

SETTINGS = VisionSettings(
    base_url="https://vlm.example/v1",
    model="vlm-1",
    api_key="secret",
    timeout=VISION_REQUEST_TIMEOUT,
)


def answer(lines: list[dict[str, Any]] | str, status: int = 200) -> httpx2.Response:
    content = lines if isinstance(lines, str) else json.dumps({"lines": lines})
    return httpx2.Response(
        status,
        json={
            "model": "vlm-1-2026",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 2000, "completion_tokens": 300},
        },
    )


@pytest.fixture
def page(tmp_path: Path) -> Path:
    """A page image of 2480 x 3508 pixels (A4 at 300 dpi)."""
    path = tmp_path / "page.png"
    Image.new("L", (2480, 3508), 255).save(path, dpi=(300, 300))
    return path


def test_the_answer_s_lines_with_their_boxes() -> None:
    content = json.dumps(
        {
            "lines": [
                {"text": "  Rechnung   4711 ", "box": [10, 20, 300, 40]},
                {"text": "", "box": [0, 0, 1, 1]},
                {"text": "Rand", "box": [-5, 990, 2000, 1200]},
                {"text": "verdreht", "box": [300, 60, 100, 50]},
            ]
        }
    )
    assert parse_answer(f"```json\n{content}\n```", (1000, 1000)) == [
        Line("Rechnung 4711", (10.0, 20.0, 300.0, 40.0)),
        Line("Rand", (0.0, 990.0, 1000.0, 1000.0)),
        Line("verdreht", (100.0, 50.0, 300.0, 60.0)),
    ]


@pytest.mark.parametrize(
    "content",
    [
        "Here is the page.",
        '{"text": "no lines"}',
        '{"lines": [{"text": "x"}]}',
        '{"lines": [{"text": "x", "box": [1, 2, 3]}]}',
        '{"lines": [{"text": "x", "box": [1, 2, 3, true]}]}',
    ],
)
def test_an_answer_that_does_not_fit(content: str) -> None:
    with pytest.raises(ValueError):
        parse_answer(content, (100, 100))


def test_a_box_keeps_at_least_a_pixel() -> None:
    (line,) = parse_answer('{"lines": [{"text": "x", "box": [5, 7, 5, 7]}]}', (100, 100))
    assert line.box == (5.0, 7.0, 6.0, 8.0)


def test_the_image_goes_at_about_a_megapixel() -> None:
    sent = scaled(Image.new("RGB", (2480, 3508), "white"))
    assert sent.width * sent.height <= MAX_PIXELS
    assert sent.width * sent.height > MAX_PIXELS * 0.99
    assert sent.size[0] / sent.size[1] == pytest.approx(2480 / 3508, abs=0.002)
    small = Image.new("1", (400, 300))
    assert scaled(small).size == (400, 300)
    assert scaled(Image.new("P", (400, 300))).mode == "RGB"


def test_a_page_is_read_and_its_boxes_scaled_back(page: Path) -> None:
    requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        body = json.loads(request.content)
        text = body["messages"][1]["content"][0]["text"]
        assert text.startswith("Page 2. The image is ")
        return answer([{"text": "Betrag 123,45 EUR [unreadable]", "box": [90, 451, 450, 477]}])

    lines, record = read_page(page, SETTINGS, 2, transport=httpx2.MockTransport(handle))
    (request,) = requests
    assert str(request.url) == "https://vlm.example/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer secret"
    body = json.loads(request.content)
    assert body["model"] == "vlm-1"
    assert "temperature" not in body
    assert body["response_format"]["type"] == "json_schema"
    assert body["messages"][0] == {"role": "system", "content": SYSTEM}
    picture = body["messages"][1]["content"][1]["image_url"]["url"]
    sent = Image.open(io.BytesIO(base64.b64decode(picture.split(",", 1)[1])))
    assert sent.width * sent.height <= MAX_PIXELS
    (line,) = lines
    factor = 2480 / sent.width
    assert line.text == "Betrag 123,45 EUR [unreadable]"
    assert line.box[0] == pytest.approx(90 * factor, rel=0.01)
    assert line.box[3] == pytest.approx(477 * 3508 / sent.height, rel=0.01)
    assert (record.page, record.words, record.unsure) == (2, 4, 1)
    (call,) = record.calls
    assert call.system == SYSTEM
    assert call.user.endswith(f"[image: page 2, {sent.width} x {sent.height} pixels, PNG]")
    assert call.model == "vlm-1-2026"
    assert call.usage == {"prompt_tokens": 2000, "completion_tokens": 300}


def test_an_answer_that_does_not_fit_is_asked_for_once_more(page: Path) -> None:
    answers = iter([answer("Sure! The page says: Rechnung"), answer([])])
    lines, record = read_page(
        page, SETTINGS, 1, transport=httpx2.MockTransport(lambda _: next(answers))
    )
    assert lines == []
    _, second = record.calls
    assert "could not be used (the answer is not JSON)" in second.user
    assert (record.words, record.unsure) == (0, 0)


def test_two_answers_that_do_not_fit_fail(page: Path) -> None:
    with pytest.raises(VisionError, match=r"page 1: .*no usable answer: the answer is not JSON"):
        read_page(page, SETTINGS, 1, transport=httpx2.MockTransport(lambda _: answer("no")))


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx2.Response(401, json={"error": {"message": "bad key"}}), "HTTP 401: bad key"),
        (httpx2.Response(200, text="<html>"), "not JSON"),
        (httpx2.Response(200, json={"choices": []}), "unusable response"),
    ],
)
def test_an_endpoint_that_fails(page: Path, response: httpx2.Response, message: str) -> None:
    with pytest.raises(VisionError, match=message):
        read_page(page, SETTINGS, 1, transport=httpx2.MockTransport(lambda _: response))


def test_an_endpoint_that_cannot_be_reached(page: Path) -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(VisionError, match="cannot be reached: ConnectError"):
        read_page(page, SETTINGS, 1, transport=httpx2.MockTransport(fail))


def test_the_configuration_goes_through_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = VisionSettings(
        base_url="https://vlm.example/v1", model="vlm-1", api_key="k", timeout=timedelta(seconds=90)
    )
    env = environment(settings, tmp_path)
    assert env[KEY_ENV] == "k"
    assert "k" not in json.loads(env[CONFIG_ENV]).values()
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert configuration() == (settings, tmp_path)
    monkeypatch.delenv(CONFIG_ENV)
    with pytest.raises(VisionError, match="no usable configuration"):
        configuration()


def test_the_records_of_the_pages_in_order(tmp_path: Path) -> None:
    for number in (2, 1):
        record = PageRecord(page=number, words=3, unsure=number - 1, calls=())
        record_path(tmp_path, number).write_text(json.dumps(record.to_json()))
    assert [(record.page, record.unsure) for record in read_records(tmp_path)] == [(1, 0), (2, 1)]


def test_the_words_of_a_line_share_its_box_by_length() -> None:
    lines = [Line("ab [unreadable] c", (100.0, 50.0, 270.0, 70.0))]
    tree = page_element(lines, (1000, 1400), 300.0, 0)
    assert tree.bbox == BoundingBox(left=0, top=0, right=1000, bottom=1400)
    assert (tree.dpi, tree.page_number) == (300, 0)
    (line,) = tree.lines
    assert line.bbox == BoundingBox(left=100, top=50, right=270, bottom=70)
    words = line.words
    assert [word.text for word in words] == ["ab", "[unreadable]", "c"]
    # 17 characters over 170 pixels: ten each, the spaces included.
    boxes = [word.bbox for word in words if word.bbox is not None]
    assert [(box.left, box.right) for box in boxes] == [
        (100, 120),
        (130, 250),
        (260, 270),
    ]
    assert [word.confidence for word in words] == [1.0, 0.0, 1.0]
