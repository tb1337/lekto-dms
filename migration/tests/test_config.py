from pathlib import Path

import pytest

from lekto_migration.config import Config, ConfigError, secret


def load(env: dict[str, str], **changes: object) -> Config:
    values: dict[str, object] = {
        "paperless_url": None,
        "lekto_url": None,
        "state": Path("s"),
        "report_dir": Path("r"),
        "plan": Path("p.yaml"),
        "concurrency": 2,
        "limit": None,
        "pipeline_timeout": 10.0,
    }
    return Config.load(**{**values, **changes}, env=env)  # type: ignore[arg-type]


def test_the_environment_configures_everything() -> None:
    config = load(
        {
            "LEKTO_MIGRATION_PAPERLESS_URL": "http://p/",
            "LEKTO_MIGRATION_PAPERLESS_TOKEN": " key ",
            "LEKTO_MIGRATION_LEKTO_URL": "http://q",
            "LEKTO_MIGRATION_LEKTO_TOKEN": "other",
        }
    )
    assert (config.paperless_url, config.lekto_url, config.plan) == (
        "http://p",
        "http://q",
        Path("p.yaml"),
    )
    assert (config.paperless_token, config.lekto_token) == ("key", "other")


def test_keys_never_show_in_the_text_of_the_configuration() -> None:
    config = load(
        {
            "LEKTO_MIGRATION_PAPERLESS_URL": "http://p",
            "LEKTO_MIGRATION_PAPERLESS_TOKEN": "very-secret",
        }
    )
    assert "very-secret" not in repr(config) and "very-secret" not in str(config)


def test_a_key_may_come_from_a_file(tmp_path: Path) -> None:
    file = tmp_path / "key"
    file.write_text("from-file\n")
    assert secret({"LEKTO_MIGRATION_X_FILE": str(file)}, "X") == "from-file"
    with pytest.raises(ConfigError, match="only one"):
        secret({"LEKTO_MIGRATION_X_FILE": str(file), "LEKTO_MIGRATION_X": "v"}, "X")
    with pytest.raises(ConfigError, match="cannot read"):
        secret({"LEKTO_MIGRATION_X_FILE": str(tmp_path / "missing")}, "X")


@pytest.mark.parametrize(
    ("env", "changes", "text"),
    [
        ({}, {}, "Paperless URL"),
        ({"LEKTO_MIGRATION_PAPERLESS_URL": "http://p"}, {}, "API key"),
        (
            {"LEKTO_MIGRATION_PAPERLESS_URL": "http://p", "LEKTO_MIGRATION_PAPERLESS_TOKEN": "k"},
            {"concurrency": 0},
            "concurrency",
        ),
    ],
)
def test_missing_or_wrong_settings_are_refused(
    env: dict[str, str], changes: dict[str, object], text: str
) -> None:
    with pytest.raises(ConfigError, match=text):
        load(env, **changes)


def test_without_a_terminal_only_yes_writes() -> None:
    from lekto_migration.cli import terminal

    config = load(
        {"LEKTO_MIGRATION_PAPERLESS_URL": "http://p", "LEKTO_MIGRATION_PAPERLESS_TOKEN": "k"}
    )
    assert terminal(config)("Write it?") is False  # pytest's stdin is no terminal
    assert (
        terminal(
            load(
                {
                    "LEKTO_MIGRATION_PAPERLESS_URL": "http://p",
                    "LEKTO_MIGRATION_PAPERLESS_TOKEN": "k",
                },
                yes=True,
            )
        )("Write it?")
        is True
    )


def test_an_env_file_replaces_the_lekto_variables(tmp_path: Path) -> None:
    from lekto_migration.config import env_file

    path = tmp_path / "dev.env"
    path.write_text(
        "# the development instance\n"
        "LEKTO_MIGRATION_PAPERLESS_URL=http://paperless:8000\n"
        "export LEKTO_MIGRATION_PAPERLESS_TOKEN='a b'  # quoted\n"
        'LEKTO_MIGRATION_LEKTO_URL="http://lekto:8000"\n'
    )
    environ = {"LEKTO_MIGRATION_LEKTO_TOKEN": "test", "HOME": "/home/x"}
    assert env_file(path, environ) == {
        "HOME": "/home/x",
        "LEKTO_MIGRATION_PAPERLESS_URL": "http://paperless:8000",
        "LEKTO_MIGRATION_PAPERLESS_TOKEN": "a b",
        "LEKTO_MIGRATION_LEKTO_URL": "http://lekto:8000",
    }
    path.write_text("LEKTO_MIGRATION_X=two words\n")
    with pytest.raises(ConfigError, match=r"dev.env:1: .*needs quotes"):
        env_file(path, environ)
    with pytest.raises(ConfigError, match="--env-file"):
        env_file(tmp_path / "missing.env", environ)


def test_the_env_file_goes_before_or_after_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from lekto_migration.cli import main

    missing = str(tmp_path / "missing.env")
    assert main(["--env-file", missing, "check"]) == 2
    assert main(["check", "--env-file", missing]) == 2
    assert capsys.readouterr().err.count("--env-file") == 2
