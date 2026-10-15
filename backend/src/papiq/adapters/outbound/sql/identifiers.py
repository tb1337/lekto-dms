"""The identifiers each document shows, in `document_identifiers`."""

from collections import defaultdict
from collections.abc import Collection

from sqlalchemy import and_, delete, insert, or_, select

from papiq.adapters.outbound.sql import tables as t
from papiq.adapters.outbound.sql.transaction import Transaction
from papiq.core.domain.identifiers import IdentifierKind
from papiq.core.domain.ids import ContactId, DocumentId

type Key = tuple[IdentifierKind, str]
_BATCH = 200  # identifiers per query


class SqlDocumentIdentifierRepository:
    def __init__(self, transaction: Transaction) -> None:
        self._tx = transaction

    async def replace(self, document: DocumentId, identifiers: Collection[Key]) -> None:
        table = t.document_identifiers
        await self._tx.write(delete(table).where(table.c.document_id == document))
        rows = [
            {"document_id": document, "kind": kind.value, "value": value}
            for kind, value in sorted(set(identifiers))
        ]
        if rows:
            await self._tx.write(insert(table), rows)

    async def contacts_of(self, identifiers: Collection[Key]) -> dict[Key, frozenset[ContactId]]:
        table, documents = t.document_identifiers, t.documents
        found: dict[Key, set[ContactId]] = defaultdict(set)
        keys = sorted(set(identifiers))
        for start in range(0, len(keys), _BATCH):
            wanted = or_(
                *(
                    and_(table.c.kind == kind.value, table.c.value == value)
                    for kind, value in keys[start : start + _BATCH]
                )
            )
            query = (
                select(table.c.kind, table.c.value, documents.c.contact_id)
                .join(documents, documents.c.id == table.c.document_id)
                .where(
                    wanted,
                    documents.c.confirmed_at.is_not(None),
                    documents.c.contact_id.is_not(None),
                )
                .distinct()
            )
            for row in await self._tx.read(query):
                found[(IdentifierKind(row.kind), row.value)].add(ContactId(row.contact_id))
        return {key: frozenset(contacts) for key, contacts in found.items()}
