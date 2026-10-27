"""The documents expected next (#145 PR 12, `services.expected`)."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from lekto.core.domain.document_facts import DocumentFact, FactOrigin, FactRole
from lekto.core.domain.documents import Document, DocumentChanges
from lekto.core.domain.errors import PermissionDeniedError
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.master_data import Contact, DocumentType
from lekto.core.domain.series import Cadence, SeriesState
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import Role, User
from lekto.core.services.expected import ExpectedService, number
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
) -> Document:
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
    return document


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


async def test_a_number_written_two_ways_and_a_missing_one_stay_one_series(world: World) -> None:
    """From the review of #159: the value counts, not its kind; a bill whose number was not
    read joins the only numbered series of its contact and type; a person's number names
    none."""
    owner = await world.user()
    space = await world.personal_space(owner)
    contact, kind = await seed(world)
    await bill(world, owner, space, contact, kind, date(2026, 6, 15), "123456")
    await bill(world, owner, space, contact, kind, date(2026, 7, 15))
    document = await bill(world, owner, space, contact, kind, date(2026, 8, 15))
    async with world.uow() as uow:
        await uow.document_facts.replace_found(
            document.id,
            [
                DocumentFact(
                    kind=IdentifierKind.CUSTOMER_NUMBER,
                    value="123456",
                    role=FactRole.CONTACT,
                    origins=frozenset({FactOrigin.PATTERN}),
                )
            ],
        )
        await uow.commit()
    await bill(world, owner, space, contact, kind, date(2026, 9, 15), "123456")
    world.clock.set(datetime(2026, 9, 20, 12, tzinfo=NOW.tzinfo))
    (found,) = await ExpectedService(world.uow, world.clock).expected(owner.id)
    assert found.series.key.number == (IdentifierKind.CONTRACT_NUMBER, "123456")
    assert len(found.series.documents) == 4


def test_a_person_s_number_names_no_series() -> None:
    private = DocumentFact(
        kind=IdentifierKind.CUSTOMER_NUMBER,
        value="4711",
        role=FactRole.PERSON,
        origins=frozenset({FactOrigin.PERSON}),
    )
    assert number([private]) is None


async def test_today_is_the_day_in_the_caller_s_time_zone(world: World) -> None:
    owner = await world.user()
    space = await world.personal_space(owner)
    contact, kind = await seed(world)
    for month in (7, 8, 9):
        await bill(world, owner, space, contact, kind, date(2026, month, 5))
    # 7 October, 23:30 in UTC, is 8 October in Berlin: past the spread of the 5th.
    world.clock.set(datetime(2026, 10, 7, 23, 30, tzinfo=UTC))
    service = ExpectedService(world.uow, world.clock)
    (utc,) = await service.expected(owner.id)
    (berlin,) = await service.expected(owner.id, zone=ZoneInfo("Europe/Berlin"))
    assert (utc.state, berlin.state) == (SeriesState.SOON, SeriesState.OVERDUE)
