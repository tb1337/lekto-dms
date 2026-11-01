"""The generic repository on SQL tables, with the explicit mapping between domain objects and
rows; the repositories by area (users, spaces, master data, documents) build on it.

`update` is optimistic: `UPDATE ... WHERE id = :id AND version = :version`. If no row matches,
the entity is missing (NotFoundError) or was changed by someone else (ConcurrencyError). On
Postgres, a concurrent update of the same row waits for the other transaction and then finds
the new version; on SQLite, writers are serialized by the write lock.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import ColumnElement, Row, Table, delete, insert, select, true, update

from lekto.adapters.outbound.sql.transaction import Transaction
from lekto.core.domain.entity import Entity
from lekto.core.domain.errors import ConcurrencyError, NotFoundError
from lekto.core.domain.identity import ViaToken

type Values = dict[str, Any]


def via_columns(via: ViaToken | None) -> Values:
    """The columns of `tables._via_token` for `via`."""
    return {
        "via_token_id": None if via is None else via.id,
        "via_token_name": None if via is None else via.name,
    }


KEYS_PER_QUERY = 200
"""Keys a query takes as parameters at most, so that their number and the statement's length
stay bounded (SQLite allows 32 766 parameters, asyncpg 32 767)."""


class SqlRepository[K: UUID, E: Entity[UUID]]:
    """Common part: a main table with its key (`key`, `id` unless a table names it otherwise)
    and `version`, optionally child tables."""

    kind: ClassVar[str]
    table: ClassVar[Table]
    key: ClassVar[str] = "id"

    def __init__(self, transaction: Transaction) -> None:
        self._tx = transaction

    async def get(self, id: K) -> E:
        entity = await self.find(id)
        if entity is None:
            raise NotFoundError(self.kind, id)
        return entity

    async def find(self, id: K) -> E | None:
        found = await self._load(self.table.c[self.key] == id)
        return found[0] if found else None

    async def add(self, entity: E) -> None:
        await self._tx.write(insert(self.table).values(self._values(entity)))
        await self._write_children(entity)

    async def update(self, entity: E) -> None:
        id, version = entity.id, entity.version
        key = self.table.c[self.key]
        result = await self._tx.write(
            update(self.table)
            .where(key == id, self.table.c.version == version)
            .values({**self._changed(entity), "version": version + 1})
        )
        if result.rowcount == 0:
            exists = await self._tx.read(select(key).where(key == id))
            if exists.first() is None:
                raise NotFoundError(self.kind, id)
            raise ConcurrencyError(f"{self.kind} {id} was changed concurrently")
        entity.version = version + 1
        await self._delete_children([id])
        await self._write_children(entity)

    def _changed(self, entity: E) -> Values:
        """The columns `update` writes: all of them, unless a repository keeps a column that
        never changes after `add` out of it (a large one, written once)."""
        return self._values(entity)

    async def list_all(self) -> list[E]:
        return await self._load(true())

    async def remove(self, id: K) -> None:
        """Child tables go with the row (ON DELETE CASCADE)."""
        result = await self._tx.write(delete(self.table).where(self.table.c[self.key] == id))
        if result.rowcount == 0:
            raise NotFoundError(self.kind, id)

    async def _load(self, where: ColumnElement[bool]) -> list[E]:
        rows = (await self._tx.read(select(self.table).where(where))).all()
        return await self._entities(rows)

    async def _entities(self, rows: Sequence[Row[Any]]) -> list[E]:
        return [self._entity(row) for row in rows]

    # --- mapping, implemented per entity -------------------------------------------------------

    def _values(self, entity: E) -> Values:
        """Column values of the main table, including id and version."""
        raise NotImplementedError

    def _entity(self, row: Row[Any]) -> E:
        raise NotImplementedError

    async def _write_children(self, entity: E) -> None:
        """Insert the rows of child tables."""

    async def _delete_children(self, ids: list[UUID]) -> None:
        """Delete the rows of child tables."""

    async def _insert_many(self, table: Table, rows: list[Values]) -> None:
        if rows:
            await self._tx.write(insert(table), rows)

    async def _children(
        self, table: Table, parent: str, ids: Iterable[UUID]
    ) -> dict[UUID, list[Row[Any]]]:
        """Rows of a child table, grouped by the parent column."""
        grouped: dict[UUID, list[Row[Any]]] = defaultdict(list)
        id_list = list(ids)
        if id_list:
            column = table.c[parent]
            for row in (await self._tx.read(select(table).where(column.in_(id_list)))).all():
                grouped[row._mapping[parent]].append(row)
        return grouped
