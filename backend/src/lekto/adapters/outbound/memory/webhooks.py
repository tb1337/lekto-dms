"""In-memory webhook repository, on the tables of the in-memory unit of work."""

import copy
from collections import Counter
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from lekto.adapters.outbound.memory.database import WEBHOOK_DELIVERIES, Table
from lekto.adapters.outbound.memory.rows import _REMOVED, MemoryRepository, _copy
from lekto.core.domain.errors import NotFoundError
from lekto.core.domain.ids import UserId, WebhookId
from lekto.core.domain.webhooks import DeliveryOutcome, Webhook, WebhookDelivery
from lekto.core.ports.repository import PAGE_SIZE

if TYPE_CHECKING:
    from lekto.adapters.outbound.memory.unit_of_work import MemoryUnitOfWork


@dataclass
class DeliveryRow:
    """A logged delivery; `version` only for the unit of work's bookkeeping."""

    id: UUID
    item: WebhookDelivery
    version: int = 1


class MemoryWebhookRepository(MemoryRepository[WebhookId, Webhook]):
    def __init__(self, uow: "MemoryUnitOfWork", table: Table[Webhook]) -> None:
        super().__init__(uow, table)
        self._deliveries = MemoryRepository[UUID, DeliveryRow](uow, WEBHOOK_DELIVERIES)

    async def remove(self, id: WebhookId) -> None:
        self._deliveries._remove_rows(
            [row for row in self._deliveries._all() if row.item.webhook_id == id]
        )
        if self._uow._row(self._table, id) is not _REMOVED:
            self._uow._write(self._table, id, _REMOVED)

    async def remove_for_owner(self, owner: UserId) -> int:
        webhooks = [row for row in self._all() if row.owner_id == owner]
        ids = {row.id for row in webhooks}
        self._deliveries._remove_rows(
            [row for row in self._deliveries._all() if row.item.webhook_id in ids]
        )
        return self._remove_rows(webhooks)

    async def list_for_owner(self, owner: UserId) -> list[Webhook]:
        return self._oldest_first(row for row in self._all() if row.owner_id == owner)

    async def list_all(self) -> list[Webhook]:
        return self._oldest_first(self._all())

    async def count_for_owner(self, owner: UserId) -> int:
        return sum(1 for row in self._all() if row.owner_id == owner)

    async def list_active_for(self, event_type: str) -> list[Webhook]:
        return self._oldest_first(
            row for row in self._all() if row.active and row.wants(event_type)
        )

    async def list_model_calls(self) -> list[Webhook]:
        return self._oldest_first(row for row in self._all() if row.model_call is not None)

    async def add_delivery(self, delivery: WebhookDelivery) -> None:
        if self._uow._row(self._table, delivery.webhook_id) is _REMOVED:
            raise NotFoundError("webhook", delivery.webhook_id)
        await self._deliveries.add(DeliveryRow(delivery.id, delivery))

    async def deliveries(
        self,
        webhook: WebhookId,
        *,
        outcomes: Collection[DeliveryOutcome] | None = None,
        event_type: str | None = None,
        offset: int = 0,
        limit: int = PAGE_SIZE,
    ) -> list[WebhookDelivery]:
        rows = [
            row.item
            for row in self._deliveries._all()
            if row.item.webhook_id == webhook
            and (outcomes is None or row.item.outcome in outcomes)
            and (event_type is None or row.item.event_type == event_type)
        ]
        rows.sort(key=lambda delivery: delivery.id, reverse=True)
        return [copy.deepcopy(row) for row in rows[offset : offset + limit]]

    async def delivery_counts(
        self, webhook: WebhookId, *, event_type: str | None = None
    ) -> dict[DeliveryOutcome, int]:
        return dict(
            Counter(
                row.item.outcome
                for row in self._deliveries._all()
                if row.item.webhook_id == webhook
                and (event_type is None or row.item.event_type == event_type)
            )
        )

    async def delivery_event_types(self, webhook: WebhookId) -> list[str]:
        return sorted(
            {
                row.item.event_type
                for row in self._deliveries._all()
                if row.item.webhook_id == webhook
            }
        )

    async def purge_deliveries(self, *, before: datetime) -> int:
        return self._deliveries._remove_rows(
            [row for row in self._deliveries._all() if row.item.started_at < before]
        )

    def _oldest_first(self, rows: Iterable[Webhook]) -> list[Webhook]:
        found = sorted(rows, key=lambda row: (row.created_at, row.id))
        return [_copy(row) for row in found]
