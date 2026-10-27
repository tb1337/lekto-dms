"""Relations between documents (#145 PR 9): from the newer to the older, who sees, sets,
accepts and removes them, and the verdict on them."""

from datetime import date, datetime

import pytest

from lekto.core.domain.documents import Document, DocumentChanges
from lekto.core.domain.errors import ConflictError, NotFoundError, PermissionDeniedError
from lekto.core.domain.first_runs import RELATIONS, Verdict
from lekto.core.domain.ids import DocumentId, new_id
from lekto.core.domain.relations import Relation, RelationOrigin, RelationState, ordered
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import User
from lekto.core.services.relations import Direction, RelationService
from tests import builders
from tests.unit.services.support import World

NOW = builders.NOW


async def stored(world: World, owner: User, space: Space, dated: date | None) -> Document:
    document = builders.processed(owner, space)
    if dated is not None:
        document.apply_changes(DocumentChanges(document_date=dated), {}, NOW)
    async with world.uow() as uow:
        await uow.documents.add(document)
        await uow.commit()
    return document


def service(world: World) -> RelationService:
    return RelationService(world.uow, world.clock)


async def verdicts(world: World, id: DocumentId) -> list[tuple[str, Verdict]]:
    async with world.uow() as uow:
        return [(item.field, item.verdict) for item in await uow.processing_facts.verdicts(id)]


def test_the_newer_refers_to_the_older() -> None:
    a, b = DocumentId(new_id()), DocumentId(new_id())
    early, late = datetime(2026, 1, 1, tzinfo=NOW.tzinfo), datetime(2026, 6, 1, tzinfo=NOW.tzinfo)
    # By the document date first, else when they came in.
    assert ordered((a, date(2026, 6, 20), early), (b, date(2026, 1, 31), late)) == (a, b)
    assert ordered((a, None, early), (b, None, late)) == (b, a)
    with pytest.raises(Exception, match="refer to itself"):
        Relation(
            newer=a,
            older=a,
            origin=RelationOrigin.PERSON,
            state=RelationState.SET,
            created_at=NOW,
        )


async def test_a_person_relates_two_documents_and_removes_the_relation(world: World) -> None:
    owner = await world.user()
    space = await world.personal_space(owner)
    original = await stored(world, owner, space, date(2026, 1, 31))
    correction = await stored(world, owner, space, date(2026, 6, 20))
    relations = service(world)

    # From either end: the correction refers to the original.
    await relations.relate(owner.id, original.id, correction.id)
    seen = await relations.relations(owner.id, correction.id)
    assert [(item.other.id, item.direction) for item in seen.refers_to] == [
        (original.id, Direction.REFERS_TO)
    ]
    back = await relations.relations(owner.id, original.id)
    assert [item.other.id for item in back.referred_by] == [correction.id]
    with pytest.raises(ConflictError):
        await relations.relate(owner.id, correction.id, original.id)
    with pytest.raises(ConflictError):
        await relations.relate(owner.id, original.id, original.id)
    assert await verdicts(world, correction.id) == [(RELATIONS, Verdict.ADDED)]

    # A person's relation goes when removed.
    await relations.unrelate(owner.id, correction.id, original.id)
    async with world.uow() as uow:
        assert await uow.document_relations.of_document(original.id) == []
    with pytest.raises(NotFoundError):
        await relations.unrelate(owner.id, correction.id, original.id)


async def test_a_suggestion_is_accepted_or_rejected_for_good(world: World) -> None:
    owner = await world.user()
    space = await world.personal_space(owner)
    invoice = await stored(world, owner, space, date(2026, 6, 4))
    reminder = await stored(world, owner, space, date(2026, 7, 20))
    credit = await stored(world, owner, space, date(2026, 7, 25))
    async with world.uow() as uow:
        for newer in (reminder, credit):
            await uow.document_relations.put(
                Relation(
                    newer=newer.id,
                    older=invoice.id,
                    origin=RelationOrigin.LEKTO,
                    state=RelationState.SUGGESTED,
                    evidence={"kind": "fact", "fact_kind": "invoice_number", "value": "4711"},
                    created_at=NOW,
                )
            )
        await uow.commit()
    relations = service(world)
    assert len((await relations.relations(owner.id, invoice.id)).suggested) == 2
    await relations.relate(owner.id, reminder.id, invoice.id)
    await relations.unrelate(owner.id, credit.id, invoice.id)
    seen = await relations.relations(owner.id, invoice.id)
    assert [item.other.id for item in seen.referred_by] == [reminder.id]
    assert seen.suggested == ()
    async with world.uow() as uow:
        kept = await uow.document_relations.find(credit.id, invoice.id)
    assert kept is not None and kept.state is RelationState.REJECTED  # not suggested again
    assert await verdicts(world, reminder.id) == [(RELATIONS, Verdict.ACCEPTED)]
    assert await verdicts(world, credit.id) == [(RELATIONS, Verdict.CORRECTED)]


async def test_who_sees_and_who_sets_a_relation(world: World) -> None:
    """Only who reads both ends sees it; who edits the newer and reads the older sets it."""
    owner, reader, stranger = await world.user(), await world.user(), await world.user()
    shared = await world.spaces.create(owner.id, "Haushalt")
    await world.spaces.set_member(owner.id, shared.id, reader.id, SpaceRole.READ)
    contract = await stored(world, owner, shared, date(2025, 1, 1))
    private = await stored(world, owner, await world.personal_space(owner), date(2026, 3, 1))
    invoice = await stored(world, owner, shared, date(2026, 2, 1))
    relations = service(world)
    await relations.relate(owner.id, invoice.id, contract.id)
    await relations.relate(owner.id, private.id, contract.id)
    seen = await relations.relations(reader.id, contract.id)
    assert [item.other.id for item in seen.referred_by] == [invoice.id]  # not the private one
    assert not seen.editable and not seen.referred_by[0].changeable
    with pytest.raises(PermissionDeniedError):
        await relations.unrelate(reader.id, invoice.id, contract.id)
    with pytest.raises(NotFoundError):
        await relations.relations(stranger.id, contract.id)
    # The newer is the one to edit: an editor of the shared space relates within it.
    await world.spaces.set_member(owner.id, shared.id, reader.id, SpaceRole.EDIT)
    newer = await stored(world, owner, shared, date(2026, 4, 1))
    await relations.relate(reader.id, contract.id, newer.id)
    seen = await relations.relations(reader.id, contract.id)
    assert {item.other.id: item.changeable for item in seen.referred_by} == {
        newer.id: True,
        invoice.id: True,
    }


async def test_a_date_that_turns_the_pair_turns_the_relation(world: World) -> None:
    """Stored in the order of when it was set, read in the order of the dates now: found,
    changed and removed from either end, never twice."""
    owner = await world.user()
    space = await world.personal_space(owner)
    first = await stored(world, owner, space, date(2026, 1, 31))
    second = await stored(world, owner, space, date(2026, 6, 20))
    relations = service(world)
    await relations.relate(owner.id, second.id, first.id)
    await world.documents.change_metadata(
        owner.id, second.id, DocumentChanges(document_date=date(2025, 12, 1))
    )
    seen = await relations.relations(owner.id, first.id)
    assert [(item.other.id, item.changeable) for item in seen.refers_to] == [(second.id, True)]
    with pytest.raises(ConflictError):
        await relations.relate(owner.id, first.id, second.id)
    await relations.unrelate(owner.id, second.id, first.id)
    assert (await relations.relations(owner.id, first.id)).refers_to == ()


async def test_a_rejection_outlasts_setting_and_removing_by_hand(world: World) -> None:
    owner = await world.user()
    space = await world.personal_space(owner)
    invoice = await stored(world, owner, space, date(2026, 6, 4))
    reminder = await stored(world, owner, space, date(2026, 7, 20))
    async with world.uow() as uow:
        await uow.document_relations.put(
            Relation(
                newer=reminder.id,
                older=invoice.id,
                origin=RelationOrigin.LEKTO,
                state=RelationState.SUGGESTED,
                created_at=NOW,
            )
        )
        await uow.commit()
    relations = service(world)
    await relations.unrelate(owner.id, reminder.id, invoice.id)
    await relations.relate(owner.id, reminder.id, invoice.id)
    await relations.unrelate(owner.id, reminder.id, invoice.id)
    async with world.uow() as uow:
        kept = await uow.document_relations.find(reminder.id, invoice.id)
    assert kept is not None and kept.state is RelationState.REJECTED
