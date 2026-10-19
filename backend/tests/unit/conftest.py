import logging
import os
from collections.abc import Iterator

import pytest
import structlog

from tests.builders import SECRET_KEY, TRUSTED_PROXY


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The process environment (devcontainer, CI) must not leak into unit tests."""
    for name in list(os.environ):
        if name.upper().startswith("LEKTO_"):
            monkeypatch.delenv(name)
    # Required for the API; tests that check the requirement remove it.
    monkeypatch.setenv("LEKTO_SECRET_KEY", SECRET_KEY)
    monkeypatch.setenv("LEKTO_FORWARDED_ALLOW_IPS", TRUSTED_PROXY)


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:], root.level = handlers, level
    structlog.reset_defaults()
