"""Actions on many documents at once, in `bulk_operations`."""

from typing import Any
from uuid import UUID

from sqlalchemy import Row

from lekto.adapters.outbound.sql import tables as t
from lekto.adapters.outbound.sql.repositories import SqlRepository, Values
from lekto.core.domain.bulk import BulkAction, BulkOperation, BulkStatus
from lekto.core.domain.ids import BulkOperationId, DocumentId, UserId
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.reasons import Reason


class SqlBulkOperationRepository(SqlRepository[BulkOperationId, BulkOperation]):
    kind = "bulk operation"
    table = t.bulk_operations

    def _entity(self, row: Row[Any]) -> BulkOperation:
        return BulkOperation(
            id=BulkOperationId(row.id),
            user_id=UserId(row.user_id),
            action=BulkAction.from_json(row.action),
            documents=tuple(DocumentId(UUID(item)) for item in row.documents),
            status=BulkStatus(row.status),
            position=row.position,
            changed=row.changed,
            unchanged=row.unchanged,
            skipped=[
                (DocumentId(UUID(item[0])), Reason.from_json(item[1])) for item in row.skipped
            ],
            error=row.error,
            created_at=row.created_at,
            finished_at=row.finished_at,
            version=row.version,
        )

    def _values(self, entity: BulkOperation) -> Values:
        skipped: list[JsonValue] = [[str(id), reason.to_json()] for id, reason in entity.skipped]
        return {
            "id": entity.id,
            "user_id": entity.user_id,
            "action": entity.action.to_json(),
            "status": entity.status.value,
            "documents": [str(id) for id in entity.documents],
            "position": entity.position,
            "changed": entity.changed,
            "unchanged": entity.unchanged,
            "skipped": skipped,
            "error": entity.error,
            "created_at": entity.created_at,
            "finished_at": entity.finished_at,
            "version": entity.version,
        }
