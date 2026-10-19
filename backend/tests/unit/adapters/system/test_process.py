import json
import sys
from datetime import timedelta

import pytest

from lekto.adapters.outbound.system import run_process

SHOW_ENVIRONMENT = (
    "import json, os; "
    "print(json.dumps({k: v for k, v in os.environ.items() "
    "if k.startswith('LEKTO_') or k == 'PATH'}))"
)


async def test_a_child_gets_no_lekto_settings_but_what_the_caller_adds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OCRmyPDF, Ghostscript and Tesseract process documents of unknown origin; the secret key
    and the credentials stay out of their reach."""
    monkeypatch.setenv("LEKTO_SECRET_KEY", "the-key")
    monkeypatch.setenv("LEKTO_DB_PASSWORD_FILE", "/run/secrets/db")
    completed = await run_process(
        [sys.executable, "-I", "-c", SHOW_ENVIRONMENT],
        timeout=timedelta(seconds=30),
        env={"LEKTO_OCR_VISION": "{}"},
    )
    assert completed.returncode == 0, completed.stderr
    seen = json.loads(completed.stdout)
    assert "LEKTO_SECRET_KEY" not in seen
    assert "LEKTO_DB_PASSWORD_FILE" not in seen
    assert seen["LEKTO_OCR_VISION"] == "{}"
    assert "PATH" in seen


async def test_a_child_that_takes_too_long_is_killed() -> None:
    with pytest.raises(TimeoutError, match="did not finish"):
        await run_process(
            [sys.executable, "-I", "-c", "import time; time.sleep(30)"],
            timeout=timedelta(milliseconds=200),
        )
