import re
from datetime import timedelta
from pathlib import Path

import pytest

from lekto.composition.errors import ConfigurationError
from lekto.composition.settings import (
    DEVELOPMENT_SECRET_KEY,
    ENV_PREFIX,
    Settings,
    find_unknown_variables,
    load_settings,
)

POSTGRES = {
    "LEKTO_DB_TYPE": "postgres",
    "LEKTO_DB_HOST": "db",
    "LEKTO_DB_NAME": "lekto",
    "LEKTO_DB_USER": "lekto",
    "LEKTO_DB_PASSWORD": "pw",
}
S3 = {
    "LEKTO_STORAGE_TYPE": "s3",
    "LEKTO_S3_ENDPOINT_URL": "http://garage:3900",
    "LEKTO_S3_BUCKET": "lekto",
    "LEKTO_S3_ACCESS_KEY_ID": "key",
    "LEKTO_S3_SECRET_ACCESS_KEY": "secret",
}


def set_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def error_message(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> str:
    set_env(monkeypatch, values)
    with pytest.raises(ConfigurationError) as info:
        load_settings()
    return str(info.value)


def test_defaults() -> None:
    settings = load_settings()
    assert settings.role == "all"
    assert settings.log_format == "json"
    assert settings.log_level == "INFO"
    assert settings.db_type == "sqlite"
    assert settings.storage_type == "filesystem"
    assert settings.meilisearch_url is None
    assert settings.llm_base_url is None
    assert settings.embedding_base_url is None


def test_valid_postgres_and_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, POSTGRES | S3 | {"LEKTO_DB_PORT": "6543", "LEKTO_ROLE": "worker"})
    settings = load_settings()
    assert settings.db_type == "postgres"
    assert settings.db_port == 6543
    assert settings.db_password is not None
    assert settings.db_password.get_secret_value() == "pw"
    assert settings.storage_type == "s3"
    assert str(settings.s3_endpoint_url) == "http://garage:3900/"
    assert settings.role == "worker"


def test_llm_and_embedding_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(
        monkeypatch,
        {
            "LEKTO_LLM_BASE_URL": "http://host.docker.internal:11434/v1",
            "LEKTO_LLM_MODEL": "qwen3",
            "LEKTO_EMBEDDING_BASE_URL": "http://localhost:11434/v1",
            "LEKTO_EMBEDDING_MODEL": "bge-m3",
        },
    )
    settings = load_settings()
    assert settings.llm_model == "qwen3"
    assert settings.embedding_model == "bge-m3"


def test_classification_defaults() -> None:
    settings = load_settings()
    assert settings.llm_temperature == 0
    assert settings.llm_seed is None
    assert settings.llm_timeout == timedelta(minutes=5)
    assert settings.llm_response_format == "json_schema"
    assert settings.llm_input_budget == 12_000
    assert settings.llm_max_tags == 200
    assert settings.embedding_timeout == timedelta(minutes=1)
    assert settings.confidence_threshold == 0.9
    assert settings.contact_suggest_threshold == 0.75


def test_classification_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(
        monkeypatch,
        {
            "LEKTO_LLM_TEMPERATURE": "0.2",
            "LEKTO_LLM_SEED": "42",
            "LEKTO_LLM_TIMEOUT": "PT10M",
            "LEKTO_LLM_RESPONSE_FORMAT": "JSON_Object",
            "LEKTO_LLM_INPUT_BUDGET": "20000",
            "LEKTO_CONFIDENCE_THRESHOLD": "0.8",
            "LEKTO_CONTACT_SUGGEST_THRESHOLD": "0.8",
        },
    )
    settings = load_settings()
    assert settings.llm_temperature == 0.2
    assert settings.llm_seed == 42
    assert settings.llm_timeout == timedelta(minutes=10)
    assert settings.llm_response_format == "json_object"
    assert settings.llm_input_budget == 20_000
    assert settings.confidence_threshold == settings.contact_suggest_threshold == 0.8


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LEKTO_LLM_TEMPERATURE", "-1"),
        ("LEKTO_LLM_TEMPERATURE", "warm"),
        ("LEKTO_LLM_RESPONSE_FORMAT", "text"),
        ("LEKTO_LLM_INPUT_BUDGET", "10"),
        ("LEKTO_LLM_TIMEOUT", "0"),
        ("LEKTO_CONFIDENCE_THRESHOLD", "0"),
        ("LEKTO_CONFIDENCE_THRESHOLD", "1.5"),
    ],
)
def test_invalid_classification_settings(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    assert name in error_message(monkeypatch, {name: value})


def test_the_suggestion_threshold_is_not_above_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = error_message(
        monkeypatch,
        {"LEKTO_CONFIDENCE_THRESHOLD": "0.7", "LEKTO_CONTACT_SUGGEST_THRESHOLD": "0.75"},
    )
    assert "LEKTO_CONTACT_SUGGEST_THRESHOLD must not be above LEKTO_CONFIDENCE_THRESHOLD" in message


def test_none_leaves_the_temperature_to_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, {"LEKTO_LLM_TEMPERATURE": "None"})
    assert load_settings().llm_temperature is None


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, {"LEKTO_LOG_LEVEL": "debug"})
    assert load_settings().log_level == "DEBUG"


def test_empty_variable_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, {"LEKTO_DB_TYPE": ""})
    assert load_settings().db_type == "sqlite"


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("LEKTO_ROLE", "everything"),
        ("LEKTO_DB_TYPE", "mysql"),
        ("LEKTO_STORAGE_TYPE", "ftp"),
        ("LEKTO_LOG_FORMAT", "xml"),
        ("LEKTO_LOG_LEVEL", "LOUD"),
        ("LEKTO_DB_PORT", "0"),
        ("LEKTO_DB_PORT", "abc"),
        ("LEKTO_MEILISEARCH_URL", "not a url"),
    ],
)
def test_invalid_value_names_the_variable(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    message = error_message(monkeypatch, {variable: value})
    assert f"{variable}:" in message
    assert value in message


@pytest.mark.parametrize("value", ["xx_YY", "de DE"])
def test_an_unknown_template_locale_is_refused(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    message = error_message(monkeypatch, {"LEKTO_TEMPLATE_LOCALE": value})
    assert "LEKTO_TEMPLATE_LOCALE:" in message and f"unknown locale {value!r}" in message


def test_postgres_requires_connection_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    message = error_message(monkeypatch, {"LEKTO_DB_TYPE": "postgres"})
    for name in ("HOST", "NAME", "USER", "PASSWORD"):
        assert f"LEKTO_DB_{name} is required when LEKTO_DB_TYPE=postgres" in message


def test_s3_requires_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    message = error_message(monkeypatch, {"LEKTO_STORAGE_TYPE": "s3"})
    for name in ("ENDPOINT_URL", "BUCKET", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY"):
        assert f"LEKTO_S3_{name} is required when LEKTO_STORAGE_TYPE=s3" in message


def test_sqlite_ignores_postgres_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, {"LEKTO_DB_HOST": "db"})
    assert load_settings().db_type == "sqlite"


@pytest.mark.parametrize("prefix", ["LLM", "EMBEDDING", "VLM"])
def test_endpoint_and_model_must_be_set_together(
    monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    message = error_message(monkeypatch, {f"LEKTO_{prefix}_MODEL": "m"})
    assert f"LEKTO_{prefix}_BASE_URL and LEKTO_{prefix}_MODEL must be set together" in message


def test_all_problems_are_reported_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    message = error_message(monkeypatch, {"LEKTO_ROLE": "x", "LEKTO_DB_PORT": "0"})
    assert "LEKTO_ROLE" in message
    assert "LEKTO_DB_PORT" in message


def test_secret_is_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, POSTGRES | {"LEKTO_DB_PASSWORD": "s3cr3t-value"})
    settings = load_settings()
    assert "s3cr3t-value" not in repr(settings)
    assert settings.describe()["db_password"] == "**********"


def test_url_credentials_are_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, {"LEKTO_MEILISEARCH_URL": "http://admin:hunter2@meili:7700"})
    description = load_settings().describe()
    assert description["meilisearch_url"] == "http://***@meili:7700/"
    assert "hunter2" not in str(description)

    message = error_message(monkeypatch, {"LEKTO_LLM_BASE_URL": "http://admin:hunter2@ollama:::1"})
    assert "LEKTO_LLM_BASE_URL" in message
    assert "hunter2" not in message


def test_choices_ignore_case_and_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(
        monkeypatch,
        {
            "LEKTO_ROLE": "API",
            "LEKTO_LOG_FORMAT": " Console ",
            "LEKTO_DB_TYPE": "SQLite",
            "LEKTO_CLASSIFIER": "NONE",
        },
    )
    settings = load_settings()
    assert (settings.role, settings.log_format, settings.db_type) == ("api", "console", "sqlite")
    assert settings.classifier == "none"


def test_blank_values_count_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, POSTGRES | {"LEKTO_DB_HOST": "  ", "LEKTO_DB_PASSWORD": " "})
    message = error_message(monkeypatch, {})
    assert "LEKTO_DB_HOST is required" in message
    assert "LEKTO_DB_PASSWORD is required" in message


def test_values_are_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, POSTGRES | {"LEKTO_DB_HOST": " db \n"})
    assert load_settings().db_host == "db"


def test_variable_names_are_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, {"lekto_role": "worker"})
    assert load_settings().role == "worker"


def test_secret_from_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret = tmp_path / "db"
    secret.write_text("from-file\n")
    set_env(monkeypatch, POSTGRES)
    monkeypatch.delenv("LEKTO_DB_PASSWORD")
    monkeypatch.setenv("LEKTO_DB_PASSWORD_FILE", str(secret))
    settings = load_settings()
    assert settings.db_password is not None
    assert settings.db_password.get_secret_value() == "from-file"


def test_only_one_trailing_newline_is_removed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "key"
    secret.write_text(" spaced \n\n")
    monkeypatch.setenv("LEKTO_MEILISEARCH_API_KEY_FILE", str(secret))
    settings = load_settings()
    assert settings.meilisearch_api_key is not None
    assert settings.meilisearch_api_key.get_secret_value() == " spaced \n"


def test_variable_and_file_together_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret = tmp_path / "db"
    secret.write_text("from-file")
    message = error_message(
        monkeypatch,
        {"LEKTO_DB_PASSWORD": "pw", "LEKTO_DB_PASSWORD_FILE": str(secret)},
    )
    assert message == (
        "LEKTO_DB_PASSWORD and LEKTO_DB_PASSWORD_FILE are both set; use only one of them"
    )


def test_missing_secret_file_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    message = error_message(monkeypatch, {"LEKTO_LLM_API_KEY_FILE": str(missing)})
    assert "LEKTO_LLM_API_KEY_FILE" in message
    assert str(missing) in message


@pytest.mark.parametrize("content", ["", "\n", "  \n"])
def test_blank_secret_file_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
) -> None:
    secret = tmp_path / "blank"
    secret.write_text(content)
    message = error_message(monkeypatch, {"LEKTO_LLM_API_KEY_FILE": str(secret)})
    assert "is empty" in message


def test_unreadable_secret_files_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    binary = tmp_path / "binary"
    binary.write_bytes(b"\xff\xfe\x00")
    assert "not valid UTF-8" in error_message(monkeypatch, {"LEKTO_LLM_API_KEY_FILE": str(binary)})
    assert "LEKTO_LLM_API_KEY_FILE" in error_message(
        monkeypatch, {"LEKTO_LLM_API_KEY_FILE": str(tmp_path)}
    )


def test_s3_secrets_from_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    key_id, key = tmp_path / "id", tmp_path / "key"
    key_id.write_text("file-id\n")
    key.write_text("file-key\n")
    set_env(monkeypatch, S3)
    monkeypatch.delenv("LEKTO_S3_ACCESS_KEY_ID")
    monkeypatch.delenv("LEKTO_S3_SECRET_ACCESS_KEY")
    monkeypatch.setenv("LEKTO_S3_ACCESS_KEY_ID_FILE", str(key_id))
    monkeypatch.setenv("LEKTO_S3_SECRET_ACCESS_KEY_FILE", str(key))
    settings = load_settings()
    assert settings.s3_access_key_id is not None
    assert settings.s3_secret_access_key is not None
    assert settings.s3_access_key_id.get_secret_value() == "file-id"
    assert settings.s3_secret_access_key.get_secret_value() == "file-key"


def test_file_variant_exists_only_for_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    role = tmp_path / "role"
    role.write_text("api")
    set_env(monkeypatch, {"LEKTO_ROLE_FILE": str(role)})
    assert Settings().role == "all"
    assert find_unknown_variables() == ["LEKTO_ROLE_FILE"]


def test_unknown_variables_are_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(monkeypatch, {"LEKTO_DB_TYPO": "x", "LEKTO_ROLE": "all", "UNRELATED": "y"})
    assert find_unknown_variables() == ["LEKTO_DB_TYPO"]


def test_variables_of_the_migration_client_are_not_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """The development instance shares its environment with `lekto-migration`."""
    set_env(
        monkeypatch,
        {"LEKTO_MIGRATION_PAPERLESS_URL": "http://paperless:8000", "LEKTO_MIGRATION_TYPO": "x"},
    )
    assert find_unknown_variables() == []


def test_variables_of_the_image_are_not_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """`PUID`, `PGID` and the `S6_` variables belong to the container, not to Lekto."""
    set_env(
        monkeypatch,
        {"PUID": "1000", "PGID": "1000", "S6_SERVICES_GRACETIME": "40000", "TZ": "Europe/Berlin"},
    )
    assert find_unknown_variables() == []


def test_the_web_ui_is_off_by_default() -> None:
    assert load_settings().ui_dir is None


def test_the_web_ui_directory_needs_its_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    message = error_message(monkeypatch, {"LEKTO_UI_DIR": str(tmp_path)})
    assert f"LEKTO_UI_DIR: no index.html in {tmp_path}" in message
    set_env(monkeypatch, {"LEKTO_ROLE": "worker"})
    assert load_settings().ui_dir == tmp_path  # the worker serves nothing
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    set_env(monkeypatch, {"LEKTO_ROLE": "all"})
    assert load_settings().ui_dir == tmp_path


def test_webhook_defaults() -> None:
    settings = load_settings()
    assert settings.webhooks_per_user == 20
    assert settings.webhook_secret_grace == timedelta(hours=24)
    assert settings.webhook_timeout == timedelta(seconds=10)
    assert settings.webhook_max_attempts == 10
    assert settings.webhook_retry_delay == timedelta(seconds=30)
    assert settings.webhook_disable_after == 20
    assert settings.webhook_concurrency == 4


def test_mcp_defaults() -> None:
    settings = load_settings()
    assert settings.mcp_enabled is True
    assert settings.mcp_text_max == 20_000


def test_worker_and_processing_defaults() -> None:
    settings = load_settings()
    assert settings.worker_concurrency == 2
    assert settings.node_max_attempts == 3
    assert settings.node_retry_delay == timedelta(seconds=30)
    assert settings.ocr_languages == "deu+eng"
    assert settings.ocr_timeout == timedelta(minutes=10)
    assert settings.retention == timedelta(days=7)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("30", timedelta(seconds=30)), ("1.5", timedelta(seconds=1.5)), ("PT1H", timedelta(hours=1))],
)
def test_durations_are_seconds_or_iso_8601(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: timedelta
) -> None:
    monkeypatch.setenv("LEKTO_OCR_TIMEOUT", value)
    assert load_settings().ocr_timeout == expected


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LEKTO_OCR_TIMEOUT", "0"),
        ("LEKTO_OCR_TIMEOUT", "ten"),
        ("LEKTO_WORKER_CONCURRENCY", "0"),
        ("LEKTO_OCR_LANGUAGES", "deu,eng"),
        ("LEKTO_OCR_LANGUAGES", "deu+"),
    ],
)
def test_invalid_worker_settings_name_the_variable(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    assert name in error_message(monkeypatch, {name: value})


def test_every_role_needs_a_valid_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # The worker decrypts webhook secrets to sign requests.
    monkeypatch.delenv("LEKTO_SECRET_KEY")
    for role in ("all", "api", "worker"):
        message = error_message(monkeypatch, {"LEKTO_ROLE": role})
        assert "LEKTO_SECRET_KEY is required" in message
    message = error_message(monkeypatch, {"LEKTO_SECRET_KEY": "too-short"})
    assert "LEKTO_SECRET_KEY" in message and "openssl rand -base64 32" in message
    assert "too-short" not in message


def test_identity_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    password = tmp_path / "admin"
    password.write_text("a long admin password\n")
    set_env(
        monkeypatch,
        {
            "LEKTO_ADMIN_USERNAME": "root",
            "LEKTO_ADMIN_PASSWORD_FILE": str(password),
            "LEKTO_SESSION_IDLE_TIMEOUT": "PT8H",
            "LEKTO_SESSION_MAX_AGE": "P7D",
            "LEKTO_COOKIE_SECURE": "false",
            "LEKTO_FORWARDED_ALLOW_IPS": "172.18.0.2",
        },
    )
    settings = load_settings()
    assert settings.admin_password is not None
    assert settings.admin_password.get_secret_value() == "a long admin password"
    assert settings.session_idle_timeout == timedelta(hours=8)
    assert settings.session_max_age == timedelta(days=7)
    assert settings.cookie_secure is False
    assert settings.forwarded_allow_ips == "172.18.0.2"
    described = settings.describe()
    assert described["admin_password"] == "**********"
    assert described["secret_key"] == "**********"


def test_identity_defaults() -> None:
    settings = load_settings()
    assert settings.session_idle_timeout == timedelta(days=1)
    assert settings.session_max_age == timedelta(days=30)
    assert settings.cookie_secure is True
    assert settings.admin_username is None


def test_inconsistent_identity_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    message = error_message(
        monkeypatch,
        {
            "LEKTO_ADMIN_USERNAME": "root",
            "LEKTO_SESSION_IDLE_TIMEOUT": "P2D",
            "LEKTO_SESSION_MAX_AGE": "P1D",
        },
    )
    assert "LEKTO_ADMIN_USERNAME and LEKTO_ADMIN_PASSWORD must be set together" in message
    assert "LEKTO_SESSION_MAX_AGE must not be shorter than LEKTO_SESSION_IDLE_TIMEOUT" in message


OIDC = {
    "LEKTO_OIDC_ISSUER": "https://idp.example/realms/home",
    "LEKTO_OIDC_CLIENT_ID": "lekto",
    "LEKTO_OIDC_CLIENT_SECRET": "client-secret",
    "LEKTO_PUBLIC_URL": "https://lekto.example",
}


def test_oidc_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not load_settings().oidc_enabled
    set_env(monkeypatch, OIDC | {"LEKTO_OIDC_AUTO_CREATE": "true"})
    settings = load_settings()
    assert settings.oidc_enabled
    assert settings.oidc_issuer == "https://idp.example/realms/home"  # exactly as given
    assert settings.oidc_scopes == "openid profile email"
    assert settings.oidc_display_name == "Single sign-on"
    assert settings.oidc_auto_create is True
    assert settings.describe()["oidc_client_secret"] == "**********"


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            {"LEKTO_OIDC_ISSUER": "https://idp.example"},
            "LEKTO_OIDC_ISSUER, LEKTO_OIDC_CLIENT_ID, LEKTO_OIDC_CLIENT_SECRET must be set "
            "together",
        ),
        (OIDC | {"LEKTO_OIDC_ISSUER": "http://idp.example"}, "LEKTO_OIDC_ISSUER: must be an https"),
        (OIDC | {"LEKTO_OIDC_SCOPES": "profile email"}, "LEKTO_OIDC_SCOPES: must contain 'openid'"),
        (
            {key: value for key, value in OIDC.items() if key != "LEKTO_PUBLIC_URL"},
            "LEKTO_PUBLIC_URL is required with OIDC",
        ),
    ],
)
def test_inconsistent_oidc_settings(
    monkeypatch: pytest.MonkeyPatch, values: dict[str, str], expected: str
) -> None:
    message = error_message(monkeypatch, values)
    assert expected in message
    assert "client-secret" not in message


def test_secure_cookies_need_the_trusted_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    """M4-01: Lekto speaks plain HTTP; with `Secure` cookies (default) a TLS-terminating proxy
    is in front of it. Without `LEKTO_FORWARDED_ALLOW_IPS` every request then carries the
    proxy's address, and the per-source throttle would hit everyone at once."""
    monkeypatch.delenv("LEKTO_FORWARDED_ALLOW_IPS")
    message = error_message(monkeypatch, {})
    assert "LEKTO_FORWARDED_ALLOW_IPS is required with LEKTO_COOKIE_SECURE=true" in message
    with pytest.raises(ConfigurationError, match="FORWARDED_ALLOW_IPS"):
        Settings(cookie_secure=True, forwarded_allow_ips=None)
    set_env(monkeypatch, {"LEKTO_COOKIE_SECURE": "false"})
    assert load_settings().forwarded_allow_ips is None  # development over plain HTTP
    set_env(monkeypatch, {"LEKTO_COOKIE_SECURE": "true", "LEKTO_ROLE": "worker"})
    assert load_settings().forwarded_allow_ips is None  # no cookies in the worker


def test_request_bodies_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    assert load_settings().request_max_size == 1024 * 1024
    set_env(monkeypatch, {"LEKTO_REQUEST_MAX_SIZE": "64KiB"})
    assert load_settings().request_max_size == 64 * 1024


def test_the_development_key_is_refused_with_secure_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M4-11: the devcontainer's key is public; production (secure cookies) must not use it."""
    compose = Path(__file__).parents[3] / ".devcontainer" / "compose.yml"
    lines = [line.strip() for line in compose.read_text().splitlines()]
    assert f"LEKTO_SECRET_KEY: {DEVELOPMENT_SECRET_KEY}" in lines
    message = error_message(monkeypatch, {"LEKTO_SECRET_KEY": DEVELOPMENT_SECRET_KEY})
    assert "LEKTO_SECRET_KEY is the development key" in message
    assert DEVELOPMENT_SECRET_KEY not in message
    urlsafe = DEVELOPMENT_SECRET_KEY.replace("+", "-").replace("/", "_").rstrip("=")
    assert "development key" in error_message(monkeypatch, {"LEKTO_SECRET_KEY": urlsafe})
    set_env(monkeypatch, {"LEKTO_COOKIE_SECURE": "false"})
    assert load_settings().secret_key is not None  # fine for development


def test_search_defaults() -> None:
    settings = load_settings()
    assert settings.meilisearch_index == "lekto-documents"
    assert settings.meilisearch_timeout == timedelta(seconds=30)
    assert settings.meilisearch_task_timeout == timedelta(minutes=2)
    assert settings.search_locales == "deu+eng"
    assert settings.embedding_dimensions is None
    assert settings.search_semantic_ratio == 0.5
    assert settings.search_embed_timeout == timedelta(seconds=5)
    assert (settings.search_max_text, settings.search_chunk_size, settings.search_max_chunks) == (
        200_000,
        1500,
        8,
    )
    assert settings.search_reconcile_interval == timedelta(hours=6)
    assert settings.search_rebuild_timeout == timedelta(hours=6)
    assert settings.embedding_query_prefix is None
    assert settings.embedding_document_prefix is None


def test_indexing_and_query_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(
        monkeypatch,
        {
            "LEKTO_SEARCH_SEMANTIC_RATIO": "0.8",
            "LEKTO_SEARCH_EMBED_TIMEOUT": "2",
            "LEKTO_SEARCH_MAX_TEXT": "50000",
            "LEKTO_SEARCH_CHUNK_SIZE": "800",
            "LEKTO_SEARCH_MAX_CHUNKS": "4",
            "LEKTO_SEARCH_RECONCILE_INTERVAL": "PT1H",
            "LEKTO_SEARCH_REBUILD_TIMEOUT": "PT12H",
            "LEKTO_EMBEDDING_QUERY_PREFIX": "query:",
            "LEKTO_EMBEDDING_DOCUMENT_PREFIX": "passage:",
        },
    )
    settings = load_settings()
    assert settings.search_semantic_ratio == 0.8
    assert settings.search_embed_timeout == timedelta(seconds=2)
    assert (settings.search_max_text, settings.search_chunk_size, settings.search_max_chunks) == (
        50_000,
        800,
        4,
    )
    assert settings.search_reconcile_interval == timedelta(hours=1)
    assert settings.search_rebuild_timeout == timedelta(hours=12)
    assert (settings.embedding_query_prefix, settings.embedding_document_prefix) == (
        "query:",
        "passage:",
    )


def test_a_prefix_writes_a_line_break_as_backslash_n(monkeypatch: pytest.MonkeyPatch) -> None:
    """Qwen3-Embedding wants its instruction and the query on lines of their own; an environment
    file keeps the value on one line."""
    set_env(monkeypatch, {"LEKTO_EMBEDDING_QUERY_PREFIX": "Instruct: find the documents\\nQuery:"})
    assert load_settings().embedding_query_prefix == "Instruct: find the documents\nQuery:"


def test_search_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    set_env(
        monkeypatch,
        {
            "LEKTO_MEILISEARCH_URL": "http://meilisearch:7700",
            "LEKTO_MEILISEARCH_INDEX": "lekto-test",
            "LEKTO_MEILISEARCH_TIMEOUT": "5",
            "LEKTO_MEILISEARCH_TASK_TIMEOUT": "PT10M",
            "LEKTO_SEARCH_LOCALES": "deu",
            "LEKTO_EMBEDDING_BASE_URL": "http://ollama:11434/v1",
            "LEKTO_EMBEDDING_MODEL": "bge-m3",
            "LEKTO_EMBEDDING_DIMENSIONS": "1024",
        },
    )
    settings = load_settings()
    assert settings.meilisearch_index == "lekto-test"
    assert settings.meilisearch_timeout == timedelta(seconds=5)
    assert settings.meilisearch_task_timeout == timedelta(minutes=10)
    assert settings.search_locales == "deu"
    assert settings.embedding_dimensions == 1024


def test_the_search_index_needs_the_vector_length_with_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embeddings = {
        "LEKTO_EMBEDDING_BASE_URL": "http://ollama:11434/v1",
        "LEKTO_EMBEDDING_MODEL": "bge-m3",
    }
    message = error_message(
        monkeypatch, {**embeddings, "LEKTO_MEILISEARCH_URL": "http://meilisearch:7700"}
    )
    assert "LEKTO_EMBEDDING_DIMENSIONS is required with LEKTO_MEILISEARCH_URL" in message


def test_either_embeddings_or_search_alone_needs_no_vector_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_env(
        monkeypatch,
        {"LEKTO_EMBEDDING_BASE_URL": "http://ollama:11434/v1", "LEKTO_EMBEDDING_MODEL": "bge-m3"},
    )
    assert load_settings().embedding_dimensions is None
    monkeypatch.delenv("LEKTO_EMBEDDING_BASE_URL")
    monkeypatch.delenv("LEKTO_EMBEDDING_MODEL")
    set_env(monkeypatch, {"LEKTO_MEILISEARCH_URL": "http://meilisearch:7700"})
    assert load_settings().embedding_dimensions is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LEKTO_MEILISEARCH_INDEX", "with space"),
        ("LEKTO_MEILISEARCH_INDEX", ""),
        ("LEKTO_SEARCH_LOCALES", "de"),
        ("LEKTO_SEARCH_LOCALES", "deu+"),
        ("LEKTO_EMBEDDING_DIMENSIONS", "0"),
        ("LEKTO_SEARCH_SEMANTIC_RATIO", "1.5"),
        ("LEKTO_SEARCH_SEMANTIC_RATIO", "-0.1"),
        ("LEKTO_SEARCH_CHUNK_SIZE", "10"),
        ("LEKTO_SEARCH_MAX_CHUNKS", "0"),
        ("LEKTO_SEARCH_MAX_TEXT", "10"),
        ("LEKTO_SEARCH_EMBED_TIMEOUT", "0"),
    ],
)
def test_invalid_search_settings(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    set_env(monkeypatch, {name: value})
    if value == "":
        assert load_settings().meilisearch_index == "lekto-documents"  # blank means unset
        return
    with pytest.raises(ConfigurationError, match=name):
        load_settings()


README = Path(__file__).parents[2] / "README.md"
_DOCUMENTED = re.compile(r"^\| `(LEKTO_[A-Z0-9_]+)` \| (API|Worker|both) \| ", re.MULTILINE)


def test_every_setting_is_documented_with_its_role() -> None:
    """backend/README.md, section Configuration, is the one place for all `LEKTO_` variables:
    one row per setting with its role (API, Worker or both), default and meaning."""
    documented = _DOCUMENTED.findall(README.read_text(encoding="utf-8"))
    names = [name for name, _ in documented]
    expected = [ENV_PREFIX + name.upper() for name in Settings.model_fields]
    assert sorted(names) == sorted(expected), (
        f"missing in README: {sorted(set(expected) - set(names))}; "
        f"unknown in README: {sorted(set(names) - set(expected))}"
    )
    assert len(names) == len(set(names)), "a variable is documented twice"


def test_renamed_variables_are_refused_with_their_new_name(monkeypatch: pytest.MonkeyPatch) -> None:
    message = error_message(monkeypatch, {"LEKTO_STEP_MAX_ATTEMPTS": "5"})
    assert message == "LEKTO_STEP_MAX_ATTEMPTS was renamed to LEKTO_NODE_MAX_ATTEMPTS"
