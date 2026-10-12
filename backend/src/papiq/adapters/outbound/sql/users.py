"""Users."""

from typing import Any

from sqlalchemy import Row

from papiq.adapters.outbound.sql import tables as t
from papiq.adapters.outbound.sql.repositories import SqlRepository, Values
from papiq.core.domain.ids import UserId
from papiq.core.domain.users import Role, User
from papiq.core.domain.validation import name_key


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
        }

    def _entity(self, row: Row[Any]) -> User:
        return User(
            id=UserId(row.id),
            username=row.username,
            role=Role(row.role),
            created_at=row.created_at,
            active=row.active,
            version=row.version,
        )
