"""A stand-in for a vision language model behind an OpenAI-compatible API, for tests that run
OCRmyPDF with the vision plugin: a local HTTP server that answers each page with fixed lines.

The lines are given in fractions of the page (`[left, top, right, bottom]`, 0 to 1) and sent
back in pixels of the image the request names, as the real model does.
"""

import http.server
import json
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

type Lines = Sequence[tuple[str, tuple[float, float, float, float]]]

LINES: Lines = (
    ("Rechnung Nummer 4711", (0.1, 0.11, 0.6, 0.14)),
    ("Lekto Testdokument", (0.1, 0.17, 0.55, 0.2)),
    ("Betrag 123,45 EUR", (0.1, 0.24, 0.5, 0.27)),
)


@dataclass
class VisionStub:
    """`pages`: the lines of each page in order (the last for any page after); `status`: an
    HTTP status to answer with instead; `requests`: what came in, `keys` the bearer tokens."""

    pages: list[Lines] = field(default_factory=lambda: [LINES])
    status: int = 200
    model: str = "stub-vlm"
    requests: list[dict[str, Any]] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    url: str = ""

    def answer(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self.requests.append(body)
        if self.status != 200:
            return self.status, {"error": {"message": "the stub is down"}}
        text = body["messages"][1]["content"][0]["text"]
        page = int(text.split(".", 1)[0].removeprefix("Page "))
        size = text.split("The image is ", 1)[1].split(" pixels", 1)[0]
        width, height = (int(value) for value in size.split(" x "))
        lines = self.pages[min(page, len(self.pages)) - 1]
        answer = {
            "lines": [
                {
                    "text": line,
                    "box": [
                        round(box[0] * width),
                        round(box[1] * height),
                        round(box[2] * width),
                        round(box[3] * height),
                    ],
                }
                for line, box in lines
            ]
        }
        return 200, {
            "model": self.model,
            "choices": [{"message": {"content": json.dumps(answer)}}],
            "usage": {"prompt_tokens": 1500, "completion_tokens": 120},
        }


@contextmanager
def serve(stub: VisionStub) -> Iterator[VisionStub]:
    """Serve `stub` on a free local port; `stub.url` is its base URL (with `/v1`)."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            stub.keys.append(self.headers.get("Authorization", "").removeprefix("Bearer "))
            status, answer = stub.answer(body)
            data = json.dumps(answer).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stub.url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield stub
    finally:
        server.shutdown()
        server.server_close()
