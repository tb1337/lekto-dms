"""Reachability probes for integration tests, a free local port, and the mark for those that need
the OCR programs. Standard library and pytest only, no client libraries."""

import json
import shutil
import socket
import urllib.error
import urllib.request

import pytest

TIMEOUT = 3.0

# Postgres answers an SSLRequest with a single byte: 'S' (supported) or 'N' (not supported).
_POSTGRES_SSL_REQUEST = (8).to_bytes(4, "big") + (80877103).to_bytes(4, "big")

# Requests to the services of the compose network must never go through a configured proxy.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port() -> int:
    """A port on 127.0.0.1 that was free a moment ago; nobody listens on it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def postgres_answers(host: str, port: int) -> bool:
    """True if a Postgres server speaks on host:port."""
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT) as connection:
            connection.sendall(_POSTGRES_SSL_REQUEST)
            return connection.recv(1) in {b"S", b"N"}
    except OSError:
        return False


def http_status(url: str) -> int | None:
    """HTTP status of a GET request, also for error statuses; None if nothing answers."""
    try:
        with _opener.open(url, timeout=TIMEOUT) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:  # includes URLError and timeouts
        return None


def meilisearch_health(url: str) -> str | None:
    """The `status` reported by Meilisearch's `/health` endpoint; None if unreachable."""
    try:
        with _opener.open(url.rstrip("/") + "/health", timeout=TIMEOUT) as response:
            status = json.load(response).get("status")
    except (OSError, ValueError):
        return None
    return status if isinstance(status, str) else None


def ocr_programs_installed() -> bool:
    """True if Tesseract and Ghostscript, which OCRmyPDF calls, are on the path."""
    return all(shutil.which(program) for program in ("tesseract", "gs"))


requires_ocr = pytest.mark.skipif(
    not ocr_programs_installed(), reason="Tesseract or Ghostscript not installed"
)
"""Mark for tests (or `pytestmark` of a module) that run OCRmyPDF."""
