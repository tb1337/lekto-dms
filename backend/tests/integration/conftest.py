import os
import secrets
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from papiq.adapters.outbound.filesystem import FilesystemObjectStore
from papiq.adapters.outbound.sql import Database, migrate
from papiq.composition.settings import Settings, load_settings
from papiq.core.ports import ObjectStore
from tests import probes
from tests.builders import SECRET_KEY, TRUSTED_PROXY
from tests.integration.services import create_database, drop_database, postgres, s3_test_store


@pytest.fixture(scope="session")
def settings() -> Settings:
    """The configuration from the environment: in the devcontainer, the compose services. The
    secret key and the trusted proxies the API requires are not what these tests are about;
    test values fill in."""
    os.environ.setdefault("PAPIQ_SECRET_KEY", SECRET_KEY)
    os.environ.setdefault("PAPIQ_FORWARDED_ALLOW_IPS", TRUSTED_PROXY)
    return load_settings()


# The services: each fixture is the one place that skips a test when its service is not
# configured or does not answer. The CI checks that nothing skipped.


@pytest.fixture(scope="session")
def postgres_settings(settings: Settings) -> Settings:
    if settings.db_type != "postgres" or settings.db_host is None:
        pytest.skip("PAPIQ_DB_TYPE is not postgres")
    if not probes.postgres_answers(settings.db_host, settings.db_port):
        pytest.skip(f"Postgres not reachable at {settings.db_host}:{settings.db_port}")
    return settings


@pytest.fixture(scope="session")
def s3_settings(settings: Settings) -> Settings:
    if settings.storage_type != "s3" or settings.s3_endpoint_url is None:
        pytest.skip("PAPIQ_STORAGE_TYPE is not s3")
    if probes.http_status(str(settings.s3_endpoint_url)) is None:
        pytest.skip(f"S3 endpoint not reachable at {settings.s3_endpoint_url}")
    return settings


@pytest.fixture(scope="session")
def meilisearch_settings(settings: Settings) -> Settings:
    if settings.meilisearch_url is None:
        pytest.skip("PAPIQ_MEILISEARCH_URL is not set")
    if probes.meilisearch_health(str(settings.meilisearch_url)) is None:
        pytest.skip(f"Meilisearch not reachable at {settings.meilisearch_url}")
    return settings


# The two set-ups of the end-to-end tests: SQLite with the filesystem, Postgres with S3 (Garage).
@pytest.fixture(params=["sqlite+filesystem", "postgres+s3"])
async def stores(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[tuple[Database, ObjectStore]]:
    if request.param == "sqlite+filesystem":
        database = Database.sqlite(tmp_path / "papiq.db")
        await migrate(database)
        yield database, FilesystemObjectStore(tmp_path / "objects")
        await database.dispose()
        return
    settings: Settings = request.getfixturevalue("postgres_settings")
    s3: Settings = request.getfixturevalue("s3_settings")
    assert settings.db_name
    name = f"{settings.db_name}_test_{secrets.token_hex(4)}"
    await create_database(settings, name)
    database = postgres(settings, name)
    try:
        await migrate(database)
        async with s3_test_store(s3) as store:
            yield database, store
    finally:
        await database.dispose()
        await drop_database(settings, name)


@pytest.fixture
def object_store(stores: tuple[Database, ObjectStore]) -> ObjectStore:
    return stores[1]
