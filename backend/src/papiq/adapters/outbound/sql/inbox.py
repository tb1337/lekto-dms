"""The inbox in SQL: the seen marks (`inbox_seen`) and confirmations (`inbox_confirmations`),
and the inbox's queries. `domain.inbox.inbox_state` is written here once more, as conditions on
the documents joined with the viewer's mark and the document's confirmation."""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ColumnElement,
    FromClause,
    Row,
    Select,
    and_,
    case,
    delete,
    func,
    or_,
    select,
)

from papiq.adapters.outbound.sql import tables as t
from papiq.adapters.outbound.sql.documents import SqlDocumentRepository
from papiq.adapters.outbound.sql.repositories import KEYS_PER_QUERY
from papiq.adapters.outbound.sql.transaction import Transaction
from papiq.core.domain.ids import DocumentId, UserId
from papiq.core.domain.inbox import OPEN_TABS, Confirmation, InboxTab
from papiq.core.domain.pipeline import Lane
from papiq.core.ports.repository import InboxEntry, InboxPosition

_documents, _seen, _confirmations = t.documents, t.inbox_seen, t.inbox_confirmations


class SqlInboxRepository:
    def __init__(self, transaction: Transaction, documents: SqlDocumentRepository) -> None:
        self._tx = transaction
        self._documents = documents  # reads the documents of the rows

    async def query(
        self,
        viewer: UserId,
        *,
        owner: UserId | None,
        tab: InboxTab | None,
        since: datetime,
        after: InboxPosition | None = None,
        limit: int,
    ) -> list[InboxEntry]:
        conditions = _conditions(since)
        wanted = or_(*(conditions[item] for item in OPEN_TABS)) if tab is None else conditions[tab]
        criteria = [wanted, *_whose(owner)]
        id_ = _documents.c.id
        order = [id_.desc()]
        if tab is InboxTab.DONE:  # by when they left, newest first, ties by id
            left = _left_at()
            order = [left.desc(), id_.desc()]
            if after is not None:
                assert after.left_at is not None, "a position under done names when it left"
                criteria.append(
                    or_(left < after.left_at, and_(left == after.left_at, id_ < after.id))
                )
        elif after is not None:
            criteria.append(id_ < after.id)
        rows = (
            await self._tx.read(_entry_rows(viewer).where(*criteria).order_by(*order).limit(limit))
        ).all()
        return await self._entries(rows)

    async def entry(self, viewer: UserId, document: DocumentId) -> InboxEntry | None:
        rows = (await self._tx.read(_entry_rows(viewer).where(_documents.c.id == document))).all()
        found = await self._entries(rows)
        return found[0] if found else None

    async def _entries(self, rows: Sequence[Row[Any]]) -> list[InboxEntry]:
        documents = await self._documents._entities(rows)
        return [
            InboxEntry(
                document,
                row.inbox_seen_at,
                None
                if row.inbox_confirmed_by is None
                else Confirmation(UserId(row.inbox_confirmed_by), row.inbox_confirmed_at),
            )
            for document, row in zip(documents, rows, strict=True)
        ]

    async def count(
        self, viewer: UserId, *, owner: UserId | None, since: datetime
    ) -> dict[InboxTab, int]:
        conditions = _conditions(since)
        statement = (
            select(
                *(
                    func.count(case((condition, 1))).label(tab.value)
                    for tab, condition in conditions.items()
                )
            )
            .select_from(_joined(viewer))
            .where(or_(*conditions.values()), *_whose(owner))
        )
        row = (await self._tx.read(statement)).one()
        return {tab: int(row._mapping[tab.value]) for tab in conditions}

    async def seen(
        self, viewer: UserId, documents: Collection[DocumentId]
    ) -> dict[DocumentId, datetime]:
        ids = sorted(set(documents))
        found: dict[DocumentId, datetime] = {}
        for start in range(0, len(ids), KEYS_PER_QUERY):
            statement = select(_seen.c.document_id, _seen.c.seen_at).where(
                _seen.c.user_id == viewer,
                _seen.c.document_id.in_(ids[start : start + KEYS_PER_QUERY]),
            )
            found.update(
                (DocumentId(row.document_id), row.seen_at) for row in await self._tx.read(statement)
            )
        return found

    async def mark_seen(self, viewer: UserId, document: DocumentId, at: datetime) -> None:
        await self._mark([document], viewer, at)

    async def mark_all_seen(self, viewer: UserId, *, owner: UserId | None, at: datetime) -> int:
        statement = (
            select(_documents.c.id).select_from(_joined(viewer)).where(_new(), *_whose(owner))
        )
        new = [DocumentId(row.id) for row in await self._tx.read(statement)]
        for start in range(0, len(new), KEYS_PER_QUERY):
            await self._mark(new[start : start + KEYS_PER_QUERY], viewer, at)
        return len(new)

    async def unmark_seen(self, viewer: UserId, document: DocumentId) -> None:
        await self._tx.write(
            delete(_seen).where(_seen.c.user_id == viewer, _seen.c.document_id == document)
        )

    async def record_confirmation(self, document: DocumentId, confirmation: Confirmation) -> None:
        statement = self._tx.database.insert(_confirmations).values(
            document_id=document, confirmed_by=confirmation.by, confirmed_at=confirmation.at
        )
        await self._tx.write(
            statement.on_conflict_do_update(
                index_elements=[_confirmations.c.document_id],
                set_={
                    "confirmed_by": statement.excluded.confirmed_by,
                    "confirmed_at": statement.excluded.confirmed_at,
                },
            )
        )

    async def purge(self, *, before: datetime) -> int:
        confirmations = await self._tx.write(
            delete(_confirmations).where(_confirmations.c.confirmed_at < before)
        )
        # A mark tells nothing once its document became new again after it, or is new for no
        # one: a later `new_at` is later still.
        telling_nothing = (
            select(_documents.c.id)
            .where(
                _documents.c.id == _seen.c.document_id,
                or_(_documents.c.new_at.is_(None), _documents.c.new_at > _seen.c.seen_at),
            )
            .exists()
        )
        marks = await self._tx.write(delete(_seen).where(_seen.c.seen_at < before, telling_nothing))
        return int(confirmations.rowcount) + int(marks.rowcount)

    async def remove_for_user(self, user: UserId) -> int:
        result = await self._tx.write(delete(_seen).where(_seen.c.user_id == user))
        return int(result.rowcount)

    async def _mark(self, documents: list[DocumentId], viewer: UserId, at: datetime) -> None:
        """Upsert the marks of `viewer` on `documents` with `at`."""
        if not documents:
            return
        statement = self._tx.database.insert(_seen)
        statement = statement.on_conflict_do_update(
            index_elements=[_seen.c.user_id, _seen.c.document_id],
            set_={"seen_at": statement.excluded.seen_at},
        )
        await self._tx.write(
            statement,
            [{"user_id": viewer, "document_id": id, "seen_at": at} for id in documents],
        )


def _joined(viewer: UserId) -> FromClause:
    """The documents with the viewer's seen mark and their confirmation, where there is one."""
    return _documents.outerjoin(
        _seen, and_(_seen.c.document_id == _documents.c.id, _seen.c.user_id == viewer)
    ).outerjoin(_confirmations, _confirmations.c.document_id == _documents.c.id)


def _whose(owner: UserId | None) -> list[ColumnElement[bool]]:
    return [] if owner is None else [_documents.c.owner_id == owner]


def _entry_rows(viewer: UserId) -> Select[Any]:
    """The documents with the viewer's seen mark and their confirmation, as entries read them."""
    return select(
        _documents,
        _seen.c.seen_at.label("inbox_seen_at"),
        _confirmations.c.confirmed_by.label("inbox_confirmed_by"),
        _confirmations.c.confirmed_at.label("inbox_confirmed_at"),
    ).select_from(_joined(viewer))


def _left_at() -> ColumnElement[Any]:
    """When a document under done left the inbox, on `_joined` (`domain.inbox.left_at`): the
    viewer's seen while it is new, else its confirmation."""
    return case(
        (_documents.c.new_at.is_not(None), _seen.c.seen_at),
        else_=_confirmations.c.confirmed_at,
    )


def _new() -> ColumnElement[bool]:
    """The tab new on `_joined`: green, new, and not seen by the viewer since
    (`domain.inbox.is_unseen`)."""
    new_at, seen_at = _documents.c.new_at, _seen.c.seen_at
    return and_(
        _documents.c.lane == Lane.GREEN.value,
        new_at.is_not(None),
        or_(seen_at.is_(None), seen_at < new_at),
    )


def _conditions(since: datetime) -> dict[InboxTab, ColumnElement[bool]]:
    """Each tab as a condition on `_joined` (`domain.inbox.inbox_state`); done from `since`."""
    lane, new_at, seen_at = _documents.c.lane, _documents.c.new_at, _seen.c.seen_at
    seen_since_new = and_(new_at.is_not(None), seen_at >= new_at, seen_at >= since)
    confirmed = and_(new_at.is_(None), _confirmations.c.confirmed_at >= since)
    return {
        InboxTab.NEW: _new(),
        InboxTab.REVIEW: lane == Lane.YELLOW.value,
        InboxTab.INTERVENE: lane == Lane.RED.value,
        InboxTab.PROCESSING: lane.is_(None),
        InboxTab.DONE: and_(lane == Lane.GREEN.value, or_(seen_since_new, confirmed)),
    }
