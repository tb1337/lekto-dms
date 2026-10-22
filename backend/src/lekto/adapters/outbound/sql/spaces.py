"""Spaces and their members, and which documents a user reaches through them."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Row, Select, and_, delete, or_, select

from lekto.adapters.outbound.sql import tables as t
from lekto.adapters.outbound.sql.repositories import SqlRepository, Values
from lekto.core.domain.errors import NotFoundError
from lekto.core.domain.ids import SpaceId, UserId
from lekto.core.domain.pipeline import Lane
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.validation import name_key


class SqlSpaceRepository(SqlRepository[SpaceId, Space]):
    kind = "space"
    table = t.spaces

    async def get_personal(self, user: UserId) -> Space:
        found = await self._load(t.spaces.c.personal_of == user)
        if not found:
            raise NotFoundError("personal space of user", user)
        return found[0]

    async def personal_ids(self) -> dict[UserId, SpaceId]:
        rows = await self._tx.read(
            select(t.spaces.c.personal_of, t.spaces.c.id).where(t.spaces.c.personal_of.is_not(None))
        )
        return {UserId(row.personal_of): SpaceId(row.id) for row in rows}

    async def find_by_name(self, name: str) -> Space | None:
        found = await self._load(
            and_(t.spaces.c.personal_of.is_(None), t.spaces.c.name_key == name_key(name))
        )
        return found[0] if found else None

    async def list_accessible(self, user: UserId) -> list[Space]:
        return await self._load(t.spaces.c.id.in_(member_space_ids(user)))

    async def _entities(self, rows: Sequence[Row[Any]]) -> list[Space]:
        members = await self._children(t.space_members, "space_id", (row.id for row in rows))
        return [
            Space(
                id=SpaceId(row.id),
                name=row.name,
                personal_of=None if row.personal_of is None else UserId(row.personal_of),
                members={
                    UserId(member.user_id): SpaceRole(member.role) for member in members[row.id]
                },
                created_at=row.created_at,
                version=row.version,
            )
            for row in rows
        ]

    def _values(self, entity: Space) -> Values:
        return {
            "id": entity.id,
            "name": entity.name,
            "name_key": name_key(entity.name),
            "personal_of": entity.personal_of,
            "created_at": entity.created_at,
            "version": entity.version,
        }

    async def _write_children(self, entity: Space) -> None:
        await self._insert_many(
            t.space_members,
            [
                {"space_id": entity.id, "user_id": user_id, "role": role.value}
                for user_id, role in entity.members.items()
            ],
        )

    async def _delete_children(self, ids: list[UUID]) -> None:
        await self._tx.write(delete(t.space_members).where(t.space_members.c.space_id.in_(ids)))


def visible_to(user: UserId) -> ColumnElement[bool]:
    """The reach of `lekto.core.domain.permissions`: every document in the spaces the user
    edits, the green ones in the spaces they read."""
    documents = t.documents
    return or_(
        documents.c.space_id.in_(member_space_ids(user, SpaceRole.EDIT)),
        and_(
            documents.c.lane == Lane.GREEN.value,
            documents.c.space_id.in_(member_space_ids(user, SpaceRole.READ)),
        ),
    )


def member_space_ids(user: UserId, role: SpaceRole | None = None) -> Select[tuple[UUID]]:
    """Subquery: ids of the spaces the user is a member of, in `role` if given."""
    members = t.space_members
    query = select(members.c.space_id).where(members.c.user_id == user)
    if role is not None:
        query = query.where(members.c.role == role.value)
    return query
