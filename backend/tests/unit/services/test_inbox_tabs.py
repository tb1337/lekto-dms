"""The inbox's tabs, summary and seen through the services (Tobi, 17./18.10.2026): what becomes
new, who sees what, how a document leaves the inbox."""

import itertools
from datetime import timedelta

import pytest

from papiq.core.domain.documents import Document, DocumentChanges
from papiq.core.domain.errors import NotFoundError, PermissionDeniedError
from papiq.core.domain.inbox import DONE_PERIOD, Departure, Done, InboxTab
from papiq.core.domain.master_data import Assignment, Contact
from papiq.core.domain.pipeline import Lane, Node
from papiq.core.domain.spaces import ShareLevel
from papiq.core.domain.users import Role, User
from papiq.core.ports.repository import DocumentFilter
from papiq.core.services.inbox import InboxItem
from papiq.core.services.pipeline import MetadataResult, NodeExecutor
from tests.builders import FAILED, NOW, OK, UNCERTAIN, Returns, incoming
from tests.unit.services.rules_support import Classifies
from tests.unit.services.support import World

MINUTE = timedelta(minutes=1)
_numbers = itertools.count()


async def arrive(
    world: World, owner: User, executors: dict[Node, NodeExecutor] | None = None
) -> Document:
    """A document of `owner`, processed with `executors` (each node OK otherwise)."""
    pipeline = world.pipeline(executors)
    content = f"%PDF-1.7 {next(_numbers)}".encode()
    document = await pipeline.receive(owner.id, incoming(content), filename="a.pdf")
    await world.drain(pipeline)
    return await world.documents.get(owner.id, document.id)


async def contact(world: World, name: str) -> Contact:
    admin = await world.user(role=Role.ADMIN)
    return await world.master_data.create_contact(admin.id, name)


def tabs(items: list[InboxItem]) -> list[tuple[str, InboxTab]]:
    return [(item.document.title, item.state.tab) for item in items]


async def test_a_document_green_by_itself_is_new_until_its_owner_sees_it(world: World) -> None:
    owner = await world.user()
    pipeline = world.pipeline()
    received = await pipeline.receive(owner.id, incoming(b"%PDF-1.7 a"), filename="a.pdf")
    (item,) = await world.inbox.items(owner.id)
    assert (item.state.tab, item.open, item.access) == (
        InboxTab.PROCESSING,
        (),
        ShareLevel.READ_WRITE,
    )
    summary = await world.inbox.summary(owner.id)
    assert (summary.counts[InboxTab.PROCESSING], summary.open, summary.worst_lane) == (1, 1, None)

    await world.drain(pipeline)
    (item,) = await world.inbox.items(owner.id)
    assert (item.document.id, item.state.tab, item.document.new_at) == (
        received.id,
        InboxTab.NEW,
        NOW,
    )
    assert (await world.inbox.summary(owner.id)).worst_lane is Lane.GREEN

    world.clock.advance(MINUTE)
    await world.inbox.mark_seen(owner.id, received.id)
    assert await world.inbox.items(owner.id) == []
    (done,) = await world.inbox.items(owner.id, tab=InboxTab.DONE)
    assert done.state.done == Done(Departure.SEEN, NOW + MINUTE, owner.id)
    summary = await world.inbox.summary(owner.id)
    assert (summary.open, summary.counts[InboxTab.DONE], summary.worst_lane) == (0, 1, None)

    await world.inbox.mark_unseen(owner.id, received.id)  # new again
    assert tabs(await world.inbox.items(owner.id)) == [("a", InboxTab.NEW)]


async def test_seen_changes_nothing_but_the_inbox(world: World) -> None:
    owner = await world.user()
    document = await arrive(world, owner)
    world.clock.advance(MINUTE)
    await world.inbox.mark_seen(owner.id, document.id)
    after = await world.documents.get(owner.id, document.id)
    assert after == document  # not confirmed, same lane, same version
    assert world.events()[-1].occurred_at == NOW  # no event


async def test_reading_through_the_api_sets_nothing(world: World) -> None:
    owner = await world.user()
    document = await arrive(world, owner)
    await world.documents.view(owner.id, document.id)
    await world.documents.get(owner.id, document.id)
    assert tabs(await world.inbox.items(owner.id)) == [("a", InboxTab.NEW)]


async def test_reprocessing_makes_it_new_again_only_if_the_metadata_changed(
    world: World,
) -> None:
    owner = await world.user()
    acme = await contact(world, "ACME")
    document = await arrive(world, owner)
    world.clock.advance(MINUTE)
    await world.inbox.mark_seen(owner.id, document.id)

    world.clock.advance(MINUTE)
    unchanged = world.pipeline()
    await unchanged.reprocess_from(owner.id, document.id, Node.JUDGE)
    assert tabs(await world.inbox.items(owner.id)) == [("a", InboxTab.PROCESSING)]
    await world.drain(unchanged)
    assert await world.inbox.items(owner.id) == []  # seen, and nothing changed

    world.clock.advance(MINUTE)
    changed = world.pipeline({Node.JUDGE: Classifies(contact=acme.id)})
    await changed.reprocess_from(owner.id, document.id, Node.JUDGE)
    await world.drain(changed)
    (item,) = await world.inbox.items(owner.id)
    assert (item.state.tab, item.document.contact_id) == (InboxTab.NEW, acme.id)
    assert item.document.new_at == NOW + 3 * MINUTE


@pytest.mark.parametrize("by", [Role.USER, Role.ADMIN])
async def test_a_confirmed_document_is_new_for_no_one(world: World, by: Role) -> None:
    """Confirming out of yellow, by the owner or an admin: it leaves every inbox, new for no
    one, and done tells who confirmed it."""
    owner = await world.user()
    admin = await world.user(role=Role.ADMIN)
    confirming = owner if by is Role.USER else admin
    yellow = await arrive(world, owner, {Node.JUDGE: Returns(UNCERTAIN)})
    (item,) = await world.inbox.items(owner.id, tab=InboxTab.REVIEW)
    assert [open.node for open in item.open] == [Node.JUDGE]
    assert (await world.inbox.summary(owner.id)).worst_lane is Lane.YELLOW

    world.clock.advance(MINUTE)
    pipeline = world.pipeline()
    await pipeline.confirm(confirming.id, yellow.id, DocumentChanges(), accept_suggestions=True)
    await world.drain(pipeline)

    expected = Done(Departure.CONFIRMED, NOW + MINUTE, confirming.id)
    for viewer, all_users in ((owner, False), (admin, True)):
        assert await world.inbox.items(viewer.id, all_users=all_users) == []
        (done,) = await world.inbox.items(viewer.id, tab=InboxTab.DONE, all_users=all_users)
        assert (done.document.lane, done.document.new_at, done.state.done) == (
            Lane.GREEN,
            None,
            expected,
        )


async def test_a_retry_from_red_ending_green_by_itself(world: World) -> None:
    """Red documents stand under intervene; a retry that ends green is new only if it changed
    contact, type, topic, tags, date or fields."""
    owner = await world.user()
    acme = await contact(world, "ACME")
    filing = await arrive(world, owner, {Node.FILE: Returns(FAILED)})
    reading = await arrive(world, owner, {Node.OCR: Returns(FAILED)})
    assert [item.state.tab for item in await world.inbox.items(owner.id)] == [
        InboxTab.INTERVENE,
        InboxTab.INTERVENE,
    ]
    assert (await world.inbox.summary(owner.id)).worst_lane is Lane.RED

    world.clock.advance(MINUTE)
    pipeline = world.pipeline({Node.JUDGE: Classifies(contact=acme.id)})
    for document in (filing, reading):
        await pipeline.retry(owner.id, document.id)
    await world.drain(pipeline)
    (item,) = await world.inbox.items(owner.id)
    assert (item.document.id, item.state.tab) == (reading.id, InboxTab.NEW)
    filed = await world.documents.get(owner.id, filing.id)
    assert (filed.lane, filed.new_at) == (Lane.GREEN, None)


async def test_seen_is_per_user(world: World) -> None:
    """The owner's inbox and an admin's of every user hold the same new document; each sees it
    on their own."""
    owner = await world.user()
    admin = await world.user(role=Role.ADMIN)
    document = await arrive(world, owner)
    world.clock.advance(MINUTE)
    await world.inbox.mark_seen(owner.id, document.id)
    assert await world.inbox.items(owner.id) == []
    (item,) = await world.inbox.items(admin.id, all_users=True)
    assert item.state.tab is InboxTab.NEW
    assert await world.inbox.items(admin.id) == []  # the admin's own inbox

    world.clock.advance(MINUTE)
    await world.inbox.mark_seen(admin.id, document.id)
    (done,) = await world.inbox.items(admin.id, tab=InboxTab.DONE, all_users=True)
    assert done.state.done == Done(Departure.SEEN, NOW + 2 * MINUTE, admin.id)
    await world.inbox.mark_unseen(owner.id, document.id)
    assert tabs(await world.inbox.items(owner.id)) == [("a", InboxTab.NEW)]
    assert await world.inbox.items(admin.id, all_users=True) == []


async def test_a_share_never_brings_a_document_into_an_inbox(world: World) -> None:
    owner, reader = await world.user(), await world.user()
    shared = await world.spaces.create(owner.id, "Shared")
    await world.spaces.share(owner.id, shared.id, reader.id, ShareLevel.READ_WRITE)
    pipeline = world.pipeline()
    received = await pipeline.receive(
        owner.id, incoming(b"%PDF-1.7 s"), filename="s.pdf", space=shared.id
    )
    await world.drain(pipeline)
    assert await world.documents.get(reader.id, received.id)
    await world.inbox.mark_seen(reader.id, received.id)  # nothing to see for them
    async with world.uow() as uow:
        assert await uow.inbox.seen(reader.id, [received.id]) == {}
    assert await world.inbox.items(reader.id) == []
    assert (await world.inbox.summary(reader.id)).open == 0
    assert tabs(await world.inbox.items(owner.id)) == [("s", InboxTab.NEW)]


async def test_seeing_it_again_keeps_when_it_left(world: World) -> None:
    """The web UI reports seen on every open: once seen since it became new, the time stays."""
    owner = await world.user()
    document = await arrive(world, owner)
    world.clock.advance(MINUTE)
    await world.inbox.mark_seen(owner.id, document.id)
    world.clock.advance(MINUTE)
    await world.inbox.mark_seen(owner.id, document.id)
    (done,) = await world.inbox.items(owner.id, tab=InboxTab.DONE)
    assert done.state.done == Done(Departure.SEEN, NOW + MINUTE, owner.id)
    world.clock.advance(DONE_PERIOD - 2 * MINUTE)
    await world.inbox.mark_seen(owner.id, document.id)
    world.clock.advance(2 * MINUTE)
    assert await world.inbox.items(owner.id, tab=InboxTab.DONE) == []  # gone after its 14 days


async def test_metadata_a_person_sets_during_the_run_is_their_decision(world: World) -> None:
    """Set by its owner while processing runs, taken over from the source system, or tags set
    by hand alone: the run ends green, and the document is not new."""
    owner = await world.user()
    admin = await world.user(role=Role.ADMIN)
    acme = await world.master_data.create_contact(admin.id, "ACME")
    paid = await world.master_data.create_tag(admin.id, "Paid", assignment=Assignment.MANUAL)
    pipeline = world.pipeline()
    by_hand = []
    for number, change in enumerate(
        (DocumentChanges(contact_id=acme.id), DocumentChanges(tag_ids=frozenset({paid.id})))
    ):
        content = f"%PDF-1.7 by hand {number}".encode()
        received = await pipeline.receive(owner.id, incoming(content), filename="h.pdf")
        await world.documents.change_metadata(owner.id, received.id, change)
        by_hand.append(received.id)
    imported = MetadataResult(OK, DocumentChanges(contact_id=acme.id), confirms=True)
    taken_over = await arrive(world, owner, {Node.JUDGE: Returns(imported)})
    await world.drain(pipeline)
    for id in (*by_hand, taken_over.id):
        document = await world.documents.get(owner.id, id)
        assert (document.lane, document.new_at) == (Lane.GREEN, None)
    assert await world.inbox.items(owner.id) == []


async def test_a_deleted_users_seen_marks_go(world: World) -> None:
    owner = await world.user()
    admin, other = await world.user(role=Role.ADMIN), await world.user(role=Role.ADMIN)
    document = await arrive(world, owner)
    await world.inbox.mark_seen(admin.id, document.id)
    await world.inbox.mark_seen(owner.id, document.id)
    await world.users.delete_user(other.id, admin.id)
    assert list(world.database.seen) == [(owner.id, document.id)]


async def test_seen_needs_read_access_and_counts_for_new_documents_only(world: World) -> None:
    owner, stranger = await world.user(), await world.user()
    yellow = await arrive(world, owner, {Node.JUDGE: Returns(UNCERTAIN)})
    for mark in (world.inbox.mark_seen, world.inbox.mark_unseen):
        with pytest.raises(NotFoundError):
            await mark(stranger.id, yellow.id)
    await world.inbox.mark_seen(owner.id, yellow.id)  # new for no one: nothing to see
    async with world.uow() as uow:
        assert await uow.inbox.seen(owner.id, [yellow.id]) == {}


async def test_done_lasts_fourteen_days(world: World) -> None:
    owner = await world.user()
    document = await arrive(world, owner)
    await world.inbox.mark_seen(owner.id, document.id)
    world.clock.advance(DONE_PERIOD)
    assert len(await world.inbox.items(owner.id, tab=InboxTab.DONE)) == 1
    world.clock.advance(MINUTE)
    assert await world.inbox.items(owner.id, tab=InboxTab.DONE) == []
    assert await world.inbox.items(owner.id) == []  # and it stays seen


async def test_all_as_seen_marks_what_is_new(world: World) -> None:
    owner, other = await world.user(), await world.user()
    admin = await world.user(role=Role.ADMIN)
    first, second = await arrive(world, owner), await arrive(world, owner)
    await arrive(world, owner, {Node.JUDGE: Returns(UNCERTAIN)})
    theirs = await arrive(world, other)
    world.clock.advance(MINUTE)
    assert await world.inbox.mark_all_seen(owner.id) == 2
    assert [item.state.tab for item in await world.inbox.items(owner.id)] == [InboxTab.REVIEW]
    done = await world.inbox.items(owner.id, tab=InboxTab.DONE)
    assert [item.document.id for item in done] == [second.id, first.id]
    assert await world.inbox.mark_all_seen(admin.id, all_users=True) == 3
    assert [item.document.id for item in await world.inbox.items(other.id)] == [theirs.id]


async def test_every_users_inbox_is_for_admins(world: World) -> None:
    user = await world.user()
    with pytest.raises(PermissionDeniedError, match="only admins"):
        await world.inbox.items(user.id, all_users=True)
    with pytest.raises(PermissionDeniedError, match="only admins"):
        await world.inbox.summary(user.id, all_users=True)
    with pytest.raises(PermissionDeniedError, match="only admins"):
        await world.inbox.mark_all_seen(user.id, all_users=True)


async def test_pages_of_the_inbox(world: World) -> None:
    owner = await world.user()
    documents = [await arrive(world, owner) for _ in range(3)]
    first = await world.inbox.items(owner.id, limit=2)
    rest = await world.inbox.items(owner.id, after=first[-1].document.id, limit=2)
    assert [item.document.id for item in [*first, *rest]] == [
        document.id for document in reversed(documents)
    ]


async def test_lists_say_whether_a_document_stands_in_the_callers_inbox(world: World) -> None:
    """In processing, yellow, red, or new and unseen: in the owner's inbox, and in an admin's
    of every user; never in the inbox of someone it is shared with."""
    owner, reader = await world.user(), await world.user()
    admin = await world.user(role=Role.ADMIN)
    shared = await world.spaces.create(owner.id, "Shared")
    await world.spaces.share(owner.id, shared.id, reader.id, ShareLevel.READ)
    seen, new = await arrive(world, owner), await arrive(world, owner)
    yellow = await arrive(world, owner, {Node.JUDGE: Returns(UNCERTAIN)})
    await world.documents.move(owner.id, new.id, shared.id)
    await world.inbox.mark_seen(owner.id, seen.id)
    processing = await world.pipeline().receive(owner.id, incoming(b"%PDF-1.7 p"), filename="p.pdf")

    async def listed(user: User, *, all_users: bool = False) -> dict[str, bool]:
        names = {seen.id: "seen", new.id: "new", yellow.id: "yellow", processing.id: "processing"}
        views = await world.documents.query(user.id, DocumentFilter(), all_users=all_users)
        return {names[view.document.id]: view.in_inbox for view in views}

    assert await listed(owner) == {
        "processing": True,
        "yellow": True,
        "new": True,
        "seen": False,
    }
    assert await listed(reader) == {"new": False}
    assert await listed(admin) == {}
    assert await listed(admin, all_users=True) == {
        "processing": True,
        "yellow": True,
        "new": True,
        "seen": True,  # the owner's seen is not the admin's
    }
