"""Changing many documents at once: the selection, the job and what it reports."""

from dataclasses import dataclass, field

import pytest

from lekto.core.domain.bulk import MAX_IDS, BulkAction, BulkKind, BulkStatus
from lekto.core.domain.documents import DocumentChanges
from lekto.core.domain.errors import (
    NotFoundError,
    PermissionDeniedError,
    SearchUnavailableError,
    ValidationError,
)
from lekto.core.domain.ids import (
    ContactId,
    DocumentId,
    DocumentTypeId,
    SpaceId,
    TagId,
    UserId,
    new_id,
)
from lekto.core.domain.pipeline import Lane, Node
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.rules import ForceReview
from lekto.core.domain.spaces import SpaceRole
from lekto.core.ports.repository import DocumentFilter
from lekto.core.services import bulk
from lekto.core.services.bulk import BulkService, Selection
from lekto.core.services.search import SearchItem, SearchMode, SearchPage
from tests import builders
from tests.unit.services.rules_support import (
    RuleWorld,
    channel_api,
    definition,
    incoming_pdf,
    rule_world,
)
from tests.unit.services.support import World


@dataclass
class Hits:
    """A search that finds `found`, `page` at a time (the index's pages)."""

    found: list[SearchItem]
    asked: list[tuple[str, int]] = field(default_factory=list)

    async def search(
        self,
        actor: UserId,
        text: str,
        filter: DocumentFilter | None = None,
        *,
        offset: int = 0,
        limit: int = 20,
        all_users: bool = False,
    ) -> SearchPage:
        self.asked.append((text, offset))
        items = self.found[offset : offset + 2]
        following = offset + 2
        return SearchPage(
            items=items,
            estimated_total=len(self.found),
            next_offset=following if following < len(self.found) else None,
            mode=SearchMode.WORDS,
        )


def service(r: RuleWorld, search: object = None) -> BulkService:
    return BulkService(
        r.world.uow,
        r.world.clock,
        r.documents,
        r.pipeline(),
        search,  # type: ignore[arg-type]
    )


def ids(*documents: object) -> Selection:
    return Selection(ids=tuple(document.id for document in documents))  # type: ignore[attr-defined]


async def test_tags_are_added_where_missing_and_the_others_are_skipped_with_why(
    world: World,
) -> None:
    r = await rule_world(world)
    owner, other = await world.user(), await world.user()
    tax = await r.tag("tax")
    readable = await world.spaces.create(other.id, "Readable")
    await world.spaces.set_member(other.id, readable.id, owner.id, SpaceRole.READ)
    first, tagged = await r.arrive(owner), await r.arrive(owner)
    await r.documents.change_metadata(
        owner.id, tagged.id, DocumentChanges(tag_ids=frozenset({tax.id}))
    )
    read_only = await r.arrive(other, space=readable.id)
    busy = await r.pipeline().receive(owner.id, incoming_pdf(), filename="Busy.pdf")
    gone = DocumentId(new_id())
    bulk_service = service(r)

    operation = await bulk_service.start(
        owner.id,
        Selection(ids=(first.id, tagged.id, read_only.id, busy.id, gone)),
        BulkAction(BulkKind.CHANGE_TAGS, add=frozenset({tax.id})),
    )
    assert operation.status is BulkStatus.QUEUED
    assert await builders.drain(bulk_service) == 1

    done = await bulk_service.get(owner.id, operation.id)
    assert (done.status, done.position, done.changed, done.unchanged) == (
        BulkStatus.DONE,
        5,
        1,
        1,
    )
    assert done.skipped == [
        (
            read_only.id,
            because(ReasonCode.NO_WRITE_ACCESS_TO_DOCUMENT, id=str(read_only.id)),
        ),
        (busy.id, because(ReasonCode.BEING_PROCESSED, id=str(busy.id))),
        (gone, because(ReasonCode.SKIP_NOT_AVAILABLE)),
    ]
    assert (await r.stored(first)).tag_ids == {tax.id}
    assert (await r.stored(read_only)).tag_ids == set()


async def test_tags_are_removed_and_contact_type_and_topic_set_or_cleared(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    tax, keep = await r.tag("tax"), await r.tag("keep")
    contact = await r.contact("ACME")
    document = await r.arrive(owner)
    await r.documents.change_metadata(
        owner.id,
        document.id,
        DocumentChanges(tag_ids=frozenset({tax.id, keep.id}), contact_id=contact.id),
    )
    bulk_service = service(r)

    for action in (
        BulkAction(BulkKind.CHANGE_TAGS, add=frozenset({keep.id}), remove=frozenset({tax.id})),
        BulkAction(BulkKind.SET_CONTACT, contact=None),
    ):
        await bulk_service.start(owner.id, ids(document), action)
    await builders.drain(bulk_service)

    stored = await r.stored(document)
    assert (stored.tag_ids, stored.contact_id) == ({keep.id}, None)
    again = await bulk_service.start(
        owner.id, ids(document), BulkAction(BulkKind.SET_DOCUMENT_TYPE, document_type=None)
    )
    await builders.drain(bulk_service)
    assert (await bulk_service.get(owner.id, again.id)).unchanged == 1  # no type before either


async def test_what_an_action_names_is_checked_once_when_it_starts(world: World) -> None:
    """A tag, contact, type, topic or space that does not exist is told at the start, not
    with every document; what fits its kind is all an action takes."""
    r = await rule_world(world)
    owner = await world.user()
    document = await r.arrive(owner)
    bulk_service = service(r)
    for action in (
        BulkAction(BulkKind.CHANGE_TAGS, add=frozenset({TagId(new_id())})),
        BulkAction(BulkKind.SET_CONTACT, contact=ContactId(new_id())),
        BulkAction(BulkKind.SET_DOCUMENT_TYPE, document_type=DocumentTypeId(new_id())),
        BulkAction(BulkKind.SET_TOPIC, topic=TagId(new_id())),
        BulkAction(BulkKind.MOVE, space=SpaceId(new_id())),
    ):
        with pytest.raises(NotFoundError):
            await bulk_service.start(owner.id, ids(document), action)
    with pytest.raises(ValidationError, match="move takes no add"):
        BulkAction(BulkKind.MOVE, space=SpaceId(new_id()), add=frozenset({TagId(new_id())}))
    with pytest.raises(ValidationError, match="confirm takes no contact, node"):
        BulkAction(BulkKind.CONFIRM, contact=ContactId(new_id()), node=Node.OCR)


async def test_a_selection_by_filter_takes_what_the_person_reaches(world: World) -> None:
    r = await rule_world(world)
    owner, other = await world.user(), await world.user()
    mine = [await r.arrive(owner) for _ in range(3)]
    await r.arrive(other)
    bulk_service = service(r)

    operation = await bulk_service.start(
        owner.id, Selection(), BulkAction(BulkKind.SET_TOPIC, topic=None)
    )
    assert set(operation.documents) == {document.id for document in mine}

    with pytest.raises(PermissionDeniedError):
        await bulk_service.start(owner.id, Selection(all_users=True), BulkAction(BulkKind.CONFIRM))
    everyone = await bulk_service.start(
        r.admin.id, Selection(all_users=True), BulkAction(BulkKind.CONFIRM)
    )
    assert len(everyone.documents) == 4


async def test_a_selection_is_bounded(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    r = await rule_world(world)
    owner = await world.user()
    await r.arrive(owner)
    await r.arrive(owner)
    bulk_service = service(r)
    confirm = BulkAction(BulkKind.CONFIRM)

    too_many = tuple(DocumentId(new_id()) for _ in range(MAX_IDS + 1))
    with pytest.raises(ValidationError) as raised:
        await bulk_service.start(owner.id, Selection(ids=too_many), confirm)
    assert raised.value.reason == because(ReasonCode.BULK_TOO_MANY, max=MAX_IDS)
    monkeypatch.setattr(bulk, "MAX_DOCUMENTS", 1)
    with pytest.raises(ValidationError):
        await bulk_service.start(owner.id, Selection(), confirm)
    with pytest.raises(ValidationError):
        await bulk_service.start(owner.id, Selection(ids=()), confirm)


async def test_a_selection_by_words_takes_every_hit_the_search_reaches(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    found = [await r.arrive(owner) for _ in range(5)]
    hits = Hits(
        [
            SearchItem(document=document, access=SpaceRole.EDIT, score=None, snippet=())
            for document in found
        ]
    )

    operation = await service(r, hits).start(
        owner.id, Selection(text="Rechnung"), BulkAction(BulkKind.CONFIRM)
    )

    assert operation.documents == tuple(document.id for document in found)
    assert hits.asked == [("Rechnung", 0), ("Rechnung", 2), ("Rechnung", 4)]
    with pytest.raises(SearchUnavailableError):
        await service(r).start(owner.id, Selection(text="Rechnung"), BulkAction(BulkKind.CONFIRM))


async def test_move_confirm_reprocess_and_delete_go_through_the_services(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    archive = await world.spaces.create(owner.id, "Archive")
    await r.personal_rule(owner, definition("Check", channel_api(), ForceReview("check")))
    waiting, filed = await r.arrive(owner), await r.arrive(owner)
    assert (waiting.lane, filed.lane) == (Lane.YELLOW, Lane.YELLOW)
    bulk_service = service(r)

    await bulk_service.start(owner.id, ids(waiting, filed), BulkAction(BulkKind.CONFIRM))
    await builders.drain(bulk_service)
    assert (await r.stored(waiting)).lane is None  # processing goes on, as by hand
    await world.drain(r.pipeline())
    assert (await r.stored(waiting)).lane is Lane.GREEN

    await bulk_service.start(owner.id, ids(filed), BulkAction(BulkKind.MOVE, space=archive.id))
    await builders.drain(bulk_service)
    assert (await r.stored(filed)).space_id == archive.id

    await bulk_service.start(
        owner.id, ids(filed), BulkAction(BulkKind.REPROCESS, node=Node.APPLY_RULES)
    )
    await builders.drain(bulk_service)
    assert (await r.stored(filed)).lane is None  # processing again

    deleting = await bulk_service.start(owner.id, ids(waiting, filed), BulkAction(BulkKind.DELETE))
    await builders.drain(bulk_service)
    assert (await bulk_service.get(owner.id, deleting.id)).changed == 2  # also while processing
    async with world.uow() as uow:
        assert await uow.documents.find(waiting.id) is None


async def test_the_job_hands_back_after_a_batch_and_continues(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = await rule_world(world)
    owner = await world.user()
    tax = await r.tag("tax")
    documents = [await r.arrive(owner) for _ in range(5)]
    monkeypatch.setattr(bulk, "BATCH", 2)
    bulk_service = service(r)

    operation = await bulk_service.start(
        owner.id, ids(*documents), BulkAction(BulkKind.CHANGE_TAGS, add=frozenset({tax.id}))
    )

    assert await builders.drain(bulk_service) == 3
    done = await bulk_service.get(owner.id, operation.id)
    assert (done.status, done.changed) == (BulkStatus.DONE, 5)


async def test_a_deactivated_person_stops_the_operation(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    document = await r.arrive(owner)
    bulk_service = service(r)
    operation = await bulk_service.start(owner.id, ids(document), BulkAction(BulkKind.CONFIRM))
    await r.deactivate(owner)

    await builders.drain(bulk_service)

    done = await bulk_service.get(r.admin.id, operation.id)
    assert (done.status, done.position, done.error) == (
        BulkStatus.FAILED,
        0,
        "the user is no longer active",
    )


async def test_only_its_person_and_admins_follow_an_operation(world: World) -> None:
    r = await rule_world(world)
    owner, other = await world.user(), await world.user()
    document = await r.arrive(owner)
    bulk_service = service(r)
    operation = await bulk_service.start(owner.id, ids(document), BulkAction(BulkKind.CONFIRM))

    with pytest.raises(NotFoundError):
        await bulk_service.get(other.id, operation.id)
    assert (await bulk_service.get(r.admin.id, operation.id)).id == operation.id
