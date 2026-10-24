"""A user's numbers at contacts over HTTP (issue #82): who sees which identifier of a contact,
and how a user keeps the numbers that name them in their profile."""

from typing import Any
from uuid import UUID

import httpx2

from lekto.adapters.inbound.rest import PREFIX
from lekto.core.domain.identifiers import Identifier, IdentifierKind, IdentifierSource
from lekto.core.domain.ids import ContactId, SpaceId, UserId
from lekto.core.domain.master_data import Contact, TagScope
from lekto.core.domain.spaces import SpaceRole
from lekto.core.domain.users import User
from tests.api import auth
from tests.unit.adapters.rest.support import Api

OWN = "/auth/me/profile"
PUBLIC_IBAN = "DE89370400440532013000"
LEARNED_IBAN = "DE02120300000000202051"
CUSTOMER = IdentifierKind.CUSTOMER_NUMBER
PERSONNEL = IdentifierKind.PERSONNEL_NUMBER


async def change(api: Api, user: User, body: object, path: str = OWN) -> httpx2.Response:
    """Change a profile signed in as `user` (a profile needs a session)."""
    async with api.sign_in(user) as session:
        return await session.client.patch(f"{PREFIX}{path}", json=body, headers=session.headers)


async def read(api: Api, user: User, path: str = OWN) -> dict[str, Any]:
    async with api.sign_in(user) as session:
        response = await session.client.get(f"{PREFIX}{path}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def values(api: Api, user: User, contact: ContactId) -> list[str]:
    """The values of the contact's identifiers `user` sees, alone and in the list."""
    one = await api.client.get(f"{PREFIX}/contacts/{contact}", headers=auth(user))
    assert one.status_code == 200, one.text
    listed = await api.client.get(f"{PREFIX}/contacts", headers=auth(user))
    (same,) = [item for item in listed.json() if item["id"] == str(contact)]
    assert same["identifiers"] == one.json()["identifiers"]
    return [item["value"] for item in one.json()["identifiers"]]


async def learn(api: Api, contact: ContactId, *learned: Identifier) -> None:
    """As training would: the learned identifiers of the contact."""
    async with api.container.unit_of_work() as uow:
        stored = await uow.contacts.get(contact)
        stored.set_learned(learned)
        await uow.contacts.update(stored)
        await uow.commit()


async def personal_space(api: Api, user: User) -> SpaceId:
    async with api.container.unit_of_work() as uow:
        return (await uow.spaces.get_personal(user.id)).id


async def test_a_contact_shows_each_user_what_they_may_see(api: Api) -> None:
    anna, bob, admin = await api.user("anna"), await api.user("bob"), await api.admin()
    own = await personal_space(api, anna)
    insurer = await api.services.master_data.create_contact(
        admin.id,
        "Insurer",
        identifiers=[
            Identifier.parse(IdentifierKind.IBAN, PUBLIC_IBAN),
            Identifier.parse(CUSTOMER, "K-4711", user_id=UserId(anna.id)),
        ],
    )
    learned = IdentifierSource.LEARNED
    await learn(
        api,
        insurer.id,
        Identifier(IdentifierKind.IBAN, LEARNED_IBAN, learned, learned_in=frozenset({own})),
        Identifier(PERSONNEL, "12345", learned, None, UserId(anna.id), frozenset({own})),
        Identifier(IdentifierKind.VAT_ID, "DE123456789", learned),  # before 0040: no spaces
    )
    await api.services.master_data.change_contact(
        admin.id,
        insurer.id,
        rejected_identifiers=[Identifier.parse(IdentifierKind.EMAIL_DOMAIN, "insurer.example")],
    )

    assert await values(api, admin, insurer.id) == [
        PUBLIC_IBAN,
        "K4711",
        LEARNED_IBAN,
        "DE123456789",
        "12345",
        "insurer.example",
    ]
    assert await values(api, anna, insurer.id) == [PUBLIC_IBAN, "K4711", LEARNED_IBAN, "12345"]
    assert await values(api, bob, insurer.id) == [PUBLIC_IBAN]
    # A member of the space it was learned in sees what was learned there, not her numbers.
    await api.services.spaces.set_member(anna.id, own, bob.id, SpaceRole.READ)
    assert await values(api, bob, insurer.id) == [PUBLIC_IBAN, LEARNED_IBAN]


async def test_a_user_keeps_their_numbers_in_their_profile(api: Api) -> None:
    anna, bob, admin = await api.user("anna"), await api.user("bob"), await api.admin()
    work = await api.services.master_data.create_tag(admin.id, "Work", scope=TagScope.TOPIC)
    employer = await api.services.master_data.create_contact(
        admin.id, "Employer", topic_ids=[work.id]
    )
    insurer = await api.services.master_data.create_contact(admin.id, "Insurer")
    mine = UserId(anna.id)
    learned = IdentifierSource.LEARNED
    await learn(
        api,
        insurer.id,
        Identifier(CUSTOMER, "K2002", learned, user_id=mine),
        Identifier(CUSTOMER, "K3003", learned, user_id=mine),
    )
    assert (await read(api, anna))["numbers"] == [
        number(insurer, "customer_number", "K2002", "learned"),
        number(insurer, "customer_number", "K3003", "learned"),
    ]

    body = {
        "numbers": [
            {
                "contact_id": str(employer.id),
                "kind": "personnel_number",
                "value": "12345",
                "topic_id": str(work.id),
            },
            {"contact_id": str(insurer.id), "kind": "customer_number", "value": "K 2002"},
        ],
        "declined_numbers": [
            {"contact_id": str(insurer.id), "kind": "customer_number", "value": "K3003"}
        ],
    }
    changed = await change(api, anna, body)
    assert changed.status_code == 200, changed.text
    assert changed.json()["numbers"] == [
        number(employer, "personnel_number", "12345", "manual", work.id),
        number(insurer, "customer_number", "K2002", "manual"),
    ]
    async with api.container.unit_of_work() as uow:
        stored = await uow.contacts.get(insurer.id)
    assert [(item.value, item.source, item.user_id) for item in stored.identifiers] == [
        ("K2002", IdentifierSource.MANUAL, mine),
        ("K3003", IdentifierSource.REJECTED, None),  # declined: not learned again
    ]
    assert await values(api, bob, employer.id) == []
    # Learned ones left out stay; what she entered and leaves out goes.
    await learn(api, insurer.id, Identifier(CUSTOMER, "K4004", learned, user_id=mine))
    emptied = await change(api, anna, {"numbers": []})
    assert emptied.json()["numbers"] == [number(insurer, "customer_number", "K4004", "learned")]
    assert await values(api, admin, employer.id) == []

    # An admin keeps them too, with a session; an admin's token may not.
    path = f"/users/{anna.id}/profile"
    by_admin = await change(api, admin, {"numbers": [body["numbers"][1]]}, path)
    assert by_admin.status_code == 200, by_admin.text
    token = await api.client.patch(f"{PREFIX}{path}", json={"numbers": []}, headers=auth(admin))
    assert token.status_code == 403

    unknown = {"contact_id": str(UUID(int=1)), "kind": "customer_number", "value": "K5005"}
    assert (await change(api, anna, {"numbers": [unknown]})).status_code == 404
    vat = {"contact_id": str(insurer.id), "kind": "vat_id", "value": "DE123456789"}
    assert (await change(api, anna, {"numbers": [vat]})).status_code == 422


async def test_a_number_moves_between_contacts_in_one_change(api: Api) -> None:
    anna, admin = await api.user("anna"), await api.admin()
    first = await api.services.master_data.create_contact(
        admin.id, "First", identifiers=[Identifier.parse(CUSTOMER, "K4711", user_id=anna.id)]
    )
    second = await api.services.master_data.create_contact(admin.id, "Second")
    moved = {"contact_id": str(second.id), "kind": "customer_number", "value": "K4711"}
    changed = await change(api, anna, {"numbers": [moved]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["numbers"] == [number(second, "customer_number", "K4711", "manual")]
    assert await values(api, admin, first.id) == []


async def test_a_taken_number_tells_whose_only_to_who_sees_it(api: Api) -> None:
    anna, bob, admin = await api.user("anna"), await api.user("bob"), await api.admin()
    employer = await api.services.master_data.create_contact(admin.id, "Employer")
    insurer = await api.services.master_data.create_contact(
        admin.id,
        "Insurer",
        identifiers=[
            Identifier.parse(CUSTOMER, "K9009", user_id=bob.id),
            Identifier.parse(CUSTOMER, "K7007"),
        ],
    )

    def entered(contact: Contact, value: str) -> dict[str, Any]:
        return {
            "numbers": [{"contact_id": str(contact.id), "kind": "customer_number", "value": value}]
        }

    for contact in (employer, insurer):
        taken = await change(api, anna, entered(contact, "K9009"))
        assert taken.status_code == 409, taken.text
        assert taken.json()["reason"] == {"code": "identifier_taken", "params": {"value": "K9009"}}
        assert "Insurer" not in taken.json()["detail"]
    # The contact's own number everyone sees: the conflict names it.
    public = await change(api, anna, entered(employer, "K7007"))
    assert public.status_code == 409
    assert public.json()["reason"]["code"] == "identifier_of_contact"
    assert public.json()["reason"]["params"]["contact"] == "Insurer"


def number(
    contact: Contact, kind: str, value: str, source: str, topic: UUID | None = None
) -> dict[str, Any]:
    return {
        "contact_id": str(contact.id),
        "kind": kind,
        "value": value,
        "source": source,
        "topic_id": None if topic is None else str(topic),
    }
