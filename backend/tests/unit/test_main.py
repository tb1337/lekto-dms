import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from lekto.adapters.outbound.memory import FakeLogoFetcher, FakeOcr, FakeParser, MemorySearchIndex
from lekto.composition import container
from lekto.composition.__main__ import main
from tests.builders import PASSWORD, SECRET_KEY, TRUSTED_PROXY


@pytest.fixture
def sqlite_instance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A migrated SQLite database in `tmp_path`; OCR and parser are fakes."""
    monkeypatch.setenv("LEKTO_DB_SQLITE_PATH", str(tmp_path / "lekto.db"))
    monkeypatch.setitem(container.OCR_ENGINES, "ocrmypdf", lambda _: FakeOcr())
    monkeypatch.setitem(container.PARSERS, "layout", lambda _: FakeParser())
    assert main(["migrate"]) == 0


def test_valid_configuration_exits_zero_and_masks_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    secret = tmp_path / "key"
    secret.write_text("top-secret")
    monkeypatch.setenv("LEKTO_MEILISEARCH_API_KEY_FILE", str(secret))
    monkeypatch.setenv("LEKTO_DB_TYPO", "x")

    assert main() == 0

    err = capsys.readouterr().err
    assert "top-secret" not in err
    events = [json.loads(line) for line in err.splitlines()]
    assert [e["event"] for e in events] == ["unknown configuration variable", "configuration valid"]
    assert events[0]["variable"] == "LEKTO_DB_TYPO"
    assert events[1]["meilisearch_api_key"] == "**********"


def test_external_language_models_are_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LEKTO_LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("LEKTO_LLM_MODEL", "large")
    monkeypatch.setenv("LEKTO_EMBEDDING_BASE_URL", "http://10.30.2.15:11434/v1")
    monkeypatch.setenv("LEKTO_EMBEDDING_MODEL", "small")

    assert main() == 0

    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    warnings = [e for e in events if e["level"] == "warning"]
    assert [(e["variable"], e["host"]) for e in warnings] == [
        ("LEKTO_LLM_BASE_URL", "api.example.com")
    ]
    assert "outside the local network" in warnings[0]["event"]


def test_invalid_configuration_exits_one_with_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LEKTO_DB_TYPE", "mysql")

    assert main() == 1

    assert "LEKTO_DB_TYPE" in capsys.readouterr().err


def test_migrate_sets_up_an_empty_sqlite_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "data" / "lekto.db"
    monkeypatch.setenv("LEKTO_DB_SQLITE_PATH", str(path))

    assert main(["migrate"]) == 0
    assert main(["migrate"]) == 0  # up to date: nothing to do

    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert {"documents", "jobs", "outbox", "alembic_version"} <= tables
    events = [json.loads(line)["event"] for line in capsys.readouterr().err.splitlines()]
    assert events.count("database migrated") == 2


def test_reindex_needs_a_search_index(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["reindex"]) == 1
    assert "LEKTO_MEILISEARCH_URL is not set" in capsys.readouterr().err


def test_train_needs_a_classifier(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LEKTO_CLASSIFIER", "none")
    assert main(["train"]) == 1
    assert "LEKTO_CLASSIFIER is none" in capsys.readouterr().err


@pytest.mark.usefixtures("sqlite_instance")
def test_train_without_confirmed_documents_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["train"]) == 1
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert "training the classifier failed" in [event["event"] for event in events]


@pytest.mark.usefixtures("sqlite_instance")
def test_render_pages_queues_the_documents_without_page_images(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["render-pages"]) == 0

    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [e["documents"] for e in events if e["event"] == "render-pages queued"] == [0]


@pytest.mark.usefixtures("sqlite_instance")
def test_read_facts_queues_the_documents_to_read_the_facts_of(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["read-facts"]) == 0

    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [e["documents"] for e in events if e["event"] == "read-facts queued"] == [0]


@pytest.mark.usefixtures("sqlite_instance")
def test_fetch_logos_queues_the_contacts_without_a_logo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(container.LOGO_FETCHERS, "httpx2", lambda _: FakeLogoFetcher())

    # Off by default: Lekto asks no website.
    assert main(["fetch-logos"]) == 1
    assert "set LEKTO_LOGO_FETCH=true" in capsys.readouterr().err

    monkeypatch.setenv("LEKTO_LOGO_FETCH", "true")
    assert main(["fetch-logos"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [e["contacts"] for e in events if e["event"] == "fetch-logos queued"] == [0]


@pytest.mark.usefixtures("sqlite_instance")
def test_reparse_queues_the_documents_to_read_again(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["reparse"]) == 0

    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [e["documents"] for e in events if e["event"] == "reparse queued"] == [0]


@pytest.mark.usefixtures("sqlite_instance")
def test_reindex_rebuilds_the_index(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LEKTO_MEILISEARCH_URL", "http://meilisearch:7700")
    index = MemorySearchIndex()
    monkeypatch.setitem(container.SEARCH_INDEXES, "meilisearch", lambda _: container.Opened(index))

    assert main(["reindex"]) == 0

    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    done = [event for event in events if event["event"] == "reindex finished"]
    assert [(e["documents"], e["queued"], e["removed"]) for e in done] == [(0, 0, 0)]


def test_failed_migration_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in {
        "DB_TYPE": "postgres",
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "1",  # nothing listens here
        "DB_NAME": "lekto",
        "DB_USER": "lekto",
        "DB_PASSWORD": "secret",
    }.items():
        monkeypatch.setenv(f"LEKTO_{name}", value)

    assert main(["migrate"]) == 1

    assert "database migration failed" in capsys.readouterr().err


def test_a_service_only_runs_in_its_role(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LEKTO_ROLE", "api")

    assert main(["worker"]) == 1
    monkeypatch.setenv("LEKTO_ROLE", "worker")
    assert main(["api"]) == 1

    events = [json.loads(line)["event"] for line in capsys.readouterr().err.splitlines()]
    assert "the worker does not run with LEKTO_ROLE=api" in events
    assert events[-1] == "the api does not run with LEKTO_ROLE=worker"


def test_the_worker_stops_cleanly_on_sigterm(tmp_path: Path) -> None:
    """In a process of its own: start on SQLite and the filesystem, then SIGTERM."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("LEKTO_")}
    environment |= {
        "LEKTO_DB_SQLITE_PATH": str(tmp_path / "lekto.db"),
        "LEKTO_STORAGE_PATH": str(tmp_path / "objects"),
        "LEKTO_LOG_LEVEL": "INFO",
        "LEKTO_SECRET_KEY": SECRET_KEY,
        "LEKTO_FORWARDED_ALLOW_IPS": TRUSTED_PROXY,
    }
    command = [sys.executable, "-m", "lekto.composition"]
    subprocess.run([*command, "migrate"], env=environment, check=True, capture_output=True)

    with subprocess.Popen(
        [*command, "worker"], env=environment, stderr=subprocess.PIPE, text=True
    ) as process:
        assert process.stderr is not None
        lines: list[str] = []
        for line in process.stderr:
            lines.append(line)
            if json.loads(line)["event"] == "worker started":
                break
        process.send_signal(signal.SIGTERM)
        lines += process.stderr.readlines()
        assert process.wait(timeout=30) == 0
    events = [json.loads(line)["event"] for line in lines]
    assert events[-2:] == ["worker stopping", "worker stopped"]


def test_the_api_serves_health_and_stops_on_sigterm(tmp_path: Path) -> None:
    """In a process of its own: start on SQLite and the filesystem, on the port the operating
    system picks, which the start line names; ask /health, SIGTERM. The first admin is created
    from the configuration; the password never shows in the log."""
    password_file = tmp_path / "admin-password"
    password_file.write_text(PASSWORD + "\n")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("LEKTO_")}
    environment |= {
        "LEKTO_DB_SQLITE_PATH": str(tmp_path / "lekto.db"),
        "LEKTO_STORAGE_PATH": str(tmp_path / "objects"),
        "LEKTO_API_HOST": "127.0.0.1",
        "LEKTO_API_PORT": "0",
        "LEKTO_SECRET_KEY": SECRET_KEY,
        "LEKTO_FORWARDED_ALLOW_IPS": TRUSTED_PROXY,
        "LEKTO_ADMIN_USERNAME": "admin",
        "LEKTO_ADMIN_PASSWORD_FILE": str(password_file),
    }
    command = [sys.executable, "-m", "lekto.composition"]
    subprocess.run([*command, "migrate"], env=environment, check=True, capture_output=True)

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with subprocess.Popen(
        [*command, "api"], env=environment, stderr=subprocess.PIPE, text=True
    ) as process:
        assert process.stderr is not None
        lines: list[str] = []
        port = None
        for line in process.stderr:
            lines.append(line)
            event = json.loads(line)
            if event["event"] == "api started":
                port = event["port"]
                break
        assert port is not None, "".join(lines)
        with opener.open(f"http://127.0.0.1:{port}/api/v1/health", timeout=5) as answer:
            health = json.load(answer)
        login = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/v1/auth/login",
            data=json.dumps({"username": "admin", "password": PASSWORD}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with opener.open(login, timeout=5) as answer:
            signed_in = json.load(answer)
            cookie = answer.headers["Set-Cookie"]
        process.send_signal(signal.SIGTERM)
        output = "".join(lines) + process.stderr.read()
        assert process.wait(timeout=30) == 0, output
    assert health == {"status": "ok", "checks": {"database": "ok", "object_store": "ok"}}
    assert signed_in["user"]["role"] == "admin"
    assert cookie.startswith("__Host-lekto_session=") and "Secure" in cookie
    assert "first admin created" in output
    assert PASSWORD not in output


def _events(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [json.loads(line)["event"] for line in capsys.readouterr().err.splitlines()]


def test_check_schema_tells_whether_the_database_is_migrated(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "data" / "lekto.db"
    monkeypatch.setenv("LEKTO_DB_SQLITE_PATH", str(path))

    assert main(["check-schema"]) == 1
    assert not path.exists()  # looking does not create the file
    assert "the database schema is not migrated" in _events(capsys)

    assert main(["migrate"]) == 0
    capsys.readouterr()
    assert main(["check-schema"]) == 0
    assert "database schema is current" in _events(capsys)


def test_check_schema_rejects_a_database_of_a_newer_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "lekto.db"
    monkeypatch.setenv("LEKTO_DB_SQLITE_PATH", str(path))
    assert main(["migrate"]) == 0
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE alembic_version SET version_num = '9999'")
    capsys.readouterr()

    started = time.monotonic()
    assert main(["check-schema", "--wait", "30"]) == 1  # no waiting: it will not get better

    assert time.monotonic() - started < 10
    assert any("newer version" in event for event in _events(capsys))


def test_check_schema_only_reads_a_sqlite_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # A missing file stays missing, and so does its directory: the migration creates them.
    missing = tmp_path / "data" / "lekto.db"
    monkeypatch.setenv("LEKTO_DB_SQLITE_PATH", str(missing))
    assert main(["check-schema"]) == 1
    assert not missing.parent.exists()

    # A fresh file the migration just created is not switched to WAL by the check: that switch
    # is a write, and racing the migration's own switch failed it ("database is locked").
    fresh = tmp_path / "fresh.db"
    fresh.touch()
    monkeypatch.setenv("LEKTO_DB_SQLITE_PATH", str(fresh))
    assert main(["check-schema"]) == 1
    assert fresh.stat().st_size == 0
    assert not (tmp_path / "fresh.db-wal").exists()
    capsys.readouterr()


def test_check_schema_waits_for_the_migration(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "lekto.db"
    monkeypatch.setenv("LEKTO_DB_SQLITE_PATH", str(path))
    monkeypatch.setattr("lekto.composition.database.SCHEMA_POLL_INTERVAL", 0.1)

    timer = threading.Timer(1.0, lambda: main(["migrate"]))
    timer.start()
    try:
        assert main(["check-schema", "--wait", "30"]) == 0
    finally:
        timer.join()

    assert "waiting for the database schema to be migrated" in _events(capsys)


def test_wait_only_goes_with_check_schema(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["migrate", "--wait", "5"])
    assert "unrecognized arguments: --wait" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("command", "target"),
    [
        (["evaluate", "--fake"], "lekto.composition.__main__.run_evaluation"),
        (["check-schema"], "lekto.composition.__main__.check_schema"),
    ],
)
def test_a_command_that_breaks_logs_why_and_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
    target: str,
) -> None:
    async def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("broken")

    monkeypatch.setattr(target, broken)
    assert main(command) == 1
    failed = [json.loads(line) for line in capsys.readouterr().err.splitlines()][-1]
    assert failed["level"] == "error" and "RuntimeError: broken" in failed["exception"]


@pytest.fixture
def environment() -> Iterator[None]:
    """`--env-file` changes the process' environment; it is restored afterwards."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def test_the_settings_can_come_from_a_file(
    environment: None, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "dev.env"
    path.write_text(
        f"LEKTO_SECRET_KEY={SECRET_KEY}\nLEKTO_DB_SQLITE_PATH={tmp_path / 'dev.db'}\n"
        "LEKTO_FORWARDED_ALLOW_IPS=127.0.0.1\n"
    )
    os.environ["LEKTO_DB_TYPO"] = "from the environment, not the file"

    assert main(["--env-file", str(path)]) == 0
    assert main(["check", "--env-file", str(path)]) == 0  # after the command, too

    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert "unknown configuration variable" not in [e["event"] for e in events]
    assert events[-1]["db_sqlite_path"] == str(tmp_path / "dev.db")


def test_a_file_that_is_no_setting_exits_one(
    environment: None, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "dev.env"
    path.write_text("LEKTO_DB_NAME=two words\n")
    assert main(["--env-file", str(path)]) == 1
    assert "needs quotes" in capsys.readouterr().err


def test_as_root_it_warns_and_stops_unless_root_is_meant(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.delenv("PUID", raising=False)
    assert main(["check"]) == 1
    assert "lekto-run lekto" in capsys.readouterr().err
    monkeypatch.setenv("PUID", "0")
    assert main(["check"]) == 0


def test_the_command_is_called_lekto(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert out.startswith("usage: lekto ")
    assert "reindex          rebuild the search index" in out
