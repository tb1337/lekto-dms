"""Users and their profiles."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Row, delete

from lekto.adapters.outbound.sql import tables as t
from lekto.adapters.outbound.sql.repositories import SqlRepository, Values
from lekto.core.domain.identifiers import Identifier, IdentifierKind
from lekto.core.domain.ids import UserId
from lekto.core.domain.profiles import Profile
from lekto.core.domain.users import Role, User
from lekto.core.domain.validation import name_key


class SqlUserRepository(SqlRepository[UserId, User]):
    kind = "user"
    table = t.users

    async def find_by_username(self, username: str) -> User | None:
        found = await self._load(t.users.c.username_key == name_key(username))
        return found[0] if found else None

    def _values(self, entity: User) -> Values:
        return {
            "id": entity.id,
            "username": entity.username,
            "username_key": name_key(entity.username),
            "role": entity.role.value,
            "created_at": entity.created_at,
            "active": entity.active,
            "version": entity.version,
            "display_name": entity.display_name,
            "display_name_key": None
            if entity.display_name is None
            else name_key(entity.display_name),
        }

    def _entity(self, row: Row[Any]) -> User:
        return User(
            id=UserId(row.id),
            username=row.username,
            role=Role(row.role),
            created_at=row.created_at,
            active=row.active,
            display_name=row.display_name,
            version=row.version,
        )


class SqlProfileRepository(SqlRepository[UserId, Profile]):
    kind = "profile"
    table = t.user_profiles
    key = "user_id"

    def _values(self, entity: Profile) -> Values:
        return {
            "user_id": entity.id,
            "birth_date": entity.birth_date,
            "email": entity.email,
            "version": entity.version,
        }

    async def _entities(self, rows: Sequence[Row[Any]]) -> list[Profile]:
        ids = [row.user_id for row in rows]
        aliases = await self._children(t.user_aliases, "user_id", ids)
        identifiers = await self._children(t.user_identifiers, "user_id", ids)
        declined = await self._children(t.user_declined_identifiers, "user_id", ids)
        return [
            Profile(
                id=UserId(row.user_id),
                aliases=[
                    alias.name for alias in sorted(aliases[row.user_id], key=lambda a: a.position)
                ],
                birth_date=row.birth_date,
                email=row.email,
                identifiers=sorted(
                    (
                        Identifier(IdentifierKind(item.kind), item.value)
                        for item in identifiers[row.user_id]
                    ),
                    key=lambda item: (item.kind.value, item.value),
                ),
                declined=[
                    Identifier(IdentifierKind(item.kind), item.value)
                    for item in declined[row.user_id]
                ],
                version=row.version,
            )
            for row in rows
        ]

    async def _write_children(self, entity: Profile) -> None:
        await self._insert_many(
            t.user_aliases,
            [
                {
                    "user_id": entity.id,
                    "name": alias,
                    "name_key": name_key(alias),
                    "position": position,
                }
                for position, alias in enumerate(entity.aliases)
            ],
        )
        await self._insert_many(
            t.user_identifiers,
            [
                {"user_id": entity.id, "kind": item.kind.value, "value": item.value}
                for item in entity.identifiers
            ],
        )
        await self._insert_many(
            t.user_declined_identifiers,
            [
                {"user_id": entity.id, "kind": item.kind.value, "value": item.value}
                for item in entity.declined
            ],
        )

    async def _delete_children(self, ids: list[UUID]) -> None:
        for table in (t.user_aliases, t.user_identifiers, t.user_declined_identifiers):
            await self._tx.write(delete(table).where(table.c.user_id.in_(ids)))
