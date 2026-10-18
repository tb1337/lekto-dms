"""Tests of services that depend on how the persistence handles concurrent units and stored
references: run on the in-memory adapters, SQLite and Postgres alike (each needs the fixture
`uow_factory`)."""

import asyncio

import pytest

from papiq.adapters.outbound.memory import ManualClock, MemoryObjectStore
from papiq.core.domain.documents import Document, DocumentChanges
from papiq.core.domain.master_data import TagScope
from papiq.core.domain.pipeline import Lane
from papiq.core.domain.users import User
from papiq.core.ports import UnitOfWorkFactory
from papiq.core.services import master_data
from papiq.core.services.documents import DocumentService
from papiq.core.services.master_data import MasterDataService
from tests import builders
from tests.builders import NOW
from tests.contracts.unit_of_work import owner_with_space


async def _admin(uow_factory: UnitOfWorkFactory) -> User:
    admin = builders.admin()
    async with uow_factory() as uow:
        await uow.users.add(admin)
        await uow.commit()
    return admin


class ServicesOverPersistence:
    async def test_concurrent_tag_moves_make_no_cycle(self, uow_factory: UnitOfWorkFactory) -> None:
        """Moving A under B and B under A at once: one move waits for the other and sees it."""
        admin = await _admin(uow_factory)
        service = MasterDataService(uow_factory, ManualClock(NOW), builders.TEMPLATES)
        a = await service.create_tag(admin.id, "A")
        b = await service.create_tag(admin.id, "B")
        results = await asyncio.gather(
            service.change_tag(admin.id, a.id, parent_id=b.id),
            service.change_tag(admin.id, b.id, parent_id=a.id),
            return_exceptions=True,
        )
        assert sorted(type(result).__name__ for result in results) == ["Tag", "ValidationError"]
        async with uow_factory() as uow:
            tags = {tag.id: tag for tag in await uow.tags.list_all()}
        assert None in {tags[a.id].parent_id, tags[b.id].parent_id}

    async def test_a_moved_tag_leaves_documents_and_groups_the_tag_below(
        self, uow_factory: UnitOfWorkFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The job after a move, a page of documents at a time (each step queueing the next):
        what carries a tag and one now above it keeps the one below, as if set anew; the lane,
        the confirmation, other tags and other documents stay."""
        monkeypatch.setattr(master_data, "_NORMALISE_BATCH", 2)
        owner, space = await owner_with_space(uow_factory)
        admin = await _admin(uow_factory)
        service = MasterDataService(uow_factory, ManualClock(NOW), builders.TEMPLATES)
        insurance = await service.create_tag(admin.id, "Insurance")
        health = await service.create_tag(admin.id, "Health")
        dental = await service.create_tag(admin.id, "Dental", parent_id=health.id)
        other = await service.create_tag(admin.id, "Other")
        insurer = await service.create_tag(admin.id, "Insurer", scope=TagScope.CONTACT)
        kassen = await service.create_tag(admin.id, "Kassen", scope=TagScope.CONTACT)
        bills = await service.create_tag(admin.id, "Bills", scope=TagScope.DOCUMENT_TYPE)
        medical = await service.create_tag(admin.id, "Medical", scope=TagScope.DOCUMENT_TYPE)
        nord = await service.create_contact(admin.id, "Nord", group_ids=[insurer.id, kassen.id])
        invoice = await service.create_document_type(
            admin.id, "Invoice", group_ids=[bills.id, medical.id]
        )
        carried = [
            {insurance.id, health.id},
            {insurance.id, dental.id, other.id},
            {insurance.id},
            {health.id},
            {insurance.id, health.id},
        ]
        documents: list[Document] = []
        async with uow_factory() as uow:
            for number, tags in enumerate(carried):
                document = builders.run_pipeline(
                    builders.document(owner, space, content=str(number))
                )
                document.tag_ids = set(tags)
                if number == 0:
                    document.mark_confirmed(NOW)
                await uow.documents.add(document)
                documents.append(document)
            await uow.commit()
        await service.change_tag(admin.id, health.id, parent_id=insurance.id)
        await service.change_tag(admin.id, kassen.id, parent_id=insurer.id)
        await service.change_tag(admin.id, medical.id, parent_id=bills.id)
        # Health: four documents carry it or Dental, two per step, and a last step finds none.
        assert [await service.run_next_job() for _ in range(6)] == [True] * 5 + [False]
        async with uow_factory() as uow:
            stored = [await uow.documents.get(document.id) for document in documents]
            assert (await uow.contacts.get(nord.id)).group_ids == {kassen.id}
            assert (await uow.document_types.get(invoice.id)).group_ids == {medical.id}
        assert [document.tag_ids for document in stored] == [
            {health.id},
            {dental.id, other.id},
            {insurance.id},
            {health.id},
            {health.id},
        ]
        assert [document.version for document in stored] == [2, 2, 1, 1, 2]
        assert {document.lane for document in stored} == {Lane.GREEN}
        assert [document.confirmed_at for document in stored[:2]] == [NOW, None]

    async def test_groups_and_topics_count_their_contacts_and_types(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        """Each contact (type) once at its group or topic and at those above it, from the
        stored groups and topics of contacts and types."""
        admin = await _admin(uow_factory)
        service = MasterDataService(uow_factory, ManualClock(NOW), builders.TEMPLATES)
        insurer = await service.create_tag(admin.id, "Insurer", scope=TagScope.CONTACT)
        health = await service.create_tag(
            admin.id, "Health insurer", scope=TagScope.CONTACT, parent_id=insurer.id
        )
        bank = await service.create_tag(admin.id, "Bank", scope=TagScope.CONTACT)
        insurance = await service.create_tag(admin.id, "Insurance", scope=TagScope.TOPIC)
        dental = await service.create_tag(
            admin.id, "Dental", scope=TagScope.TOPIC, parent_id=insurance.id
        )
        bills = await service.create_tag(admin.id, "Bills", scope=TagScope.DOCUMENT_TYPE)
        medical = await service.create_tag(
            admin.id, "Medical", scope=TagScope.DOCUMENT_TYPE, parent_id=bills.id
        )
        await service.create_contact(
            admin.id,
            "Nord",
            group_ids=[insurer.id, health.id],
            topic_ids=[insurance.id, dental.id],
        )
        await service.create_contact(admin.id, "Süd", group_ids=[health.id], topic_ids=[dental.id])
        await service.create_contact(admin.id, "Plain")
        await service.create_document_type(admin.id, "Invoice", group_ids=[medical.id])
        await service.create_document_type(admin.id, "Receipt", group_ids=[bills.id])
        members = await service.tag_members(admin.id)
        assert members.contacts == {insurer.id: 2, health.id: 2, insurance.id: 2, dental.id: 2}
        assert bank.id not in members.contacts
        assert members.document_types == {bills.id: 2, medical.id: 1}

    async def test_a_topic_is_not_given_while_its_contact_gives_it_up(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        """Taking a topic away from a contact and giving it to one of its documents at once:
        one waits for the other (`contact_topics_lock`) and sees it, so no document keeps a
        topic its contact does not enable."""
        owner, space = await owner_with_space(uow_factory)
        admin = await _admin(uow_factory)
        master = MasterDataService(uow_factory, ManualClock(NOW), builders.TEMPLATES)
        documents = DocumentService(uow_factory, ManualClock(NOW), MemoryObjectStore())
        work = await master.create_tag(admin.id, "Work", scope=TagScope.TOPIC)
        nord = await master.create_contact(admin.id, "Nord", topic_ids=[work.id])
        document = builders.document(owner, space)
        async with uow_factory() as uow:
            await uow.documents.add(document)
            await uow.commit()
        await documents.update_metadata(owner.id, document.id, DocumentChanges(contact_id=nord.id))
        results = await asyncio.gather(
            master.change_contact(admin.id, nord.id, topic_ids=[]),
            documents.update_metadata(owner.id, document.id, DocumentChanges(topic_id=work.id)),
            return_exceptions=True,
        )
        assert sorted(type(result).__name__ for result in results) in (
            ["Contact", "ValidationError"],
            ["ConflictError", "Document"],
        ), results
        async with uow_factory() as uow:
            stored = await uow.documents.get(document.id)
            contact = await uow.contacts.get(nord.id)
        assert stored.topic_id is None or stored.topic_id in contact.topic_ids
