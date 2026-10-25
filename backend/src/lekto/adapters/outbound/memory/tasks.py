"""In-memory task repository, on the tables of the in-memory unit of work."""

from collections.abc import Iterable
from datetime import datetime

from lekto.adapters.outbound.memory.rows import MemoryRepository, _copy
from lekto.core.domain.ids import DocumentId, TaskId, WebhookId
from lekto.core.domain.pipeline import Node
from lekto.core.domain.tasks import Task, TaskStatus


class MemoryTaskRepository(MemoryRepository[TaskId, Task]):
    async def list_for_run(self, document: DocumentId, node: Node, run: int) -> list[Task]:
        return _oldest_first(
            row
            for row in self._all()
            if row.document_id == document and row.node is node and row.run == run
        )

    async def list_unsettled_for(self, document: DocumentId) -> list[Task]:
        return _oldest_first(
            row for row in self._all() if row.document_id == document and not row.status.settled
        )

    async def count_open(self, webhook: WebhookId) -> int:
        return sum(
            1 for row in self._all() if row.webhook_id == webhook and row.status is TaskStatus.OPEN
        )

    async def queued(self, webhook: WebhookId, *, limit: int) -> list[Task]:
        return _oldest_first(
            row
            for row in self._all()
            if row.webhook_id == webhook and row.status is TaskStatus.QUEUED
        )[:limit]

    async def purge(self, *, before: datetime) -> int:
        return self._remove_rows(
            [row for row in self._all() if row.settled_at is not None and row.settled_at < before]
        )


def _oldest_first(rows: Iterable[Task]) -> list[Task]:
    return [_copy(row) for row in sorted(rows, key=lambda row: (row.created_at, row.id))]
