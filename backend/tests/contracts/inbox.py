"""Contract of the inbox repository (`InboxRepository`): seen marks per user, confirmations, the
tabs of an inbox, and the cleanup. The rule itself is `domain.inbox.inbox_state`; the suite
checks that an adapter selects by it."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

import pytest

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import ConflictError
from lekto.core.domain.ids import DocumentId, UserId, new_id
from lekto.core.domain.inbox import DONE_PERIOD, Confirmation, InboxTab, left_at
from lekto.core.domain.pipeline import Node
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import User
from lekto.core.ports.repository import InboxPosition
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from tests import builders
from tests.builders import FAILED, NOW, UNCERTAIN
from tests.contracts.unit_of_work import owner_with_space

LATER = NOW + timedelta(hours=1)
LAST = NOW + timedelta(hours=2)
SINCE = LAST - DONE_PERIOD
LONG_AGO = SINCE - timedelta(days=1)


async def store(uow_factory: UnitOfWorkFactory, *documents: Document) -> None:
    async with uow_factory() as uow:
        for document in documents:
            await uow.documents.add(document)
        await uow.commit()


def green(owner: User, space: Space, *, new: bool = True) -> Document:
    """Green from its first run, new since `NOW` unless not `new`."""
    document = builders.processed(owner, space)
    assert document.new_at == NOW
    if not new:
        document.new_at = None
    return document


@dataclass
class Inbox:
    """An owner's documents in every state, oldest first; another owner's new one."""

    owner: User
    other: User
    documents: dict[str, Document]

    def ids(self, *names: str) -> list[DocumentId]:
        """The ids of the documents `names`, newest first as the inbox lists them."""
        return sorted((self.documents[name].id for name in names), reverse=True)


async def inbox(uow_factory: UnitOfWorkFactory) -> Inbox:
    owner, space = await owner_with_space(uow_factory)
    other, others = await owner_with_space(uow_factory)
    documents = {
        "processing": builders.document(owner, space),
        "yellow": builders.processed(owner, space, {Node.JUDGE: UNCERTAIN}),
        "red": builders.processed(owner, space, {Node.OCR: FAILED}),
        "new": green(owner, space),
        "seen": green(owner, space),
        "seen_long_ago": green(owner, space),
        "new_again": green(owner, space),
        "confirmed": green(owner, space, new=False),
        "confirmed_long_ago": green(owner, space, new=False),
        "filed": green(owner, space, new=False),
        "other": green(other, others),
    }
    documents["seen_long_ago"].new_at = LONG_AGO - timedelta(days=1)
    documents["new_again"].new_at = LATER
    await store(uow_factory, *documents.values())
    async with uow_factory() as uow:
        await uow.inbox.mark_seen(owner.id, documents["seen"].id, LATER)
        await uow.inbox.mark_seen(owner.id, documents["seen_long_ago"].id, LONG_AGO)
        await uow.inbox.mark_seen(owner.id, documents["new_again"].id, NOW)
        await uow.inbox.record_confirmation(
            documents["confirmed"].id, Confirmation(other.id, LATER)
        )
        await uow.inbox.record_confirmation(
            documents["confirmed_long_ago"].id, Confirmation(owner.id, LONG_AGO)
        )
        await uow.commit()
    return Inbox(owner, other, documents)


class InboxRepositoryContract:
    async def test_the_inbox_holds_the_spaces_a_user_edits(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        editor = await builders.seed_user(uow_factory)
        reader = await builders.seed_user(uow_factory)
        other = await builders.seed_user(uow_factory)
        shared = builders.space(editor, readers=[reader], editors=[other])
        async with uow_factory() as uow:
            await uow.spaces.add(shared)
            await uow.commit()
        yellow = builders.processed(editor, shared, {Node.JUDGE: UNCERTAIN})
        new = green(reader, shared)
        await store(uow_factory, yellow, new)
        async with uow_factory() as uow:
            for user in (editor, other):
                found = await uow.inbox.query(
                    user.id, editor=user.id, tab=None, since=SINCE, limit=9
                )
                assert {entry.document.id for entry in found} == {yellow.id, new.id}
            mine = await uow.inbox.query(
                reader.id, editor=reader.id, tab=None, since=SINCE, limit=9
            )
            assert mine == []
            counts = await uow.inbox.count(reader.id, editor=reader.id, since=SINCE)
            assert sum(counts.values()) == 0

    async def test_seen_marks_are_per_user(self, uow_factory: UnitOfWorkFactory) -> None:
        owner, space = await owner_with_space(uow_factory)
        admin = await builders.seed_user(uow_factory)
        document = green(owner, space)
        await store(uow_factory, document)
        async with uow_factory() as uow:
            await uow.inbox.mark_seen(owner.id, document.id, NOW)
            assert await uow.inbox.seen(owner.id, [document.id]) == {document.id: NOW}
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.inbox.seen(owner.id, [document.id]) == {document.id: NOW}
            assert await uow.inbox.seen(admin.id, [document.id]) == {}
            await uow.inbox.mark_seen(owner.id, document.id, LATER)  # replaces
            await uow.inbox.mark_seen(admin.id, document.id, LAST)
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.inbox.seen(owner.id, [document.id]) == {document.id: LATER}
            assert await uow.inbox.seen(admin.id, [document.id, DocumentId(new_id())]) == {
                document.id: LAST
            }
            await uow.inbox.unmark_seen(owner.id, document.id)
            await uow.inbox.unmark_seen(owner.id, document.id)  # never mind
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.inbox.seen(owner.id, [document.id]) == {}
            assert await uow.inbox.seen(admin.id, [document.id]) == {document.id: LAST}
            assert await uow.inbox.seen(admin.id, []) == {}

    async def test_marks_are_stored_on_commit_only(self, uow_factory: UnitOfWorkFactory) -> None:
        owner, space = await owner_with_space(uow_factory)
        document = green(owner, space)
        await store(uow_factory, document)
        async with uow_factory() as uow:
            await uow.inbox.mark_seen(owner.id, document.id, NOW)
            await uow.inbox.record_confirmation(document.id, Confirmation(owner.id, NOW))
            await uow.rollback()
        async with uow_factory() as uow:
            assert await uow.inbox.seen(owner.id, [document.id]) == {}
            (entry,) = await uow.inbox.query(
                owner.id, editor=owner.id, tab=InboxTab.NEW, since=SINCE, limit=5
            )
            assert entry.confirmation is None

    async def test_the_tabs_of_an_owners_inbox(self, uow_factory: UnitOfWorkFactory) -> None:
        scene = await inbox(uow_factory)
        owner = scene.owner.id
        expected = {
            InboxTab.NEW: scene.ids("new", "new_again"),
            InboxTab.REVIEW: scene.ids("yellow"),
            InboxTab.INTERVENE: scene.ids("red"),
            InboxTab.PROCESSING: scene.ids("processing"),
            InboxTab.DONE: scene.ids("seen", "confirmed"),
        }
        async with uow_factory() as uow:
            for tab, ids in expected.items():
                entries = await uow.inbox.query(owner, editor=owner, tab=tab, since=SINCE, limit=50)
                assert [entry.document.id for entry in entries] == ids, tab
            every = await uow.inbox.query(owner, editor=owner, tab=None, since=SINCE, limit=50)
            assert [entry.document.id for entry in every] == scene.ids(
                "processing", "yellow", "red", "new", "new_again"
            )
            counts = await uow.inbox.count(owner, editor=owner, since=SINCE)
        assert counts == {tab: len(ids) for tab, ids in expected.items()}

    async def test_entries_carry_what_the_state_is_decided_by(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        scene = await inbox(uow_factory)
        owner = scene.owner.id
        async with uow_factory() as uow:
            done = await uow.inbox.query(
                owner, editor=owner, tab=InboxTab.DONE, since=SINCE, limit=9
            )
            again = await uow.inbox.query(
                owner, editor=owner, tab=InboxTab.NEW, since=SINCE, limit=9
            )
        by_id = {entry.document.id: entry for entry in [*done, *again]}
        seen = by_id[scene.documents["seen"].id]
        assert (seen.seen_at, seen.confirmation) == (LATER, None)
        assert seen.document == scene.documents["seen"]
        confirmed = by_id[scene.documents["confirmed"].id]
        assert (confirmed.seen_at, confirmed.confirmation) == (
            None,
            Confirmation(scene.other.id, LATER),
        )
        assert by_id[scene.documents["new_again"].id].seen_at == NOW

    async def test_a_silent_mark_keeps_a_document_from_being_new_but_not_done(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        """A move marks it for who knew it (Tobi, 22.10.2026): not new, not done either, until
        they see it."""
        owner, space = await owner_with_space(uow_factory)
        moved = green(owner, space)
        await store(uow_factory, moved)
        async with uow_factory() as uow:
            await uow.inbox.mark_seen(owner.id, moved.id, LATER, silent=True)
            await uow.commit()
        async with uow_factory() as uow:
            counts = await uow.inbox.count(owner.id, editor=owner.id, since=SINCE)
            assert (counts[InboxTab.NEW], counts[InboxTab.DONE]) == (0, 0)
            entry = await uow.inbox.entry(owner.id, moved.id)
            assert entry is not None and (entry.seen_at, entry.silent) == (LATER, True)
            assert await uow.inbox.seen(owner.id, [moved.id]) == {moved.id: LATER}
            await uow.inbox.mark_seen(owner.id, moved.id, LAST)  # now they look at it
            await uow.commit()
        async with uow_factory() as uow:
            done = await uow.inbox.query(
                owner.id, editor=owner.id, tab=InboxTab.DONE, since=SINCE, limit=9
            )
            assert [(item.document.id, item.seen_at, item.silent) for item in done] == [
                (moved.id, LAST, False)
            ]

    async def test_admins_see_every_users_inbox_with_their_own_seen(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        scene = await inbox(uow_factory)
        admin = await builders.seed_user(uow_factory)
        async with uow_factory() as uow:
            new = await uow.inbox.query(
                admin.id, editor=None, tab=InboxTab.NEW, since=SINCE, limit=50
            )
            assert [entry.document.id for entry in new] == scene.ids(
                "new", "seen", "seen_long_ago", "new_again", "other"
            )
            done = await uow.inbox.query(
                admin.id, editor=None, tab=InboxTab.DONE, since=SINCE, limit=50
            )
            assert [entry.document.id for entry in done] == scene.ids("confirmed")
            counts = await uow.inbox.count(admin.id, editor=None, since=SINCE)
            assert counts[InboxTab.NEW] == 5
            # Another user's inbox is theirs: nothing of the owner's.
            theirs = await uow.inbox.count(scene.other.id, editor=scene.other.id, since=SINCE)
        assert theirs == {**dict.fromkeys(InboxTab, 0), InboxTab.NEW: 1}

    async def test_pages_newest_first(self, uow_factory: UnitOfWorkFactory) -> None:
        scene = await inbox(uow_factory)
        owner = scene.owner.id
        open = scene.ids("processing", "yellow", "red", "new", "new_again")
        found: list[DocumentId] = []
        after = None
        async with uow_factory() as uow:
            while True:
                page = await uow.inbox.query(
                    owner, editor=owner, tab=None, since=SINCE, after=after, limit=2
                )
                found += [entry.document.id for entry in page]
                if len(page) < 2:
                    break
                after = InboxPosition(page[-1].document.id)
        assert found == open

    async def test_done_goes_by_when_documents_left(self, uow_factory: UnitOfWorkFactory) -> None:
        """Newest first by when they left (`left_at`), ties by id, whenever they arrived; the
        pages after a position (when its document left, and its id) stay stable."""
        owner, space = await owner_with_space(uow_factory)
        first, confirmed, third, fourth = (green(owner, space) for _ in range(4))
        confirmed.new_at = None
        await store(uow_factory, first, confirmed, third, fourth)
        async with uow_factory() as uow:
            await uow.inbox.mark_seen(owner.id, first.id, LAST)
            await uow.inbox.record_confirmation(confirmed.id, Confirmation(owner.id, NOW))
            await uow.inbox.mark_seen(owner.id, third.id, LATER)
            await uow.inbox.mark_seen(owner.id, fourth.id, LATER)
            await uow.commit()
        expected = [first.id, *sorted((third.id, fourth.id), reverse=True), confirmed.id]
        async with uow_factory() as uow:
            done = await uow.inbox.query(
                owner.id, editor=owner.id, tab=InboxTab.DONE, since=SINCE, limit=9
            )
            assert [entry.document.id for entry in done] == expected
            found: list[DocumentId] = []
            after = None
            while page := await uow.inbox.query(
                owner.id, editor=owner.id, tab=InboxTab.DONE, since=SINCE, after=after, limit=1
            ):
                (entry,) = page
                found.append(entry.document.id)
                left = left_at(entry.document, entry.seen_at, entry.confirmation)
                after = InboxPosition(entry.document.id, left)
        assert found == expected

    async def test_an_entry_of_one_document(self, uow_factory: UnitOfWorkFactory) -> None:
        scene = await inbox(uow_factory)
        admin = await builders.seed_user(uow_factory)
        seen, confirmed = scene.documents["seen"], scene.documents["confirmed"]
        async with uow_factory() as uow:
            entry = await uow.inbox.entry(scene.owner.id, seen.id)
            assert entry is not None
            assert (entry.document, entry.seen_at, entry.confirmation) == (seen, LATER, None)
            other = await uow.inbox.entry(admin.id, confirmed.id)  # whoever owns it
            assert other is not None
            assert (other.seen_at, other.confirmation) == (
                None,
                Confirmation(scene.other.id, LATER),
            )
            assert await uow.inbox.entry(scene.owner.id, DocumentId(new_id())) is None

    async def test_all_as_seen_marks_what_is_new_in_the_inbox(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        scene = await inbox(uow_factory)
        owner = scene.owner.id
        admin = await builders.seed_user(uow_factory)
        async with uow_factory() as uow:
            assert await uow.inbox.mark_all_seen(owner, editor=owner, at=LAST) == 2
            await uow.commit()
        async with uow_factory() as uow:
            counts = await uow.inbox.count(owner, editor=owner, since=SINCE)
            assert counts[InboxTab.NEW] == 0
            assert counts[InboxTab.DONE] == 4  # with new and new again
            seen = await uow.inbox.seen(
                owner, [document.id for document in scene.documents.values()]
            )
            assert seen[scene.documents["new_again"].id] == LAST
            assert seen[scene.documents["seen_long_ago"].id] == LONG_AGO  # not new: as it was
            assert scene.documents["other"].id not in seen
            assert await uow.inbox.mark_all_seen(owner, editor=owner, at=LAST) == 0
            # An admin's for every user marks for the admin only.
            assert await uow.inbox.mark_all_seen(admin.id, editor=None, at=LAST) == 5
            await uow.commit()
        async with uow_factory() as uow:
            other = scene.other.id
            assert (await uow.inbox.count(other, editor=other, since=SINCE))[InboxTab.NEW] == 1

    async def test_the_cleanup_removes_what_only_done_needs(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        scene = await inbox(uow_factory)
        owner, documents = scene.owner.id, scene.documents
        ids = [document.id for document in documents.values()]
        async with uow_factory() as uow:
            # Seen before it became new again, and the old confirmation: done with them.
            assert await uow.inbox.purge(before=LATER) == 2
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.inbox.seen(owner, ids) == {
                documents["seen"].id: LATER,
                documents["seen_long_ago"].id: LONG_AGO,  # still tells it is not new
            }
            confirmed = await uow.inbox.query(
                owner, editor=owner, tab=InboxTab.DONE, since=LONG_AGO, limit=9
            )
            # By when they left: seen and confirmed at LATER (ties by id), then long ago.
            assert [entry.document.id for entry in confirmed] == [
                *scene.ids("seen", "confirmed"),
                documents["seen_long_ago"].id,
            ]
            assert await uow.inbox.purge(before=LATER) == 0

    async def test_marks_go_with_their_document_and_user(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        scene = await inbox(uow_factory)
        owner, documents = scene.owner.id, scene.documents
        async with uow_factory() as uow:
            await uow.documents.remove(documents["seen"].id)
            await uow.documents.remove(documents["confirmed"].id)
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.inbox.seen(owner, [documents["seen"].id]) == {}
            assert (await uow.inbox.count(owner, editor=owner, since=SINCE))[InboxTab.DONE] == 0
            await uow.inbox.record_confirmation(
                documents["filed"].id, Confirmation(scene.other.id, LATER)
            )
            assert await uow.inbox.remove_for_user(owner) == 2
            await uow.commit()
        async with uow_factory() as uow:
            ids = [document.id for document in documents.values()]
            assert await uow.inbox.seen(owner, ids) == {}
            # A confirmation stays with its document, whoever it names.
            done = await uow.inbox.query(
                owner, editor=owner, tab=InboxTab.DONE, since=SINCE, limit=9
            )
            assert [entry.document.id for entry in done] == scene.ids("filed")

    async def test_marks_refer_to_a_document_and_a_user(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner, space = await owner_with_space(uow_factory)
        document = green(owner, space)
        await store(uow_factory, document)
        missing = DocumentId(new_id())
        marks: list[Callable[[UnitOfWork], Awaitable[None]]] = [
            lambda uow: uow.inbox.mark_seen(owner.id, missing, NOW),
            lambda uow: uow.inbox.mark_seen(UserId(new_id()), document.id, NOW),
            lambda uow: uow.inbox.record_confirmation(missing, Confirmation(owner.id, NOW)),
        ]
        for mark in marks:
            with pytest.raises(ConflictError):
                async with uow_factory() as uow:
                    await mark(uow)
                    await uow.commit()

    @pytest.mark.parametrize("tab", [None, *InboxTab])
    async def test_an_empty_inbox(self, uow_factory: UnitOfWorkFactory, tab: InboxTab) -> None:
        owner, _ = await owner_with_space(uow_factory)
        async with uow_factory() as uow:
            assert (
                await uow.inbox.query(owner.id, editor=owner.id, tab=tab, since=SINCE, limit=5)
                == []
            )
            assert await uow.inbox.count(owner.id, editor=owner.id, since=SINCE) == dict.fromkeys(
                InboxTab, 0
            )
            assert await uow.inbox.mark_all_seen(owner.id, editor=owner.id, at=NOW) == 0
