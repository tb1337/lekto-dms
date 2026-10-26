"""The relations between documents, in `document_relations`."""

from collections.abc import Collection
from typing import Any

from sqlalchemy import Row, and_, delete, insert, or_, select

from lekto.adapters.outbound.sql import tables as t
from lekto.adapters.outbound.sql.repositories import KEYS_PER_QUERY
from lekto.adapters.outbound.sql.transaction import Transaction
from lekto.core.domain.ids import DocumentId, UserId
from lekto.core.domain.relations import Relation, RelationOrigin, RelationState


class SqlDocumentRelationRepository:
    def __init__(self, transaction: Transaction) -> None:
        self._tx = transaction

    async def of_document(self, document: DocumentId) -> list[Relation]:
        return await self.of_documents([document])

    async def of_documents(self, documents: Collection[DocumentId]) -> list[Relation]:
        table = t.document_relations
        ids = sorted(set(documents))
        found: dict[tuple[DocumentId, DocumentId], Relation] = {}
        for start in range(0, len(ids), KEYS_PER_QUERY):
            chunk = ids[start : start + KEYS_PER_QUERY]
            rows = await self._tx.read(
                select(table).where(or_(table.c.newer_id.in_(chunk), table.c.older_id.in_(chunk)))
            )
            for row in rows:
                relation = _relation(row)
                found[relation.key] = relation
        return sorted(found.values(), key=lambda item: (item.created_at, item.key), reverse=True)

    async def find(self, newer: DocumentId, older: DocumentId) -> Relation | None:
        table = t.document_relations
        rows = list(
            await self._tx.read(
                select(table).where(and_(table.c.newer_id == newer, table.c.older_id == older))
            )
        )
        return _relation(rows[0]) if rows else None

    async def put(self, relation: Relation) -> None:
        await self.remove(relation.newer, relation.older)
        await self._tx.write(insert(t.document_relations), [_row(relation)])

    async def remove(self, newer: DocumentId, older: DocumentId) -> None:
        table = t.document_relations
        await self._tx.write(
            delete(table).where(and_(table.c.newer_id == newer, table.c.older_id == older))
        )


def _row(relation: Relation) -> dict[str, Any]:
    return {
        "newer_id": relation.newer,
        "older_id": relation.older,
        "origin": relation.origin.value,
        "state": relation.state.value,
        "evidence": dict(relation.evidence),
        "created_at": relation.created_at,
        "decided_by": relation.decided_by,
        "decided_at": relation.decided_at,
    }


def _relation(row: Row[Any]) -> Relation:
    return Relation(
        newer=DocumentId(row.newer_id),
        older=DocumentId(row.older_id),
        origin=RelationOrigin(row.origin),
        state=RelationState(row.state),
        evidence=dict(row.evidence or {}),
        created_at=row.created_at,
        decided_by=None if row.decided_by is None else UserId(row.decided_by),
        decided_at=row.decided_at,
    )
