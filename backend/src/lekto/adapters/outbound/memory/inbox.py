"""The in-memory inbox: the seen marks and confirmations beside the documents of the unit of
work, and the inbox's queries by `domain.inbox.inbox_state` (the rule the SQL adapter has in
its query language). Marks are written as the SQL adapter's upserts are: the last write wins,
no version is checked."""

from collections.abc import Collection, Iterator
from datetime import datetime
from typing import TYPE_CHECKING

from lekto.adapters.outbound.memory.database import DOCUMENTS, SPACES, USERS, SeenMark
from lekto.adapters.outbound.memory.rows import _copy
from lekto.core.domain.documents import Document
from lekto.core.domain.errors import ConflictError
from lekto.core.domain.ids import DocumentId, UserId
from lekto.core.domain.inbox import Confirmation, InboxState, InboxTab, inbox_state, open_tab
from lekto.core.domain.spaces import SpaceRole
from lekto.core.domain.validation import require_utc
from lekto.core.ports.repository import InboxEntry, InboxPosition

if TYPE_CHECKING:
    from lekto.adapters.outbound.memory.unit_of_work import MemoryUnitOfWork

type SeenKey = tuple[UserId, DocumentId]


class MemoryInboxRepository:
    def __init__(self, uow: "MemoryUnitOfWork") -> None:
        self._uow = uow

    async def query(
        self,
        viewer: UserId,
        *,
        editor: UserId | None,
        tab: InboxTab | None,
        since: datetime,
        after: InboxPosition | None = None,
        limit: int,
    ) -> list[InboxEntry]:
        found = [
            (document, state, mark, confirmation)
            for document, state, mark, confirmation in self._states(viewer, editor, since)
            if (state.tab is not InboxTab.DONE if tab is None else state.tab is tab)
        ]
        if tab is InboxTab.DONE:  # by when they left, newest first, ties by id
            found.sort(key=lambda item: (_left(item[1]), item[0].id), reverse=True)
        entries: list[InboxEntry] = []
        for document, state, mark, confirmation in found:
            if after is not None and not _before(document, state, after, tab):
                continue
            entries.append(_entry(document, mark, confirmation))
            if len(entries) == limit:
                break
        return entries

    async def entry(self, viewer: UserId, document: DocumentId) -> InboxEntry | None:
        row = self._uow._row(DOCUMENTS, document)
        if row is None:
            return None
        return _entry(
            row, self._marks().get((viewer, document)), self._confirmations().get(document)
        )

    async def count(
        self, viewer: UserId, *, editor: UserId | None, since: datetime
    ) -> dict[InboxTab, int]:
        counts = dict.fromkeys(InboxTab, 0)
        for _, state, _, _ in self._states(viewer, editor, since):
            counts[state.tab] += 1
        return counts

    async def seen(
        self, viewer: UserId, documents: Collection[DocumentId]
    ) -> dict[DocumentId, datetime]:
        wanted = set(documents)
        return {
            document: mark.at
            for (user, document), mark in self._marks().items()
            if user == viewer and document in wanted and self._exists(document)
        }

    async def mark_seen(
        self, viewer: UserId, document: DocumentId, at: datetime, *, silent: bool = False
    ) -> None:
        self._marks()  # the unit is open
        self._refer(document)
        if self._uow._row(USERS, viewer) is None:
            raise ConflictError(f"seen mark of a user that does not exist: {viewer}")
        self._uow._seen[(viewer, document)] = SeenMark(require_utc(at, "seen_at"), silent)

    async def mark_all_seen(self, viewer: UserId, *, editor: UserId | None, at: datetime) -> int:
        marks = self._marks()
        new = [
            document.id
            for document in self._documents(editor)
            if open_tab(document, _at(marks.get((viewer, document.id)))) is InboxTab.NEW
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
        for key, mark in self._marks().items():
            row = self._uow._row(DOCUMENTS, key[1])
            at = mark.at
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
        self, viewer: UserId, editor: UserId | None, since: datetime
    ) -> Iterator[tuple[Document, InboxState, SeenMark | None, Confirmation | None]]:
        """The documents of `editor` that stand in `viewer`'s inbox, newest first, with where."""
        marks, confirmations = self._marks(), self._confirmations()
        for document in sorted(self._documents(editor), key=lambda row: row.id, reverse=True):
            mark = marks.get((viewer, document.id))
            confirmation = confirmations.get(document.id)
            state = inbox_state(
                document,
                viewer=viewer,
                seen_at=_at(mark),
                confirmation=confirmation,
                since=since,
                silent=mark is not None and mark.silent,
            )
            if state is not None:
                yield document, state, mark, confirmation

    def _documents(self, editor: UserId | None) -> list[Document]:
        """The documents in the spaces `editor` edits (None: every one), as the unit sees them
        (not copied)."""
        rows = self._uow._rows(DOCUMENTS)
        if editor is None:
            return rows
        edited = {
            space.id for space in self._uow._rows(SPACES) if space.role_of(editor) is SpaceRole.EDIT
        }
        return [row for row in rows if row.space_id in edited]

    def _exists(self, document: DocumentId) -> bool:
        return self._uow._row(DOCUMENTS, document) is not None

    def _refer(self, document: DocumentId) -> None:
        """ConflictError for a mark of a document that does not exist, as the SQL schema's
        foreign key refuses it."""
        if not self._exists(document):
            raise ConflictError(f"inbox mark of a document that does not exist: {document}")

    def _marks(self) -> dict[SeenKey, SeenMark]:
        """The seen marks committed, with this unit's changes."""
        self._uow._check_open()
        marks = dict(self._uow._db.seen)
        for key, mark in self._uow._seen.items():
            if mark is None:
                marks.pop(key, None)
            else:
                marks[key] = mark
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


def _at(mark: SeenMark | None) -> datetime | None:
    return None if mark is None else mark.at


def _entry(
    document: Document, mark: SeenMark | None, confirmation: Confirmation | None
) -> InboxEntry:
    return InboxEntry(_copy(document), _at(mark), confirmation, mark is not None and mark.silent)


def _left(state: InboxState) -> datetime:
    assert state.done is not None  # under done
    return state.done.at


def _before(
    document: Document, state: InboxState, after: InboxPosition, tab: InboxTab | None
) -> bool:
    """Whether the document comes after `after` in the order of `tab`."""
    if tab is not InboxTab.DONE:
        return document.id < after.id
    assert after.left_at is not None, "a position under done names when its document left"
    return (_left(state), document.id) < (after.left_at, after.id)
