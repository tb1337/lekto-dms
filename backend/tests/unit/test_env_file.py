"""`lekto --env-file`: a file of KEY=value lines as a shell reads it, in place of the
environment's LEKTO_ variables."""

from pathlib import Path

import pytest

from lekto.composition.env_file import apply_env_file, read_env_file
from lekto.composition.errors import ConfigurationError


def test_lines_are_read_as_a_shell_reads_them(tmp_path: Path) -> None:
    path = tmp_path / "dev.env"
    path.write_text(
        "# the development instance\n"
        "\n"
        "LEKTO_DB_NAME=lekto_dev\n"
        "export LEKTO_LOG_LEVEL=INFO  # spoken\n"
        "LEKTO_EMBEDDING_QUERY_PREFIX='Instruct: find it\\nQuery:'\n"
        'LEKTO_ADMIN_PASSWORD="say \\"hi\\" for \\$5"\n'
        "LEKTO_LLM_API_KEY=\n"
        "  LEKTO_UI_DIR=../web/build\n"
    )
    assert read_env_file(path) == {
        "LEKTO_DB_NAME": "lekto_dev",
        "LEKTO_LOG_LEVEL": "INFO",
        "LEKTO_EMBEDDING_QUERY_PREFIX": "Instruct: find it\\nQuery:",
        "LEKTO_ADMIN_PASSWORD": 'say "hi" for $5',
        "LEKTO_LLM_API_KEY": "",
        "LEKTO_UI_DIR": "../web/build",
    }


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("no equals sign", "not KEY=value"),
        ("1KEY=x", "not KEY=value"),
        ("KEY='open", "single quote is not closed"),
        ('KEY="open', "double quote is not closed"),
        ("KEY=two words", "needs quotes"),
        ("KEY='a'b", "needs quotes"),
    ],
)
def test_a_line_that_is_no_setting_is_refused(tmp_path: Path, line: str, message: str) -> None:
    path = tmp_path / "dev.env"
    path.write_text(f"LEKTO_A=1\n{line}\n")
    with pytest.raises(ConfigurationError, match=f"dev.env:2: .*{message}"):
        read_env_file(path)


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="--env-file"):
        read_env_file(tmp_path / "missing.env")


def test_the_file_replaces_every_lekto_variable(tmp_path: Path) -> None:
    path = tmp_path / "dev.env"
    path.write_text("LEKTO_DB_NAME=lekto_dev\n")
    environ = {"LEKTO_DB_NAME": "lekto", "LEKTO_LOG_LEVEL": "DEBUG", "HOME": "/home/x"}
    apply_env_file(path, environ)
    assert environ == {"LEKTO_DB_NAME": "lekto_dev", "HOME": "/home/x"}
