"""`/identifiers/open`: the open identifiers, where one stands, decisions."""

from lekto.adapters.inbound.rest import PREFIX
from lekto.core.domain.document_facts import DocumentFact, FactOrigin, role_of
from lekto.core.domain.identifiers import Identifier, IdentifierKind, IdentifierSource
from lekto.core.domain.master_data import Contact
from lekto.core.services.objects import text_key
from tests import builders
from tests.api import auth
from tests.unit.adapters.rest.support import Api

URL = f"{PREFIX}/identifiers/open"
CUSTOMER = (IdentifierKind.CUSTOMER_NUMBER, "20047718")
VAT = (IdentifierKind.VAT_ID, "DE312456789")
TEXT = "Kundennummer 20047718, USt-IdNr. DE312456789"


async def seeded(api: Api) -> Contact:
    owner = await api.user()
    contact = Contact.create(name="Stadtwerke", now=builders.NOW)
    contact.set_learned([Identifier(*CUSTOMER, IdentifierSource.LEARNED)])
    async with api.container.unit_of_work() as uow:
        await uow.contacts.add(contact)
        space = await uow.spaces.get_personal(owner.id)
        for _ in range(2):
            document = builders.processed(owner, space)
            document.contact_id = contact.id
            document.mark_confirmed(builders.NOW)
            await uow.documents.add(document)
            await uow.document_facts.replace_found(
                document.id,
                [
                    DocumentFact(
                        kind=kind,
                        value=value,
                        role=role_of(kind),
                        origins=frozenset({FactOrigin.PATTERN}),
                        written=value,
                        position=TEXT.index(value),
                    )
                    for kind, value in (CUSTOMER, VAT)
                ],
            )
            await api.container.object_store.put(
                text_key(document.id), TEXT.encode(), content_type="text/plain"
            )
        await uow.commit()
    return contact


async def test_admins_see_the_open_identifiers(api: Api) -> None:
    contact = await seeded(api)
    user, admin = await api.user(), await api.admin()
    assert (await api.client.get(URL, headers=auth(user))).status_code == 403
    found = await api.client.get(f"{URL}?source=learned", headers=auth(admin))
    assert found.status_code == 200
    page = found.json()
    assert page["items"] == [
        {
            "kind": "customer_number",
            "value": "20047718",
            "written": "20047718",
            "source": "learned",
            "contacts": [{"id": str(contact.id), "name": "Stadtwerke"}],
            "documents": 2,
            "last": builders.NOW.date().isoformat(),
        }
    ]
    assert (page["total"], page["counts"], page["kinds"]) == (
        1,
        {"learned": 1, "unknown": 1},
        {"customer_number": 1},
    )
    summary = await api.client.get(f"{URL}/summary", headers=auth(admin))
    assert summary.json() == {"learned": 1, "unknown": 1}

    detail = await api.client.get(
        f"{URL}/detail", params={"kind": "vat_id", "value": VAT[1]}, headers=auth(admin)
    )
    assert detail.status_code == 200
    (place, _) = detail.json()["places"]
    assert place["role"] == "contact"
    assert place["excerpt"] == {
        "before": "Kundennummer 20047718, USt-IdNr. ",
        "match": "DE312456789",
        "after": "",
    }
    missing = await api.client.get(
        f"{URL}/detail", params={"kind": "vat_id", "value": "DE1"}, headers=auth(admin)
    )
    assert (missing.status_code, missing.json()["reason"]["code"]) == (404, "identifier_not_open")


async def test_decisions_come_back_one_by_one(api: Api) -> None:
    contact = await seeded(api)
    admin = await api.admin()
    decided = await api.client.post(
        f"{URL}/decisions",
        json={
            "decisions": [
                {"kind": "customer_number", "value": "20047718", "action": "confirm"},
                {"kind": "vat_id", "value": "DE999", "action": "reject"},
            ]
        },
        headers=auth(admin),
    )
    assert decided.status_code == 200
    (done, failed) = decided.json()
    assert (done["done"], done["reason"]) == (True, None)
    assert (failed["done"], failed["reason"]["code"]) == (False, "identifier_not_open")
    async with api.container.unit_of_work() as uow:
        stored = await uow.contacts.get(contact.id)
    assert [(item.key, item.source) for item in stored.identifiers] == [
        (CUSTOMER, IdentifierSource.MANUAL)
    ]
    empty = await api.client.post(f"{URL}/decisions", json={"decisions": []}, headers=auth(admin))
    assert empty.status_code == 422
