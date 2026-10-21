"""Configuration: environment variables (`LEKTO_MIGRATION_*`) and command-line options. The API
keys come from the environment or a file, never from an option, and are never written anywhere."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

PREFIX = "LEKTO_MIGRATION_"


class ConfigError(Exception):
    pass


def secret(env: Mapping[str, str], name: str) -> str | None:
    """`LEKTO_MIGRATION_<NAME>`, or the content of the file `LEKTO_MIGRATION_<NAME>_FILE`; both
    set is an error."""
    value, file = env.get(PREFIX + name), env.get(f"{PREFIX}{name}_FILE")
    if value and file:
        raise ConfigError(f"set only one of {PREFIX}{name} and {PREFIX}{name}_FILE")
    if file:
        try:
            return Path(file).read_text(encoding="utf-8").strip() or None
        except OSError as error:
            raise ConfigError(f"cannot read {PREFIX}{name}_FILE: {error.strerror}") from None
    return value.strip() if value and value.strip() else None


_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ESCAPED = re.compile(r'\\([\\"$`])')
_UNQUOTED = re.compile(r"(\S*)(.*)", re.DOTALL)


def env_file(path: Path, environ: Mapping[str, str]) -> dict[str, str]:
    """`--env-file`: the environment with the `LEKTO_` variables of a file of `KEY=value` lines
    (read as a shell reads them with `set -a; . FILE`) in place of its own, as `lekto
    --env-file` does: for the development instance in the devcontainer."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"--env-file {path}: {error.strerror}") from None
    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, equals, raw = stripped.removeprefix("export ").lstrip().partition("=")
        if not equals or not _KEY.fullmatch(key):
            raise ConfigError(f"{path}:{number}: not KEY=value")
        try:
            values[key] = _value(raw)
        except ValueError as error:
            raise ConfigError(f"{path}:{number}: {key}: {error}") from None
    kept = {key: value for key, value in environ.items() if not key.startswith("LEKTO_")}
    return kept | values


def _value(raw: str) -> str:
    if raw.startswith("'"):
        end = raw.find("'", 1)
        if end < 0:
            raise ValueError("the single quote is not closed")
        value, rest = raw[1:end], raw[end + 1 :]
    elif raw.startswith('"'):
        end = 1
        while end < len(raw) and raw[end] != '"':
            end += 2 if raw[end] == "\\" else 1
        if end >= len(raw):
            raise ValueError("the double quote is not closed")
        value, rest = _ESCAPED.sub(r"\1", raw[1:end]), raw[end + 1 :]
    else:
        unquoted = _UNQUOTED.fullmatch(raw)
        assert unquoted is not None  # matches anything
        value, rest = unquoted[1], unquoted[2]
    if rest.strip() and not (rest[:1].isspace() and rest.strip().startswith("#")):
        raise ValueError("a value with spaces needs quotes")
    return value


def public(url: str | None) -> str | None:
    """The address without user name and password, for the state file and the reports."""
    if not url:
        return url
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


@dataclass(frozen=True)
class Config:
    """How a command runs; what is taken over and how is the plan's (`plan`)."""

    paperless_url: str
    lekto_url: str | None
    state: Path
    report_dir: Path
    paperless_token: str = field(repr=False, default="")
    lekto_token: str | None = field(repr=False, default=None)
    plan: Path = Path("migration-plan.yaml")
    concurrency: int = 4
    limit: int | None = None
    pipeline_timeout: float = 3600.0
    download: bool = False  # check: download the originals and check the files
    yes: bool = False  # write without asking
    reupload: bool = False  # run: upload a document again that was deleted in Lekto

    @classmethod
    def load(
        cls,
        *,
        paperless_url: str | None,
        lekto_url: str | None,
        state: Path,
        report_dir: Path,
        plan: Path = Path("migration-plan.yaml"),
        concurrency: int = 4,
        limit: int | None = None,
        pipeline_timeout: float = 3600.0,
        download: bool = False,
        yes: bool = False,
        reupload: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> "Config":
        env = os.environ if env is None else env
        paperless = paperless_url or env.get(PREFIX + "PAPERLESS_URL")
        lekto = lekto_url or env.get(PREFIX + "LEKTO_URL")
        if not paperless:
            raise ConfigError(
                f"the Paperless URL is missing ({PREFIX}PAPERLESS_URL or --paperless-url)"
            )
        token = secret(env, "PAPERLESS_TOKEN")
        if not token:
            raise ConfigError(f"the Paperless API key is missing ({PREFIX}PAPERLESS_TOKEN)")
        if concurrency < 1:
            raise ConfigError("the concurrency is at least 1")
        return cls(
            paperless_url=paperless.rstrip("/"),
            lekto_url=lekto.rstrip("/") if lekto else None,
            state=state,
            report_dir=report_dir,
            paperless_token=token,
            lekto_token=secret(env, "LEKTO_TOKEN"),
            plan=plan,
            concurrency=concurrency,
            limit=limit,
            pipeline_timeout=pipeline_timeout,
            download=download,
            yes=yes,
            reupload=reupload,
        )
