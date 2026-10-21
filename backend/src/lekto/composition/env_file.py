"""`lekto --env-file FILE`: the settings of a file of `KEY=value` lines, read as a shell reads
them with `set -a; . FILE`: comments, empty lines, `export`, a value in single quotes (as it is)
or double quotes (`\\"`, `\\\\`, `\\$` and `` \\` `` unescaped).

Only the command line reads such a file, for the development instance in the devcontainer,
whose environment holds the test settings; the services and the image take the environment as
it is. The file's `LEKTO_` variables replace all others: what it does not set is unset.
"""

import os
import re
from collections.abc import MutableMapping
from pathlib import Path

from lekto.composition.errors import ConfigurationError

PREFIX = "LEKTO_"
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ESCAPED = re.compile(r'\\([\\"$`])')
_UNQUOTED = re.compile(r"(\S*)(.*)", re.DOTALL)


def read_env_file(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigurationError(f"--env-file {path}: {error.strerror}") from None
    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        stripped = stripped.removeprefix("export ").lstrip()
        key, equals, raw = stripped.partition("=")
        if not equals or not _KEY.fullmatch(key):
            raise ConfigurationError(f"{path}:{number}: not KEY=value")
        try:
            values[key] = _value(raw)
        except ValueError as error:
            raise ConfigurationError(f"{path}:{number}: {key}: {error}") from None
    return values


def apply_env_file(path: Path, environ: MutableMapping[str, str] = os.environ) -> None:
    """Put the file's settings into the environment, in place of every `LEKTO_` variable."""
    values = read_env_file(path)
    for key in [key for key in environ if key.startswith(PREFIX) and key not in values]:
        del environ[key]
    environ.update(values)


def _value(raw: str) -> str:
    if raw.startswith("'"):
        end = raw.find("'", 1)
        if end < 0:
            raise ValueError("the single quote is not closed")
        value, rest = raw[1:end], raw[end + 1 :]
    elif raw.startswith('"'):
        end = _closing(raw)
        value, rest = _ESCAPED.sub(r"\1", raw[1:end]), raw[end + 1 :]
    else:
        unquoted = _UNQUOTED.fullmatch(raw)
        assert unquoted is not None  # matches anything
        value, rest = unquoted[1], unquoted[2]
    if rest.strip() and not (rest[:1].isspace() and rest.strip().startswith("#")):
        raise ValueError("a value with spaces needs quotes")
    return value


def _closing(raw: str) -> int:
    """Where the double quote that opens `raw` closes."""
    index = 1
    while index < len(raw):
        if raw[index] == "\\":
            index += 2
            continue
        if raw[index] == '"':
            return index
        index += 1
    raise ValueError("the double quote is not closed")
