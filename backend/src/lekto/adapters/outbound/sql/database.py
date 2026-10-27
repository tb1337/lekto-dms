"""Engines for SQLite and Postgres, and how the adapter starts transactions on each.

Reads run with read-committed semantics on both databases. On Postgres that is the default
isolation level. On SQLite the driver runs in autocommit mode, so reads see the latest
committed state; a unit of work starts its transaction with `BEGIN IMMEDIATE` right before
its first write. That takes SQLite's single write lock up front: a read transaction is never
upgraded to a write transaction, which would fail with SQLITE_BUSY instead of waiting.

SQLite has one writer. A task that opened a write transaction and starts a second one would
wait for its own lock until the busy timeout; `begin_write` raises RuntimeError at once instead.
"""

import asyncio
import weakref
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import asyncpg
from sqlalchemy import URL, Table, event
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.dialects.postgresql import Insert as PostgresInsert
from sqlalchemy.dialects.sqlite import Insert as SqliteInsert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from lekto.core.ports.wakeup import Channel

# SQLite engine settings, applied to every connection.
SQLITE_BUSY_TIMEOUT = timedelta(seconds=15)
_SQLITE_BUSY = f"PRAGMA busy_timeout={int(SQLITE_BUSY_TIMEOUT.total_seconds() * 1000)}"
_SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",  # readers do not block the writer and vice versa
    "PRAGMA synchronous=NORMAL",  # durable with WAL except on power loss, much faster
    "PRAGMA foreign_keys=ON",
    _SQLITE_BUSY,
)
# A read-only connection leaves the journal mode alone: switching a fresh file to WAL is a write.
_SQLITE_READER_PRAGMAS = (_SQLITE_BUSY,)


class Database:
    """An async engine for SQLite or Postgres. Create it with `sqlite()` or `postgres()`."""

    def __init__(self, engine: AsyncEngine, sqlite_path: Path | None = None) -> None:
        self.engine = engine
        self.sqlite_path = sqlite_path  # the file of a SQLite database
        # Tasks holding SQLite's write lock.
        self._writers: weakref.WeakSet[asyncio.Task[Any]] = weakref.WeakSet()
        # Told what a commit queued, on SQLite (a channel, and the job's kind on `JOBS`); on
        # Postgres the commit sends `NOTIFY` instead. See `SqlWakeup`.
        self.listeners: list[Callable[[Channel, str | None], None]] = []

    @classmethod
    def sqlite(cls, path: Path, *, read_only: bool = False) -> "Database":
        """A SQLite database file (created by `migrate`). Only on a local volume: WAL mode
        does not work on network file systems.

        `read_only`, for the schema check: the file is opened read-only and its journal mode is
        left alone, so a check never writes. On a fresh file the switch to WAL is a write; a
        check polling while the migration created the file switched it too, and SQLite answers
        the one promoting its read to a write with SQLITE_BUSY at once instead of waiting (it
        would deadlock), which failed the migration."""
        if read_only:
            url = URL.create(
                "sqlite+aiosqlite", database=f"file:{path}", query={"mode": "ro", "uri": "true"}
            )
            engine = create_async_engine(url)
            event.listen(engine.sync_engine, "connect", _configure_sqlite_reader)
        else:
            engine = create_async_engine(URL.create("sqlite+aiosqlite", database=str(path)))
            event.listen(engine.sync_engine, "connect", _configure_sqlite)
        return cls(engine, sqlite_path=path)

    @classmethod
    def postgres(cls, *, host: str, port: int, name: str, user: str, password: str) -> "Database":
        url = URL.create(
            "postgresql+asyncpg",
            username=user,
            password=password,
            host=host,
            port=port,
            database=name,
        )
        return cls(create_async_engine(url))

    @property
    def is_sqlite(self) -> bool:
        return self.engine.dialect.name == "sqlite"

    async def connect_raw(self) -> Any:
        """Postgres: a connection of the driver (asyncpg) outside the pool, for `LISTEN`; the
        caller closes it."""
        if self.is_sqlite:
            raise RuntimeError("SQLite has no connections to listen on")
        url = self.engine.url
        return await asyncpg.connect(
            host=url.host,
            port=url.port,
            user=url.username,
            password=url.password,
            database=url.database,
            server_settings={"application_name": "lekto listener"},
        )

    def insert(self, table: Table) -> PostgresInsert | SqliteInsert:
        """An INSERT in the database's dialect: one that can take `ON CONFLICT`."""
        return sqlite.insert(table) if self.is_sqlite else postgresql.insert(table)

    async def begin_write(self, connection: AsyncConnection) -> None:
        """Start the write transaction on `connection`; call before its first write and call
        `end_write` when the transaction ends."""
        if not self.is_sqlite:
            return
        task = asyncio.current_task()
        if task is not None:
            if task in self._writers:
                raise RuntimeError(
                    "this task already has an open write transaction; on SQLite a second one "
                    "would wait for its own lock"
                )
            self._writers.add(task)
        try:
            await connection.exec_driver_sql("BEGIN IMMEDIATE")
        except BaseException:
            self.end_write()
            raise

    def end_write(self) -> None:
        """The current task's write transaction has ended (committed or rolled back)."""
        task = asyncio.current_task()
        if task is not None:
            self._writers.discard(task)

    @asynccontextmanager
    async def reading(self) -> AsyncIterator[AsyncConnection]:
        """A connection for reads; nothing is committed."""
        async with self.engine.connect() as connection:
            yield connection

    @asynccontextmanager
    async def writing(self) -> AsyncIterator[AsyncConnection]:
        """A write transaction, committed when the block ends without an exception."""
        async with self.engine.connect() as connection:
            await self.begin_write(connection)
            try:
                yield connection
                await connection.commit()
            finally:
                self.end_write()

    async def dispose(self) -> None:
        await self.engine.dispose()


def _configure_sqlite(dbapi_connection: Any, _record: object) -> None:
    _apply(dbapi_connection, _SQLITE_PRAGMAS)


def _configure_sqlite_reader(dbapi_connection: Any, _record: object) -> None:
    _apply(dbapi_connection, _SQLITE_READER_PRAGMAS)


def _apply(dbapi_connection: Any, pragmas: tuple[str, ...]) -> None:
    # Autocommit in the driver: the adapter emits BEGIN itself (see the module docstring).
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    try:
        for pragma in pragmas:
            cursor.execute(pragma)
    finally:
        cursor.close()
