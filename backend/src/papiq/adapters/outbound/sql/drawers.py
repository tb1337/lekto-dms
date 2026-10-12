"""Drawers and their shares, and which drawers a user reaches."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Row, and_, delete, or_, select

from papiq.adapters.outbound.sql import tables as t
from papiq.adapters.outbound.sql.repositories import SqlRepository, Values
from papiq.core.domain.drawers import Drawer, ShareLevel
from papiq.core.domain.errors import NotFoundError
from papiq.core.domain.ids import DrawerId, UserId
from papiq.core.domain.pipeline import Lane
from papiq.core.domain.validation import name_key


class SqlDrawerRepository(SqlRepository[DrawerId, Drawer]):
    kind = "drawer"
    table = t.drawers

    async def get_default(self, owner: UserId) -> Drawer:
        found = await self._load(and_(t.drawers.c.owner_id == owner, t.drawers.c.is_default))
        if not found:
            raise NotFoundError("default drawer of user", owner)
        return found[0]

    async def list_accessible(self, user: UserId) -> list[Drawer]:
        return await self._load(t.drawers.c.id.in_(accessible_drawer_ids(user)))

    async def _entities(self, rows: Sequence[Row[Any]]) -> list[Drawer]:
        shares = await self._children(t.drawer_shares, "drawer_id", (row.id for row in rows))
        return [
            Drawer(
                id=DrawerId(row.id),
                owner_id=UserId(row.owner_id),
                name=row.name,
                is_default=row.is_default,
                shares={UserId(share.user_id): ShareLevel(share.level) for share in shares[row.id]},
                created_at=row.created_at,
                version=row.version,
            )
            for row in rows
        ]

    def _values(self, entity: Drawer) -> Values:
        return {
            "id": entity.id,
            "owner_id": entity.owner_id,
            "name": entity.name,
            "name_key": name_key(entity.name),
            "is_default": entity.is_default,
            "created_at": entity.created_at,
            "version": entity.version,
        }

    async def _write_children(self, entity: Drawer) -> None:
        await self._insert_many(
            t.drawer_shares,
            [
                {"drawer_id": entity.id, "user_id": user_id, "level": level.value}
                for user_id, level in entity.shares.items()
            ],
        )

    async def _delete_children(self, ids: list[DrawerId]) -> None:
        await self._tx.write(delete(t.drawer_shares).where(t.drawer_shares.c.drawer_id.in_(ids)))


def visible_to(user: UserId) -> ColumnElement[bool]:
    """The reach of `papiq.core.domain.permissions`: own documents, and green documents in
    drawers the user owns or that are shared with them."""
    documents = t.documents
    return or_(
        documents.c.owner_id == user,
        and_(
            documents.c.lane == Lane.GREEN.value,
            documents.c.drawer_id.in_(accessible_drawer_ids(user)),
        ),
    )


def accessible_drawer_ids(user: UserId) -> Any:
    """Subquery: ids of the drawers the user owns or that are shared with them."""
    return (
        select(t.drawers.c.id)
        .where(t.drawers.c.owner_id == user)
        .union(select(t.drawer_shares.c.drawer_id).where(t.drawer_shares.c.user_id == user))
    )
