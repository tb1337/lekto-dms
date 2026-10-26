"""The documents expected next (#145 PR 12, `services.expected`)."""

from datetime import date, datetime

import pytest

from lekto.core.domain.document_facts import DocumentFact, FactOrigin, FactRole
from lekto.core.domain.documents import DocumentChanges
from lekto.core.domain.errors import PermissionDeniedError
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.master_data import Contact, DocumentType
from lekto.core.domain.series import Cadence, SeriesState
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import Role, User
from lekto.core.services.expected import ExpectedService
from tests import builders
from tests.unit.services.support import World

NOW = builders.NOW
V1 = (IdentifierKind.CONTRACT_NUMBER, "V-1")
V2 = (IdentifierKind.CONTRACT_NUMBER, "V-2")


async def seed(world: World) -> tuple[Contact, DocumentType]:
    contact = Contact.create(name="Stadtwerke", now=NOW)
    kind = DocumentType.create(name="Abschlag", now=NOW)
    async with world.uow() as uow:
        await uow.contacts.add(contact)
        await uow.document_types.add(kind)
        await uow.commit()
    return contact, kind


async def bill(
    world: World,
    owner: User,
    space: Space,
    contact: Contact,
    kind: DocumentType,
    day: date,
    number: str | None = None,
) -> None:
    document = builders.processed(owner, space)
    document.apply_changes(
        DocumentChanges(contact_id=contact.id, document_type_id=kind.id, document_date=day),
        {},
        NOW,
    )
    async with world.uow() as uow:
        await uow.documents.add(document)
        if number is not None:
            await uow.document_facts.replace_found(
                document.id,
                [
                    DocumentFact(
                        kind=IdentifierKind.CONTRACT_NUMBER,
                        value=number,
                        role=FactRole.TARGET,
                        origins=frozenset({FactOrigin.PATTERN}),
                    )
                ],
            )
        await uow.commit()


async def test_monthly_bills_expect_the_next_and_keep_two_contracts_apart(world: World) -> None:
    owner = await world.user()
    space = await world.personal_space(owner)
    contact, kind = await seed(world)
    for month in (7, 8, 9):
        await bill(world, owner, space, contact, kind, date(2026, month, 15), "V-1")
        await bill(world, owner, space, contact, kind, date(2026, month, 1), "V-2")
    world.clock.set(datetime(2026, 10, 10, 12, tzinfo=NOW.tzinfo))
    found = await ExpectedService(world.uow, world.clock).expected(owner.id)
    assert [
        (item.series.key.number, item.series.cadence, item.series.next_date, item.state)
        for item in found
    ] == [
        (V2, Cadence.MONTHLY, date(2026, 10, 1), SeriesState.OVERDUE),
        (V1, Cadence.MONTHLY, date(2026, 10, 15), SeriesState.SOON),
    ]
    assert (found[0].contact, found[0].document_type) == ("Stadtwerke", "Abschlag")


async def test_only_the_documents_one_may_read(world: World) -> None:
    owner, stranger = await world.user(), await world.user()
    admin = await world.user(role=Role.ADMIN)
    space = await world.personal_space(owner)
    contact, kind = await seed(world)
    for month in (7, 8, 9):
        await bill(world, owner, space, contact, kind, date(2026, month, 15))
    service = ExpectedService(world.uow, world.clock)
    assert await service.expected(stranger.id) == []
    assert len(await service.expected(admin.id, all_users=True)) == 1
    with pytest.raises(PermissionDeniedError):
        await service.expected(owner.id, all_users=True)
