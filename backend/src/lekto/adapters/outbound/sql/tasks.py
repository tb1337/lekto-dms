"""Task repository on SQL tables."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Row, delete, func, select

from lekto.adapters.outbound.sql import tables as t
from lekto.adapters.outbound.sql.repositories import SqlRepository, Values
from lekto.core.domain.ids import DocumentId, TaskId, UserId, WebhookId
from lekto.core.domain.pipeline import Node
from lekto.core.domain.reasons import Reason
from lekto.core.domain.tasks import Task, TaskKind, TaskStatus, TaskStep


class SqlTaskRepository(SqlRepository[TaskId, Task]):
    kind = "task"
    table = t.tasks

    async def list_for_run(self, document: DocumentId, node: Node, run: int) -> list[Task]:
        table = self.table
        rows = await self._tx.read(
            select(table)
            .where(table.c.document_id == document, table.c.node == node.value, table.c.run == run)
            .order_by(table.c.created_at, table.c.id)
        )
        return [self._entity(row) for row in rows]

    async def list_unsettled_for(self, document: DocumentId) -> list[Task]:
        table = self.table
        rows = await self._tx.read(
            select(table)
            .where(table.c.document_id == document, table.c.status.in_(_UNSETTLED))
            .order_by(table.c.created_at, table.c.id)
        )
        return [self._entity(row) for row in rows]

    async def count_open(self, webhook: WebhookId) -> int:
        table = self.table
        result = await self._tx.read(
            select(func.count())
            .select_from(table)
            .where(table.c.webhook_id == webhook, table.c.status == TaskStatus.OPEN.value)
        )
        return int(result.scalar_one())

    async def queued(self, webhook: WebhookId, *, limit: int) -> list[Task]:
        table = self.table
        rows = await self._tx.read(
            select(table)
            .where(table.c.webhook_id == webhook, table.c.status == TaskStatus.QUEUED.value)
            .order_by(table.c.created_at, table.c.id)
            .limit(limit)
        )
        return [self._entity(row) for row in rows]

    async def purge(self, *, before: datetime) -> int:
        table = self.table
        result = await self._tx.write(delete(table).where(table.c.settled_at < before))
        return int(result.rowcount)

    def _entity(self, row: Row[Any]) -> Task:
        return Task(
            id=TaskId(row.id),
            kind=TaskKind(row.kind),
            document_id=DocumentId(row.document_id),
            node=Node(row.node),
            run=row.run,
            webhook_id=WebhookId(row.webhook_id),
            owner_id=UserId(row.owner_id),
            step=None if row.step is None else TaskStep.from_json(row.step),
            timeout=timedelta(seconds=row.timeout_seconds),
            status=TaskStatus(row.status),
            token_hash=row.token_hash,
            encrypted_request=None if row.request is None else bytes(row.request),
            answer=row.answer,
            producer=row.producer,
            reason=None if row.reason is None else Reason.from_json(row.reason),
            created_at=row.created_at,
            opened_at=row.opened_at,
            deadline=row.deadline,
            settled_at=row.settled_at,
            version=row.version,
        )

    def _values(self, entity: Task) -> Values:
        return {
            "id": entity.id,
            "kind": entity.kind.value,
            "document_id": entity.document_id,
            "node": entity.node.value,
            "run": entity.run,
            "webhook_id": entity.webhook_id,
            "owner_id": entity.owner_id,
            "step": None if entity.step is None else entity.step.to_json(),
            "timeout_seconds": int(entity.timeout.total_seconds()),
            "status": entity.status.value,
            "token_hash": entity.token_hash,
            "request": entity.encrypted_request,
            "answer": entity.answer,
            "producer": entity.producer,
            "reason": None if entity.reason is None else entity.reason.to_json(),
            "created_at": entity.created_at,
            "opened_at": entity.opened_at,
            "deadline": entity.deadline,
            "settled_at": entity.settled_at,
            "version": entity.version,
        }


_UNSETTLED = (TaskStatus.QUEUED.value, TaskStatus.OPEN.value)
