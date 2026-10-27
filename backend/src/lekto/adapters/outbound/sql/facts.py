"""The facts of each document, in `document_facts`."""

from collections import defaultdict
from collections.abc import Collection
from typing import Any

from sqlalchemy import Row, and_, delete, insert, or_, select

from lekto.adapters.outbound.sql import tables as t
from lekto.adapters.outbound.sql.repositories import KEYS_PER_QUERY
from lekto.adapters.outbound.sql.transaction import Transaction
from lekto.core.domain.document_facts import (
    DocumentFact,
    FactOrigin,
    FactRole,
    FactState,
    check_decided,
    check_found,
    merged,
    reading_order,
    withdrawn,
)
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import ContactId, DocumentId

type Key = tuple[IdentifierKind, str]

_BATCH = 500
"""Documents per query of `of_documents` (the parameters of an `IN`)."""


class SqlDocumentFactRepository:
    def __init__(self, transaction: Transaction) -> None:
        self._tx = transaction

    async def of_document(self, document: DocumentId) -> list[DocumentFact]:
        table = t.document_facts
        rows = await self._tx.read(select(table).where(table.c.document_id == document))
        return sorted((_fact(row) for row in rows), key=reading_order)

    async def of_documents(
        self, documents: Collection[DocumentId]
    ) -> dict[DocumentId, list[DocumentFact]]:
        table = t.document_facts
        found: dict[DocumentId, list[DocumentFact]] = {}
        ids = list(documents)
        for start in range(0, len(ids), _BATCH):
            chunk = ids[start : start + _BATCH]
            for row in await self._tx.read(select(table).where(table.c.document_id.in_(chunk))):
                found.setdefault(DocumentId(row.document_id), []).append(_fact(row))
        return {id: sorted(facts, key=reading_order) for id, facts in found.items()}

    async def replace_found(self, document: DocumentId, found: Collection[DocumentFact]) -> None:
        check_found(found)
        table = t.document_facts
        # Only the rows found go: a person's decision written meanwhile is never deleted (a
        # found fact of its key then fails on the primary key instead).
        await self._tx.write(
            delete(table).where(
                table.c.document_id == document, table.c.state == FactState.FOUND.value
            )
        )
        decided = await self.of_document(document)
        new = [fact for fact in merged(decided, found) if not fact.state.by_person]
        if new:
            await self._tx.write(insert(table), [_row(document, fact) for fact in new])

    async def decide(self, document: DocumentId, fact: DocumentFact) -> None:
        check_decided(fact)
        table = t.document_facts
        await self._tx.write(
            delete(table).where(
                table.c.document_id == document,
                table.c.kind == fact.kind.value,
                table.c.value == fact.value,
            )
        )
        await self._tx.write(insert(table), [_row(document, fact)])

    async def withdraw(self, document: DocumentId, key: Key) -> None:
        table = t.document_facts
        kind, value = key
        where = and_(
            table.c.document_id == document,
            table.c.kind == kind.value,
            table.c.value == value,
            table.c.state != FactState.FOUND.value,
        )
        rows = list(await self._tx.read(select(table).where(where)))
        if not rows:
            return
        await self._tx.write(delete(table).where(where))
        found = withdrawn(_fact(rows[0]))
        if found is not None:
            await self._tx.write(insert(table), [_row(document, found)])

    async def contacts_of(self, identifiers: Collection[Key]) -> dict[Key, frozenset[ContactId]]:
        table, documents = t.document_facts, t.documents
        found: dict[Key, set[ContactId]] = defaultdict(set)
        keys = sorted(set(identifiers))
        for start in range(0, len(keys), KEYS_PER_QUERY):
            wanted = or_(
                *(
                    and_(table.c.kind == kind.value, table.c.value == value)
                    for kind, value in keys[start : start + KEYS_PER_QUERY]
                )
            )
            query = (
                select(table.c.kind, table.c.value, documents.c.contact_id)
                .join(documents, documents.c.id == table.c.document_id)
                .where(
                    wanted,
                    table.c.state != FactState.REJECTED.value,
                    documents.c.confirmed_at.is_not(None),
                    documents.c.contact_id.is_not(None),
                )
                .distinct()
            )
            for row in await self._tx.read(query):
                found[(IdentifierKind(row.kind), row.value)].add(ContactId(row.contact_id))
        return {key: frozenset(contacts) for key, contacts in found.items()}


def _row(document: DocumentId, fact: DocumentFact) -> dict[str, object]:
    return {
        "document_id": document,
        "kind": fact.kind.value,
        "value": fact.value,
        "role": fact.role.value,
        "origins": ",".join(sorted(origin.value for origin in fact.origins)),
        "written": fact.written,
        "position": fact.position,
        "state": fact.state.value,
    }


def _fact(row: Row[Any]) -> DocumentFact:
    return DocumentFact(
        kind=IdentifierKind(row.kind),
        value=row.value,
        role=FactRole(row.role),
        origins=frozenset(FactOrigin(item) for item in row.origins.split(",")),
        written=row.written,
        position=row.position,
        state=FactState(row.state),
    )
