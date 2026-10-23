"""The version: the repository carries a development version in all three parts; the image sets
the version of its release (`LEKTO_VERSION`)."""

import importlib
import json
import tomllib
from pathlib import Path

import pytest

import lekto

ROOT = Path(__file__).parents[3]
DEVELOPMENT = "0.0.0.dev0"


def test_the_three_parts_carry_the_development_version() -> None:
    backend = tomllib.loads((ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))
    migration = tomllib.loads((ROOT / "migration/pyproject.toml").read_text(encoding="utf-8"))
    web = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
    assert backend["project"]["version"] == DEVELOPMENT
    assert migration["project"]["version"] == DEVELOPMENT
    # The same version in the form of Semver, which npm requires.
    assert web["version"] == "0.0.0-dev.0"


def test_the_version_is_the_packages_without_one_from_the_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LEKTO_VERSION", raising=False)
    assert importlib.reload(lekto).__version__ == DEVELOPMENT


def test_the_image_sets_the_version_of_its_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEKTO_VERSION", "1.2.0-beta.1")
    try:
        assert importlib.reload(lekto).__version__ == "1.2.0-beta.1"
    finally:
        monkeypatch.delenv("LEKTO_VERSION")
        importlib.reload(lekto)
