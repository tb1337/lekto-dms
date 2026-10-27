"""Postgres for the SQL adapter tests: a database of its own per test session, migrated once
with the real migrations and emptied before every test. Skips if Postgres is not configured or
not reachable; the CI checks that the Postgres run did not skip."""

import asyncio
import secrets
from collections.abc import AsyncIterator, Callable, Iterator

import pytest
from sqlalchemy import text

from lekto.adapters.outbound.sql import (
    Database,
    SqlEventBus,
    SqlUnitOfWorkFactory,
    SqlWakeup,
    migrate,
)
from lekto.adapters.outbound.sql.tables import metadata
from lekto.composition.settings import Settings
from lekto.core.domain.jobs import RetryPolicy
from lekto.core.ports.clock import Clock
from lekto.core.ports.event_bus import EventBus
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from tests import builders
from tests.contracts.event_bus import EventBusFactory
from tests.contracts.wakeup import WakeupFactory
from tests.integration.services import create_database, drop_database, postgres


@pytest.fixture
def new_database_names(postgres_settings: Settings) -> Iterator[Callable[[], str]]:
    """Names of databases that do not exist yet; they are dropped after the test."""
    names: list[str] = []

    def new_name() -> str:
        names.append(f"{postgres_settings.db_name}_test_{secrets.token_hex(4)}")
        return names[-1]

    yield new_name
    for name in names:
        asyncio.run(drop_database(postgres_settings, name))


@pytest.fixture(scope="session")
def test_database_name(postgres_settings: Settings) -> Iterator[str]:
    name = f"{postgres_settings.db_name}_test_{secrets.token_hex(4)}"

    async def create() -> None:
        await create_database(postgres_settings, name)
        database = postgres(postgres_settings, name)
        try:
            await migrate(database)
        finally:
            await database.dispose()

    asyncio.run(create())
    yield name
    asyncio.run(drop_database(postgres_settings, name))


@pytest.fixture
async def database(postgres_settings: Settings, test_database_name: str) -> AsyncIterator[Database]:
    database = postgres(postgres_settings, test_database_name)
    names = ", ".join(table.name for table in metadata.sorted_tables)
    async with database.engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    yield database
    await database.dispose()


@pytest.fixture
def uow_factory(database: Database) -> UnitOfWorkFactory:
    return SqlUnitOfWorkFactory(database)


@pytest.fixture
def event_bus_factory(database: Database) -> EventBusFactory:
    def create(
        *, clock: Clock | None = None, retry: RetryPolicy = builders.EVENT_RETRY
    ) -> EventBus:
        return SqlEventBus(database, clock=clock, retry=retry)

    return create


@pytest.fixture
def wakeup_factory(database: Database) -> WakeupFactory:
    return lambda: SqlWakeup(database)


@pytest.fixture
async def empty_database(
    postgres_settings: Settings, new_database_names: Callable[[], str]
) -> AsyncIterator[Database]:
    name = new_database_names()
    await create_database(postgres_settings, name)
    database = postgres(postgres_settings, name)
    yield database
    await database.dispose()


@pytest.fixture
async def model_database(
    postgres_settings: Settings, new_database_names: Callable[[], str]
) -> AsyncIterator[Database]:
    name = new_database_names()
    await create_database(postgres_settings, name)
    database = postgres(postgres_settings, name)
    yield database
    await database.dispose()
