"""Profiles over HTTP: display names, private data, identifiers of persons, and the persons a
document names."""

import dataclasses
from collections.abc import AsyncIterator
from uuid import UUID

import httpx2
import pytest

from lekto.adapters.inbound.rest import PREFIX
from lekto.adapters.outbound.memory import FakeParser, ManualClock
from lekto.composition.container import build_memory_container, build_services
from lekto.core.domain.identifiers import Identifier, IdentifierKind, IdentifierSource
from lekto.core.domain.ids import DocumentId, UserId
from lekto.core.domain.labels import grid_layout
from lekto.core.domain.pipeline import Node
from lekto.core.domain.spaces import SpaceRole
from tests import builders
from tests.api import auth
from tests.person_numbers import tax_id
from tests.unit.adapters.rest.support import Api, make_app, upload

TAX_ID = tax_id()
TEXT = f"""\
Finanzamt Musterstadt
Frau Anna Example
Steuer-ID {TAX_ID[:2]} {TAX_ID[2:5]} {TAX_ID[5:8]} {TAX_ID[8:]}
Kundennummer K-4711
"""


@pytest.fixture
async def api() -> AsyncIterator[Api]:
    clock = ManualClock(builders.NOW)
    container = dataclasses.replace(
        build_memory_container(clock), parser=FakeParser(TEXT, grid_layout(TEXT))
    )
    services = build_services(container)
    builders.skip_classification(services.pipeline)
    app = make_app(container, services)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://lekto") as client:
        yield Api(container, services, app, client, clock)


async def patch(api: Api, path: str, body: object, headers: dict[str, str]) -> httpx2.Response:
    return await api.client.patch(f"{PREFIX}{path}", json=body, headers=headers)


async def get(api: Api, path: str, headers: dict[str, str]) -> httpx2.Response:
    return await api.client.get(f"{PREFIX}{path}", headers=headers)


async def test_the_own_profile_and_the_display_name_others_see(api: Api) -> None:
    anna, bob = await api.user("anna"), await api.user("bob")
    empty = await get(api, "/auth/me/profile", auth(anna))
    assert empty.status_code == 200, empty.text
    assert empty.json() == {
        "user_id": str(anna.id),
        "display_name": None,
        "aliases": [],
        "birth_date": None,
        "email": None,
        "identifiers": [],
    }
    body = {
        "display_name": "Anna Example",
        "aliases": ["Anna Sample"],
        "birth_date": "1980-06-15",
        "email": "Anna@Mail.Example",
        "identifiers": [{"kind": "tax_id", "value": TAX_ID}],
    }
    changed = await patch(api, "/auth/me/profile", body, auth(anna))
    assert changed.status_code == 200, changed.text
    assert changed.json()["email"] == "anna@mail.example"
    assert changed.json()["identifiers"] == [{"kind": "tax_id", "value": TAX_ID}]
    # Only what is given changes.
    kept = await patch(api, "/auth/me/profile", {"birth_date": None}, auth(anna))
    assert kept.json()["aliases"] == ["Anna Sample"]
    assert kept.json()["birth_date"] is None

    users = (await get(api, "/users", auth(bob))).json()
    listed = next(item for item in users if item["id"] == str(anna.id))
    assert listed["display_name"] == "Anna Example"
    assert "aliases" not in listed and "email" not in listed
    me = (await get(api, "/auth/me", auth(anna))).json()
    assert me["user"]["display_name"] == "Anna Example"


async def test_only_the_user_and_admins_see_a_profile(api: Api) -> None:
    anna, bob, admin = await api.user("anna"), await api.user("bob"), await api.admin()
    path = f"/users/{anna.id}/profile"
    assert (await get(api, path, auth(bob))).status_code == 403
    assert (await patch(api, path, {"display_name": "X"}, auth(bob))).status_code == 403
    assert (await get(api, path, auth(anna))).status_code == 200
    changed = await patch(api, path, {"display_name": "Anna Example"}, auth(admin))
    assert changed.status_code == 200, changed.text
    assert (await get(api, path, auth(admin))).json()["display_name"] == "Anna Example"
    assert (await get(api, f"/users/{UUID(int=1)}/profile", auth(admin))).status_code == 404


async def test_names_are_unique_across_users(api: Api) -> None:
    anna, bob = await api.user("anna"), await api.user("bob")
    await patch(api, "/auth/me/profile", {"display_name": "Anna", "aliases": ["Ann"]}, auth(anna))
    for body in ({"display_name": "anna"}, {"aliases": ["ANN"]}, {"display_name": "Ann"}):
        taken = await patch(api, "/auth/me/profile", body, auth(bob))
        assert taken.status_code == 409, body
    twice = await patch(
        api, "/auth/me/profile", {"display_name": "Bob", "aliases": ["bob"]}, auth(bob)
    )
    assert twice.status_code == 422
    admin = await api.admin()
    created = await api.client.post(
        f"{PREFIX}/users", json={"username": "carla", "display_name": "Ann"}, headers=auth(admin)
    )
    assert created.status_code == 409
    created = await api.client.post(
        f"{PREFIX}/users", json={"username": "carla", "display_name": "Carla"}, headers=auth(admin)
    )
    assert created.status_code == 201, created.text
    assert created.json()["display_name"] == "Carla"


async def test_identifiers_of_persons_and_of_contacts(api: Api) -> None:
    anna, admin = await api.user("anna"), await api.admin()
    wrong = await patch(
        api,
        "/auth/me/profile",
        {"identifiers": [{"kind": "vat_id", "value": "DE123456789"}]},
        auth(anna),
    )
    assert wrong.status_code == 422
    invalid = await patch(
        api, "/auth/me/profile", {"identifiers": [{"kind": "tax_id", "value": "1"}]}, auth(anna)
    )
    assert invalid.status_code == 422
    future = await patch(api, "/auth/me/profile", {"birth_date": "2999-01-01"}, auth(anna))
    assert future.status_code == 422

    iban = "DE89370400440532013000"
    bank = await api.services.master_data.create_contact(
        admin.id, "Bank", identifiers=[Identifier.parse(IdentifierKind.IBAN, iban)]
    )
    taken = await patch(
        api, "/auth/me/profile", {"identifiers": [{"kind": "iban", "value": iban}]}, auth(anna)
    )
    assert taken.status_code == 409
    assert "Bank" in taken.json()["detail"]
    # A learned one gives way: the person's own number was learned as the contact's.
    async with api.container.unit_of_work() as uow:
        contact = await uow.contacts.get(bank.id)
        contact.identifiers = [Identifier(IdentifierKind.IBAN, iban, IdentifierSource.LEARNED)]
        await uow.contacts.update(contact)
        await uow.commit()
    mine = await patch(
        api, "/auth/me/profile", {"identifiers": [{"kind": "iban", "value": iban}]}, auth(anna)
    )
    assert mine.status_code == 200, mine.text
    contact_out = (await get(api, f"/contacts/{bank.id}", auth(admin))).json()
    assert contact_out["identifiers"] == []
    # A contact cannot take a person's number.
    refused = await api.client.post(
        f"{PREFIX}/contacts/{bank.id}/identifiers",
        json={"kind": "iban", "value": iban},
        headers=auth(admin),
    )
    assert refused.status_code == 409
    # A contact's customer number names the user it belongs to.
    named = await api.client.post(
        f"{PREFIX}/contacts/{bank.id}/identifiers",
        json={"kind": "customer_number", "value": "K-4711", "user_id": str(anna.id)},
        headers=auth(admin),
    )
    assert named.status_code == 200, named.text
    assert named.json()["identifiers"][0]["user_id"] == str(anna.id)
    unknown = await api.client.post(
        f"{PREFIX}/contacts/{bank.id}/identifiers",
        json={"kind": "customer_number", "value": "K-4712", "user_id": str(UUID(int=1))},
        headers=auth(admin),
    )
    assert unknown.status_code == 404
    personal_kind = await api.client.post(
        f"{PREFIX}/contacts/{bank.id}/identifiers",
        json={"kind": "tax_id", "value": TAX_ID},
        headers=auth(admin),
    )
    assert personal_kind.status_code == 422


async def test_the_persons_a_document_names(api: Api) -> None:
    anna, reader, admin = await api.user("anna"), await api.user("reader"), await api.admin()
    await patch(
        api,
        "/auth/me/profile",
        {"display_name": "Anna Example", "identifiers": [{"kind": "tax_id", "value": TAX_ID}]},
        auth(anna),
    )
    shared = await api.services.spaces.create(anna.id, "Shared")
    await api.services.spaces.set_member(anna.id, shared.id, reader.id, SpaceRole.READ)
    document = await upload(api, auth(anna), space=str(shared.id))

    facts = (await get(api, f"/documents/{document}/facts", auth(anna))).json()
    (person,) = facts["persons"]
    assert person["user_id"] == str(anna.id)
    assert person["name"] == "Anna Example"
    assert person["strength"] == "hard"
    assert person["evidence"] == ["tax_id", "name"]
    assert person["spans"]
    # Her tax ID is no unknown identifier, the customer number is.
    assert [item["kind"] for item in facts["identifiers"]] == ["customer_number"]
    assert (await get(api, f"/documents/{document}/facts", auth(admin))).json()["persons"]
    read = await get(api, f"/documents/{document}/facts", auth(reader))
    assert read.status_code == 200, read.text
    assert read.json()["persons"] is None

    # The facts signal keeps ids and kinds for the judge, never the values.
    async with api.container.unit_of_work() as uow:
        log = await uow.processing_log.list_for(DocumentId(UUID(document)))
    (output,) = [run.result.output for run in log if run.node is Node.SIGNAL_FACTS]
    assert output["persons"] == [
        {"user_id": str(anna.id), "strength": "hard", "evidence": ["tax_id", "name"]}
    ]
    assert TAX_ID not in str(output)


async def test_a_deleted_user_takes_their_profile_along(api: Api) -> None:
    anna, admin = await api.user("anna"), await api.admin()
    await patch(api, "/auth/me/profile", {"aliases": ["Anna Sample"]}, auth(anna))
    bank = await api.services.master_data.create_contact(
        admin.id,
        "Bank",
        identifiers=[
            Identifier.parse(IdentifierKind.CUSTOMER_NUMBER, "K-4711", user_id=UserId(anna.id))
        ],
    )
    deleted = await api.client.delete(f"{PREFIX}/users/{anna.id}", headers=auth(admin))
    assert deleted.status_code == 204, deleted.text
    async with api.container.unit_of_work() as uow:
        assert await uow.profiles.find(anna.id) is None
        contact = await uow.contacts.get(bank.id)
    assert contact.identifiers[0].user_id is None
    # The alias is free again.
    bob = await api.user("bob")
    reused = await patch(api, "/auth/me/profile", {"display_name": "Anna Sample"}, auth(bob))
    assert reused.status_code == 200, reused.text
