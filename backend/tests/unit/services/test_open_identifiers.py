"""The open identifiers for admins: the list, where one stands, and decisions about them."""

from collections.abc import Collection

import pytest

from lekto.core.domain.document_facts import DocumentFact, FactOrigin, FactRole, role_of
from lekto.core.domain.errors import ConflictError, NotFoundError, PermissionDeniedError
from lekto.core.domain.identifiers import Identifier, IdentifierKind, IdentifierSource
from lekto.core.domain.master_data import Contact
from lekto.core.domain.open_identifiers import OpenSource
from lekto.core.domain.reasons import ReasonCode
from lekto.core.domain.users import Role, User
from lekto.core.services.objects import text_key
from lekto.core.services.open_identifiers import OpenAction, OpenDecision
from tests import builders
from tests.builders import NOW
from tests.unit.services.support import World

IBAN = (IdentifierKind.IBAN, "DE02120300000000202051")
VAT = (IdentifierKind.VAT_ID, "DE312456789")
CUSTOMER = (IdentifierKind.CUSTOMER_NUMBER, "20047718")
TEXT = "Stadtwerke Nord\nKundennummer 2004 7718\nUSt-IdNr. DE312456789\n"


async def confirmed(
    world: World, owner: User, contact: Contact, keys: Collection[tuple[IdentifierKind, str]]
) -> None:
    """A confirmed document of `contact` that shows `keys`, with its text."""
    space = await world.personal_space(owner)
    document = builders.processed(owner, space)
    document.contact_id = contact.id
    document.mark_confirmed(NOW)
    facts = []
    for kind, value in keys:
        written = "2004 7718" if kind is IdentifierKind.CUSTOMER_NUMBER else value
        position = TEXT.find(written)
        facts.append(
            DocumentFact(
                kind=kind,
                value=value,
                role=role_of(kind),
                origins=frozenset({FactOrigin.PATTERN}),
                written=written,
                position=None if position < 0 else position,
            )
        )
    async with world.uow() as uow:
        await uow.documents.add(document)
        await uow.document_facts.replace_found(document.id, facts)
        await uow.commit()
    await world.object_store.put(text_key(document.id), TEXT.encode(), content_type="text/plain")


async def setting(world: World) -> tuple[User, Contact, Contact]:
    """An admin, the utility that learned the customer number, and a bank; the VAT ID stands
    in documents of the utility only, the IBAN in documents of both."""
    admin = await world.user(role=Role.ADMIN)
    utility, bank = (Contact.create(name=name, now=NOW) for name in ("Stadtwerke", "Bank"))
    utility.set_learned([Identifier(*CUSTOMER, IdentifierSource.LEARNED)])
    async with world.uow() as uow:
        await uow.contacts.add(utility)
        await uow.contacts.add(bank)
        await uow.commit()
    await confirmed(world, admin, utility, [CUSTOMER, VAT, IBAN])
    await confirmed(world, admin, utility, [CUSTOMER, IBAN])
    await confirmed(world, admin, bank, [IBAN])
    return admin, utility, bank


async def held(world: World, contact: Contact) -> dict[tuple[IdentifierKind, str], str]:
    async with world.uow() as uow:
        stored = await uow.contacts.get(contact.id)
    return {item.key: item.source.value for item in stored.identifiers}


async def test_an_admin_lists_the_open_identifiers(world: World) -> None:
    admin, utility, bank = await setting(world)
    page = await world.open_identifiers.page(admin.id)
    assert [(item.key, item.source, len(item.seen)) for item in page.items] == [
        (IBAN, OpenSource.UNKNOWN, 3),
        (CUSTOMER, OpenSource.LEARNED, 2),
        (VAT, OpenSource.UNKNOWN, 1),
    ]
    assert page.items[0].contacts == (utility.id, bank.id)
    assert page.counts == {OpenSource.LEARNED: 1, OpenSource.UNKNOWN: 2}
    assert page.names == {utility.id: "Stadtwerke", bank.id: "Bank"}

    learned = await world.open_identifiers.page(admin.id, source=OpenSource.LEARNED)
    assert [item.key for item in learned.items] == [CUSTOMER]
    assert learned.counts == page.counts  # not narrowed by the source
    words = await world.open_identifiers.page(admin.id, words="de02 1203")
    assert [item.key for item in words.items] == [IBAN]
    named = await world.open_identifiers.page(admin.id, words="bank")
    assert [item.key for item in named.items] == [IBAN]
    paged = await world.open_identifiers.page(admin.id, offset=1, limit=1)
    assert ([item.key for item in paged.items], paged.total) == ([CUSTOMER], 3)
    assert await world.open_identifiers.summary(admin.id) == page.counts

    user = await world.user()
    with pytest.raises(PermissionDeniedError):
        await world.open_identifiers.page(user.id)


async def test_a_detail_shows_where_it_stands(world: World) -> None:
    admin, utility, _ = await setting(world)
    detail = await world.open_identifiers.detail(admin.id, *CUSTOMER)
    assert detail.names == {utility.id: "Stadtwerke"}
    assert len(detail.places) == 2
    place = detail.places[0]
    assert place.role is FactRole.CONTACT
    assert place.excerpt is not None
    assert (place.excerpt.before, place.excerpt.match) == (
        "Stadtwerke Nord Kundennummer ",
        "2004 7718",
    )
    with pytest.raises(NotFoundError):
        await world.open_identifiers.detail(admin.id, IdentifierKind.VAT_ID, "DE999999999")


async def test_decisions_confirm_and_reject_one_by_one(world: World) -> None:
    admin, utility, bank = await setting(world)
    outcomes = await world.open_identifiers.decide(
        admin.id,
        [
            OpenDecision(kind=CUSTOMER[0], value=CUSTOMER[1], action=OpenAction.CONFIRM),
            OpenDecision(kind=VAT[0], value=VAT[1], action=OpenAction.CONFIRM),
            # Its documents name two contacts: which one?
            OpenDecision(kind=IBAN[0], value=IBAN[1], action=OpenAction.CONFIRM),
            OpenDecision(kind=IdentifierKind.VAT_ID, value="DE999999999", action=OpenAction.REJECT),
        ],
    )
    assert [outcome.error is None for outcome in outcomes] == [True, True, False, False]
    assert outcomes[2].error is not None
    assert outcomes[2].error.code is ReasonCode.IDENTIFIER_CONTACT_UNCLEAR
    assert outcomes[3].error is not None
    assert outcomes[3].error.code is ReasonCode.IDENTIFIER_NOT_OPEN
    assert await held(world, utility) == {CUSTOMER: "manual", VAT: "manual"}

    # Rejected at the contact with most documents: training does not learn it again.
    (rejected,) = await world.open_identifiers.decide(
        admin.id, [OpenDecision(kind=IBAN[0], value=IBAN[1], action=OpenAction.REJECT)]
    )
    assert rejected.error is None
    assert (await held(world, utility))[IBAN] == "rejected"
    assert await held(world, bank) == {}
    assert (await world.open_identifiers.page(admin.id)).items == []


async def test_a_learned_one_is_rejected_or_moved_by_its_contact(world: World) -> None:
    admin, utility, bank = await setting(world)
    await world.open_identifiers.decide(
        admin.id,
        [
            OpenDecision(kind=CUSTOMER[0], value=CUSTOMER[1], action=OpenAction.REJECT),
            OpenDecision(kind=IBAN[0], value=IBAN[1], action=OpenAction.CONFIRM, contact=bank.id),
        ],
    )
    assert await held(world, utility) == {CUSTOMER: "rejected"}
    assert await held(world, bank) == {IBAN: "manual"}
    user = await world.user()
    with pytest.raises(PermissionDeniedError):
        await world.open_identifiers.decide(
            user.id, [OpenDecision(kind=VAT[0], value=VAT[1], action=OpenAction.REJECT)]
        )


async def test_an_identifier_entered_by_hand_is_not_rejected_at_its_contact(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    contact = await world.master_data.create_contact(
        admin.id, "Nord", identifiers=[Identifier(*VAT)]
    )
    with pytest.raises(ConflictError):
        await world.master_data.reject_identifier(admin.id, contact.id, VAT)
