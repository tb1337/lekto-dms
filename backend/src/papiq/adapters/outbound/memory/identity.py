"""In-memory identity repositories, on the tables of the in-memory unit of work."""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from papiq.adapters.outbound.memory.database import Table
from papiq.adapters.outbound.memory.rows import MemoryRepository, _copy
from papiq.core.domain.identity import (
    ApiToken,
    Credential,
    ExternalIdentity,
    LoginFailures,
    Session,
    ThrottleRule,
    failure_id,
)
from papiq.core.domain.ids import ApiTokenId, ExternalIdentityId, SessionId, UserId

if TYPE_CHECKING:
    from papiq.adapters.outbound.memory.unit_of_work import MemoryUnitOfWork


class MemoryCredentialRepository(MemoryRepository[UserId, Credential]):
    async def remove(self, user: UserId) -> None:
        self._remove_rows([row for row in self._all() if row.user_id == user])


class MemorySessionRepository(MemoryRepository[SessionId, Session]):
    async def find_by_token(self, token_hash: str) -> Session | None:
        return next((_copy(row) for row in self._all() if row.token_hash == token_hash), None)

    async def touch(self, id: SessionId, last_seen_at: datetime) -> None:
        self._touch(id, "last_seen_at", last_seen_at)

    async def remove(self, id: SessionId) -> None:
        self._remove_rows([row for row in self._all() if row.id == id])

    async def remove_for_user(self, user: UserId, *, keep: SessionId | None = None) -> int:
        return self._remove_rows(
            [row for row in self._all() if row.user_id == user and row.id != keep]
        )

    async def purge(self, *, now: datetime, idle_before: datetime) -> int:
        return self._remove_rows(
            [row for row in self._all() if row.expires_at <= now or row.last_seen_at <= idle_before]
        )


class MemoryApiTokenRepository(MemoryRepository[ApiTokenId, ApiToken]):
    async def find_by_token(self, token_hash: str) -> ApiToken | None:
        return next((_copy(row) for row in self._all() if row.token_hash == token_hash), None)

    async def list_for(self, user: UserId) -> list[ApiToken]:
        rows = [row for row in self._all() if row.user_id == user]
        return [_copy(row) for row in sorted(rows, key=lambda row: (row.created_at, row.id))]

    async def touch(self, id: ApiTokenId, last_used_at: datetime) -> None:
        self._touch(id, "last_used_at", last_used_at)

    async def remove(self, id: ApiTokenId) -> None:
        self._remove_rows([row for row in self._all() if row.id == id])

    async def remove_for_user(self, user: UserId) -> int:
        return self._remove_rows([row for row in self._all() if row.user_id == user])


class MemoryExternalIdentityRepository:
    def __init__(self, uow: "MemoryUnitOfWork", table: Table[ExternalIdentity]) -> None:
        self._rows = MemoryRepository[ExternalIdentityId, ExternalIdentity](uow, table)

    async def add(self, identity: ExternalIdentity) -> None:
        await self._rows.add(identity)

    async def find(self, issuer: str, subject: str) -> ExternalIdentity | None:
        return next(
            (
                _copy(row)
                for row in self._rows._all()
                if row.issuer == issuer and row.subject == subject
            ),
            None,
        )

    async def list_for(self, user: UserId) -> list[ExternalIdentity]:
        rows = [row for row in self._rows._all() if row.user_id == user]
        return [_copy(row) for row in sorted(rows, key=lambda row: (row.created_at, row.id))]

    async def remove(self, id: ExternalIdentityId) -> None:
        self._rows._remove_rows([row for row in self._rows._all() if row.id == id])

    async def remove_for_user(self, user: UserId) -> int:
        return self._rows._remove_rows([row for row in self._rows._all() if row.user_id == user])


class MemoryLoginFailureRepository:
    """Atomic, since nothing in a call waits for anything else."""

    def __init__(self, uow: "MemoryUnitOfWork", table: Table[LoginFailures]) -> None:
        self._rows = MemoryRepository[UUID, LoginFailures](uow, table)

    async def find(self, key: str) -> LoginFailures | None:
        return await self._rows.find(failure_id(key))

    async def reserve(self, key: str, rule: ThrottleRule, now: datetime) -> timedelta | None:
        failures = await self.find(key)
        if failures is None:
            failures = LoginFailures.first(key, now)
            wait = failures.reserve(rule, now)
            await self._rows.add(failures)
            return wait
        wait = failures.reserve(rule, now)
        if wait is None:
            await self._rows.update(failures)
        return wait

    async def release(self, key: str, rule: ThrottleRule) -> None:
        failures = await self.find(key)
        if failures is not None:
            failures.release(rule)
            await self._rows.update(failures)

    async def remove(self, key: str) -> None:
        self._rows._remove_rows([row for row in self._rows._all() if row.key == key])

    async def purge(self, *, before: datetime) -> int:
        return self._rows._remove_rows(
            [
                row
                for row in self._rows._all()
                if row.first_failure_at < before
                and (row.blocked_until is None or row.blocked_until < before)
            ]
        )
