"""`/identifiers/open`: the open identifiers, where one stands, decisions."""

import json

from lekto.adapters.inbound.rest import PREFIX
from lekto.core.domain.document_facts import DocumentFact, FactOrigin, role_of
from lekto.core.domain.identifiers import Identifier, IdentifierKind, IdentifierSource
from lekto.core.domain.labels import grid_layout
from lekto.core.domain.master_data import Contact
from lekto.core.domain.users import User
from lekto.core.services.objects import structure_key, text_key
from tests import builders
from tests.api import auth
from tests.unit.adapters.rest.support import Api

URL = f"{PREFIX}/identifiers/open"
CUSTOMER = (IdentifierKind.CUSTOMER_NUMBER, "20047718")
VAT = (IdentifierKind.VAT_ID, "DE312456789")
TEXT = "Kundennummer 20047718, USt-IdNr. DE312456789"


async def seeded(api: Api, owner: User | None = None) -> Contact:
    owner = owner or await api.user()
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
            await api.container.object_store.put(
                structure_key(document.id),
                json.dumps(grid_layout(TEXT)).encode(),
                content_type="application/json",
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
            "ref": api.container.refs.seal("20047718", context="customer_number"),
            "written": "20047718",
            "source": "learned",
            "contacts": [{"id": str(contact.id), "name": "Stadtwerke"}],
            "person": None,
            "documents": 2,
            "last": builders.NOW.date().isoformat(),
            # Two documents of its contact, at no other: confirm it.
            "recommendation": {
                "action": "confirm",
                "reason": {
                    "code": "recommend_confirm",
                    "params": {"count": 2, "name": "Stadtwerke"},
                    "subject": None,
                    "rule": None,
                    "field": None,
                },
            },
        }
    ]
    assert (page["total"], page["counts"], page["kinds"]) == (
        1,
        {"learned": 1, "unknown": 1, "suggested": 0},
        {"customer_number": 1},
    )
    # The VAT ID has no holder yet (read before it had one): no recommendation.
    assert (page["recommended"], page["to_confirm"]) == (1, 1)
    summary = await api.client.get(f"{URL}/summary", headers=auth(admin))
    assert summary.json() == {"learned": 1, "unknown": 1, "suggested": 0}

    vat = api.container.refs.seal(VAT[1], context="vat_id")
    detail = await api.client.get(f"{URL}/vat_id/{vat}", headers=auth(admin))
    assert detail.status_code == 200
    assert detail.json()["identifier"]["ref"] == vat
    (place, _) = detail.json()["places"]
    assert place["role"] == "contact"
    assert place["excerpt"] == {
        "before": "Kundennummer 20047718, USt-IdNr. ",
        "match": "DE312456789",
        "after": "",
    }
    # Where the pages show it, the fact's own place marked.
    (occurrence,) = place["occurrences"]
    assert occurrence["own"] is True
    (location,) = occurrence["locations"]
    assert location["page"] == 1
    assert round(location["boxes"][0]["x"] * 80) == TEXT.index("DE312456789")
    gone = api.container.refs.seal("DE1", context="vat_id")
    missing = await api.client.get(f"{URL}/vat_id/{gone}", headers=auth(admin))
    assert (missing.status_code, missing.json()["reason"]["code"]) == (404, "identifier_not_open")
    for wrong in (f"customer_number/{vat}", "vat_id/DE312456789"):
        refused = await api.client.get(f"{URL}/{wrong}", headers=auth(admin))
        assert (refused.status_code, refused.json()["reason"]["code"]) == (422, "ref_unknown")


async def test_open_identifiers_are_found_by_words_in_the_body(api: Api) -> None:
    await seeded(api)
    user, admin = await api.user(), await api.admin()
    search = f"{URL}/search"
    assert (await api.client.post(search, json={"q": "x"}, headers=auth(user))).status_code == 403
    found = await api.client.post(
        search, params={"source": "learned"}, json={"q": "2004 7718"}, headers=auth(admin)
    )
    assert found.status_code == 200, found.text
    assert [item["value"] for item in found.json()["items"]] == ["20047718"]
    none = await api.client.post(search, json={"q": "Gaswerke"}, headers=auth(admin))
    assert none.json()["items"] == []
    assert (await api.client.post(search, json={}, headers=auth(admin))).status_code == 422
    # The list takes no words.
    listed = await api.client.get(URL, params={"q": "Gaswerke"}, headers=auth(admin))
    assert listed.json()["total"] == 2


async def test_refs_name_a_value_without_showing_it(api: Api) -> None:
    user = await api.user()
    refs = f"{PREFIX}/identifiers/refs"
    made = await api.client.post(
        refs, json={"kind": "iban", "value": "de89 3704 0044 0532 0130 00"}, headers=auth(user)
    )
    assert made.status_code == 200, made.text
    ref = made.json()["ref"]
    assert made.json() == {"kind": "iban", "value": "DE89370400440532013000", "ref": ref}
    assert "DE89" not in ref
    again = await api.client.post(
        refs, json={"kind": "iban", "value": "DE89370400440532013000"}, headers=auth(user)
    )
    assert again.json()["ref"] == ref
    read = await api.client.get(f"{refs}/iban/{ref}", headers=auth(user))
    assert read.json() == made.json()
    bad = await api.client.post(refs, json={"kind": "iban", "value": "DE00"}, headers=auth(user))
    assert bad.status_code == 422
    other = await api.client.get(f"{refs}/vat_id/{ref}", headers=auth(user))
    assert (other.status_code, other.json()["reason"]["code"]) == (422, "ref_unknown")
    assert (await api.client.get(f"{refs}/iban/{ref}")).status_code == 401


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


async def test_the_recommended_are_confirmed_at_once(api: Api) -> None:
    contact = await seeded(api)
    admin = await api.admin()
    only = await api.client.get(URL, params={"recommended": True}, headers=auth(admin))
    assert [item["value"] for item in only.json()["items"]] == [CUSTOMER[1]]
    done = await api.client.post(f"{URL}/recommended", headers=auth(admin))
    assert done.status_code == 200, done.text
    assert done.json() == [
        {"kind": "customer_number", "value": CUSTOMER[1], "done": True, "reason": None}
    ]
    after = (await api.client.get(URL, headers=auth(admin))).json()
    assert (after["counts"]["learned"], after["to_confirm"]) == (0, 0)
    async with api.container.unit_of_work() as uow:
        stored = await uow.contacts.get(contact.id)
    assert any(item.value == CUSTOMER[1] and item.source.value == "manual"
               for item in stored.identifiers)  # fmt: skip
    user = await api.user()
    refused = await api.client.post(f"{URL}/recommended", headers=auth(user))
    assert refused.status_code == 403


async def test_where_an_identifier_stands_in_the_documents_the_caller_reads(api: Api) -> None:
    """The newest documents with the fact within the caller's reach, each place marked."""
    owner = await api.user()
    await seeded(api, owner)
    places = f"{PREFIX}/identifiers/places"
    customer = api.container.refs.seal(CUSTOMER[1], context="customer_number")
    found = await api.client.get(f"{places}/customer_number/{customer}", headers=auth(owner))
    assert found.status_code == 200, found.text
    listed = found.json()["places"]
    assert len(listed) == 2
    assert listed[0]["excerpt"]["match"] == "20047718"
    assert [item["own"] for item in listed[0]["occurrences"]] == [True]
    # Another user reads none of them; a person's kind is for admins; a broken reference.
    other = await api.user()
    nothing = await api.client.get(f"{places}/customer_number/{customer}", headers=auth(other))
    assert nothing.json() == {"places": []}
    tax = api.container.refs.seal("12345678911", context="tax_id")
    assert (await api.client.get(f"{places}/tax_id/{tax}", headers=auth(other))).status_code == 403
    broken = await api.client.get(f"{places}/vat_id/{customer}", headers=auth(other))
    assert (broken.status_code, broken.json()["reason"]["code"]) == (422, "ref_unknown")
