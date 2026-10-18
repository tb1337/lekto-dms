"""The in-memory inbox: the seen marks and confirmations beside the documents of the unit of
work, and the inbox's queries by `domain.inbox.inbox_state` (the rule the SQL adapter has in
its query language). Marks are written as the SQL adapter's upserts are: the last write wins,
no version is checked."""

from collections.abc import Collection, Iterator
from datetime import datetime
from typing import TYPE_CHECKING

from papiq.adapters.outbound.memory.database import DOCUMENTS, USERS
from papiq.adapters.outbound.memory.rows import _copy
from papiq.core.domain.documents import Document
from papiq.core.domain.errors import ConflictError
from papiq.core.domain.ids import DocumentId, UserId
from papiq.core.domain.inbox import Confirmation, InboxState, InboxTab, inbox_state, open_tab
from papiq.core.domain.validation import require_utc
from papiq.core.ports.repository import InboxEntry

if TYPE_CHECKING:
    from papiq.adapters.outbound.memory.unit_of_work import MemoryUnitOfWork

type SeenKey = tuple[UserId, DocumentId]


class MemoryInboxRepository:
    def __init__(self, uow: "MemoryUnitOfWork") -> None:
        self._uow = uow

    async def query(
        self,
        viewer: UserId,
        *,
        owner: UserId | None,
        tab: InboxTab | None,
        since: datetime,
        after: DocumentId | None = None,
        limit: int,
    ) -> list[InboxEntry]:
        entries: list[InboxEntry] = []
        for document, state, seen_at, confirmation in self._states(viewer, owner, since):
            wanted = state.tab is not InboxTab.DONE if tab is None else state.tab is tab
            if not wanted or (after is not None and document.id >= after):
                continue
            entries.append(InboxEntry(_copy(document), seen_at, confirmation))
            if len(entries) == limit:
                break
        return entries

    async def count(
        self, viewer: UserId, *, owner: UserId | None, since: datetime
    ) -> dict[InboxTab, int]:
        counts = dict.fromkeys(InboxTab, 0)
        for _, state, _, _ in self._states(viewer, owner, since):
            counts[state.tab] += 1
        return counts

    async def seen(
        self, viewer: UserId, documents: Collection[DocumentId]
    ) -> dict[DocumentId, datetime]:
        wanted = set(documents)
        return {
            document: at
            for (user, document), at in self._marks().items()
            if user == viewer and document in wanted and self._exists(document)
        }

    async def mark_seen(self, viewer: UserId, document: DocumentId, at: datetime) -> None:
        self._marks()  # the unit is open
        self._refer(document)
        if self._uow._row(USERS, viewer) is None:
            raise ConflictError(f"seen mark of a user that does not exist: {viewer}")
        self._uow._seen[(viewer, document)] = require_utc(at, "seen_at")

    async def mark_all_seen(self, viewer: UserId, *, owner: UserId | None, at: datetime) -> int:
        marks = self._marks()
        new = [
            document.id
            for document in self._documents(owner)
            if open_tab(document, marks.get((viewer, document.id))) is InboxTab.NEW
        ]
        for document in new:
            await self.mark_seen(viewer, document, at)
        return len(new)

    async def unmark_seen(self, viewer: UserId, document: DocumentId) -> None:
        self._marks()
        self._uow._seen[(viewer, document)] = None

    async def record_confirmation(self, document: DocumentId, confirmation: Confirmation) -> None:
        self._confirmations()
        self._refer(document)
        require_utc(confirmation.at, "confirmed_at")
        self._uow._confirmations[document] = confirmation

    async def purge(self, *, before: datetime) -> int:
        removed = 0
        for document, confirmation in self._confirmations().items():
            if confirmation.at < before:
                self._uow._confirmations[document] = None
                removed += 1
        for key, at in self._marks().items():
            row = self._uow._row(DOCUMENTS, key[1])
            if at < before and (row is None or row.new_at is None or row.new_at > at):
                self._uow._seen[key] = None
                removed += 1
        return removed

    async def remove_for_user(self, user: UserId) -> int:
        keys = [key for key in self._marks() if key[0] == user]
        for key in keys:
            self._uow._seen[key] = None
        return len(keys)

    def _states(
        self, viewer: UserId, owner: UserId | None, since: datetime
    ) -> Iterator[tuple[Document, InboxState, datetime | None, Confirmation | None]]:
        """The documents of `owner` that stand in `viewer`'s inbox, newest first, with where."""
        marks, confirmations = self._marks(), self._confirmations()
        for document in sorted(self._documents(owner), key=lambda row: row.id, reverse=True):
            seen_at = marks.get((viewer, document.id))
            confirmation = confirmations.get(document.id)
            state = inbox_state(
                document, viewer=viewer, seen_at=seen_at, confirmation=confirmation, since=since
            )
            if state is not None:
                yield document, state, seen_at, confirmation

    def _documents(self, owner: UserId | None) -> list[Document]:
        """The documents of `owner` (None: every one), as the unit sees them (not copied)."""
        rows = self._uow._rows(DOCUMENTS)
        return [row for row in rows if owner is None or row.owner_id == owner]

    def _exists(self, document: DocumentId) -> bool:
        return self._uow._row(DOCUMENTS, document) is not None

    def _refer(self, document: DocumentId) -> None:
        """ConflictError for a mark of a document that does not exist, as the SQL schema's
        foreign key refuses it."""
        if not self._exists(document):
            raise ConflictError(f"inbox mark of a document that does not exist: {document}")

    def _marks(self) -> dict[SeenKey, datetime]:
        """The seen marks committed, with this unit's changes."""
        self._uow._check_open()
        marks = dict(self._uow._db.seen)
        for key, at in self._uow._seen.items():
            if at is None:
                marks.pop(key, None)
            else:
                marks[key] = at
        return marks

    def _confirmations(self) -> dict[DocumentId, Confirmation]:
        """The confirmations committed, with this unit's changes."""
        self._uow._check_open()
        confirmations = dict(self._uow._db.confirmations)
        for document, confirmation in self._uow._confirmations.items():
            if confirmation is None:
                confirmations.pop(document, None)
            else:
                confirmations[document] = confirmation
        return confirmations
