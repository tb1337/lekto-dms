"""The stream of documents (#145 PR 13, `services.stream`): series lanes with their relation
target at the start and the expected document, branches, chains and the rest."""

from datetime import date, datetime

from lekto.core.domain.documents import Document, DocumentChanges
from lekto.core.domain.ids import ContactId, DocumentTypeId
from lekto.core.domain.master_data import Contact, DocumentType
from lekto.core.domain.relations import Relation, RelationOrigin, RelationState
from lekto.core.domain.series import SeriesState
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import User
from lekto.core.ports.repository import DocumentFilter
from lekto.core.services.stream import LaneKind, StreamService
from tests import builders
from tests.unit.services.support import World

NOW = builders.NOW


class Scene:
    def __init__(self, world: World, owner: User, space: Space) -> None:
        self.world, self.owner, self.space = world, owner, space

    @classmethod
    async def of(cls, world: World) -> "Scene":
        owner = await world.user()
        return cls(world, owner, await world.personal_space(owner))

    async def contact(self, name: str) -> ContactId:
        contact = Contact.create(name=name, now=NOW)
        async with self.world.uow() as uow:
            await uow.contacts.add(contact)
            await uow.commit()
        return contact.id

    async def kind(self, name: str, *, target: bool = False) -> DocumentTypeId:
        kind = DocumentType.create(name=name, now=NOW, relation_target=target)
        async with self.world.uow() as uow:
            await uow.document_types.add(kind)
            await uow.commit()
        return kind.id

    async def document(
        self, contact: ContactId | None, kind: DocumentTypeId | None, day: date | None
    ) -> Document:
        document = builders.processed(self.owner, self.space)
        document.apply_changes(
            DocumentChanges(contact_id=contact, document_type_id=kind, document_date=day), {}, NOW
        )
        async with self.world.uow() as uow:
            await uow.documents.add(document)
            await uow.commit()
        return document

    async def relate(self, newer: Document, older: Document) -> None:
        async with self.world.uow() as uow:
            await uow.document_relations.put(
                Relation(
                    newer=newer.id,
                    older=older.id,
                    origin=RelationOrigin.PERSON,
                    state=RelationState.SET,
                    created_at=NOW,
                )
            )
            await uow.commit()


async def test_a_contact_s_stream(world: World) -> None:
    s = await Scene.of(world)
    insurer = await s.contact("Nord Versicherung")
    contract, bill, complaint = (
        await s.kind("Vertrag", target=True),
        await s.kind("Beitragsrechnung"),
        await s.kind("Reklamation"),
    )
    policy = await s.document(insurer, contract, date(2025, 12, 1))
    bills = [await s.document(insurer, bill, date(2026, month, 1)) for month in (7, 8, 9)]
    for item in bills:
        await s.relate(item, policy)
    letter = await s.document(insurer, complaint, date(2026, 8, 10))
    answer = await s.document(insurer, complaint, date(2026, 8, 20))
    await s.relate(letter, bills[1])
    await s.relate(answer, letter)
    loose = await s.document(insurer, None, date(2026, 5, 5))
    world.clock.set(datetime(2026, 10, 2, 12, tzinfo=NOW.tzinfo))

    stream = await StreamService(world.uow, world.clock).stream(
        s.owner.id, DocumentFilter(contacts=frozenset({insurer}))
    )

    kinds = [lane.kind for lane in stream.lanes]
    assert kinds == [LaneKind.SERIES, LaneKind.BRANCH, LaneKind.SINGLE]
    series, branch, single = stream.lanes
    assert [item.id for item in series.documents] == [item.id for item in bills]
    assert series.target is not None and series.target.id == policy.id
    assert series.state is SeriesState.SOON
    assert [item.id for item in branch.documents] == [letter.id, answer.id]
    assert (branch.parent, branch.joins) == (0, bills[1].id)
    assert [item.id for item in single.documents] == [loose.id]
    assert len(stream.relations) == 5 and not stream.truncated


async def test_documents_related_among_themselves_make_a_chain(world: World) -> None:
    s = await Scene.of(world)
    shop = await s.contact("Versandhaus")
    invoice = await s.document(shop, None, date(2026, 5, 12))
    reminder = await s.document(shop, None, date(2026, 6, 10))
    await s.relate(reminder, invoice)
    stream = await StreamService(world.uow, world.clock).stream(s.owner.id, DocumentFilter())
    (chain,) = stream.lanes
    assert chain.kind is LaneKind.CHAIN
    assert [item.id for item in chain.documents] == [invoice.id, reminder.id]
