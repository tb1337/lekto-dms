"""Endpoints for users, master data, drawers and document metadata: they do what they say."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from papiq.adapters.inbound.rest import PREFIX
from papiq.core.services.objects import archive_key
from tests.api import auth
from tests.builders import PASSWORD
from tests.contracts.processing import SAMPLES
from tests.unit.adapters.rest.conftest import Api


async def green_document(api: Api, headers: dict[str, str], drawer: str | None = None) -> str:
    files = {"file": ("Bill 2026.pdf", (SAMPLES / "scan.pdf").read_bytes(), "x/y")}
    data = {} if drawer is None else {"drawer_id": drawer}
    response = await api.client.post(f"{PREFIX}/documents", files=files, data=data, headers=headers)
    assert response.status_code == 202, response.text
    await api.drain()
    return str(response.json()["id"])


async def post(api: Api, path: str, body: Any, headers: dict[str, str]) -> Any:
    response = await api.client.post(f"{PREFIX}{path}", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_metadata_with_master_data_and_fields(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    a, o = auth(admin), auth(owner)
    contact = await post(api, "/contacts", {"name": "ACME Energy"}, a)
    invoice = await post(api, "/document-types", {"name": "Invoice"}, a)
    tag = await post(api, "/tags", {"name": "tax"}, a)
    amount = await post(
        api,
        "/fields",
        {"name": "Amount", "data_type": "amount", "document_type_ids": [invoice["id"]]},
        a,
    )
    paid = await post(api, "/fields", {"name": "Paid", "data_type": "boolean"}, a)
    due = await post(api, "/fields", {"name": "Due", "data_type": "date"}, a)
    kind = await post(
        api, "/fields", {"name": "Kind", "data_type": "choice", "choices": ["a", "b"]}, a
    )
    assert amount["document_type_ids"] == [invoice["id"]]
    document = await green_document(api, o)

    response = await api.client.patch(
        f"{PREFIX}/documents/{document}",
        json={
            "title": "Electricity",
            "contact_id": contact["id"],
            "document_type_id": invoice["id"],
            "tag_ids": [tag["id"]],
            "document_date": "2026-09-30",
            "fields": {
                amount["id"]: {"amount": "84.20", "currency": "EUR"},
                paid["id"]: True,
                due["id"]: "2026-10-15",
                kind["id"]: "b",
            },
        },
        headers=o,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Electricity" and body["access"] == "read_write"
    assert body["contact_id"] == contact["id"] and body["tag_ids"] == [tag["id"]]
    assert body["document_date"] == "2026-09-30"
    assert body["fields"] == {
        amount["id"]: {"amount": "84.20", "currency": "EUR"},
        paid["id"]: True,
        due["id"]: "2026-10-15",
        kind["id"]: "b",
    }

    # Left out stays, null removes.
    response = await api.client.patch(
        f"{PREFIX}/documents/{document}",
        json={"contact_id": None, "fields": {paid["id"]: None}},
        headers=o,
    )
    body = response.json()
    assert body["contact_id"] is None and body["title"] == "Electricity"
    assert paid["id"] not in body["fields"] and amount["id"] in body["fields"]

    for bad in (
        {"fields": {kind["id"]: "c"}},
        {"fields": {due["id"]: "tomorrow"}},
        {"fields": {amount["id"]: {"amount": "x", "currency": "EUR"}}},
        {"title": None},
        {"unknown": 1},
    ):
        response = await api.client.patch(f"{PREFIX}/documents/{document}", json=bad, headers=o)
        assert response.status_code == 422, (bad, response.text)
    response = await api.client.patch(
        f"{PREFIX}/documents/{document}", json={"tag_ids": [str(UUID(int=7))]}, headers=o
    )
    assert response.status_code == 404

    # In use: not deleted.
    used = await api.client.delete(f"{PREFIX}/tags/{tag['id']}", headers=a)
    assert used.status_code == 409


async def test_listing_filters_and_pages(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    tag = await post(api, "/tags", {"name": "tax"}, auth(admin))
    ids = []
    for number in range(3):
        files = {"file": (f"{number}.pdf", _pdf(number), "x/y")}
        response = await api.client.post(f"{PREFIX}/documents", files=files, headers=auth(owner))
        ids.append(response.json()["id"])
    await api.drain()
    await api.client.patch(
        f"{PREFIX}/documents/{ids[1]}", json={"tag_ids": [tag["id"]]}, headers=auth(owner)
    )
    page = (await api.client.get(f"{PREFIX}/documents?limit=2", headers=auth(owner))).json()
    assert [item["id"] for item in page["items"]] == ids[::-1][:2]
    rest = await api.client.get(
        f"{PREFIX}/documents", params={"cursor": page["next_cursor"]}, headers=auth(owner)
    )
    assert [item["id"] for item in rest.json()["items"]] == [ids[0]]
    assert rest.json()["next_cursor"] is None
    tagged = await api.client.get(
        f"{PREFIX}/documents", params={"tag_id": tag["id"], "lane": "green"}, headers=auth(owner)
    )
    assert [item["id"] for item in tagged.json()["items"]] == [ids[1]]
    for bad in ({"cursor": "!!"}, {"limit": 0}, {"limit": 201}, {"lane": "blue"}):
        response = await api.client.get(f"{PREFIX}/documents", params=bad, headers=auth(owner))
        assert response.status_code == 422, bad


async def test_listing_sorts_by_date_and_title_and_filters_by_field(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    definition = {"name": "Note", "data_type": "text", "document_type_ids": None}
    note = await post(api, "/fields", definition, auth(admin))
    ids = []
    for number in range(3):
        files = {"file": (f"{number}.pdf", _pdf(10 + number), "x/y")}
        response = await api.client.post(f"{PREFIX}/documents", files=files, headers=auth(owner))
        ids.append(response.json()["id"])
    await api.drain()
    changes = [
        {"title": "Zahnarzt", "document_date": "2026-03-01", "fields": {note["id"]: "x"}},
        {"title": "arzt", "document_date": "2025-01-01"},
        {"title": "Ärztebrief", "document_date": None},
    ]
    for id, change in zip(ids, changes, strict=True):
        response = await api.client.patch(
            f"{PREFIX}/documents/{id}", json=change, headers=auth(owner)
        )
        assert response.status_code == 200, response.text

    async def listed(**params: Any) -> list[str]:
        found: list[str] = []
        cursor = None
        while True:
            query = {**params, "limit": 1, **({"cursor": cursor} if cursor else {})}
            page = await api.client.get(f"{PREFIX}/documents", params=query, headers=auth(owner))
            assert page.status_code == 200, page.text
            found += [item["id"] for item in page.json()["items"]]
            if (cursor := page.json()["next_cursor"]) is None:
                return found

    # Newest document date first, a page at a time; without a date last.
    assert await listed(sort="-document_date") == [ids[0], ids[1], ids[2]]
    assert await listed(sort="document_date") == [ids[1], ids[0], ids[2]]
    # By title, case and accents aside.
    assert await listed(sort="title") == [ids[1], ids[2], ids[0]]
    assert await listed(field_id=note["id"]) == [ids[0]]
    bad = await api.client.get(f"{PREFIX}/documents", params={"sort": "size"}, headers=auth(owner))
    assert bad.status_code == 422


async def test_master_data_with_their_document_counts(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    contact = await post(api, "/contacts", {"name": "ACME"}, auth(admin))
    unused = await post(api, "/contacts", {"name": "Nobody"}, auth(admin))
    definition = {"name": "Note", "data_type": "text", "document_type_ids": None}
    note = await post(api, "/fields", definition, auth(admin))
    document = await green_document(api, auth(owner))
    changed = await api.client.patch(
        f"{PREFIX}/documents/{document}",
        json={"contact_id": contact["id"], "fields": {note["id"]: "x"}},
        headers=auth(owner),
    )
    assert changed.status_code == 200, changed.text

    async def counts(path: str, headers: dict[str, str], **params: Any) -> dict[str, Any]:
        response = await api.client.get(f"{PREFIX}{path}", params=params, headers=headers)
        assert response.status_code == 200, response.text
        return {item["id"]: item["document_count"] for item in response.json()}

    # Only when asked for; within the caller's reach, an admin's reach or every document.
    assert set((await counts("/contacts", auth(owner))).values()) == {None}
    mine = await counts("/contacts", auth(owner), document_counts=True)
    assert (mine[contact["id"]], mine[unused["id"]]) == (1, 0)
    assert (await counts("/contacts", auth(admin), document_counts=True))[contact["id"]] == 0
    every = await counts("/contacts", auth(admin), document_counts=True, all_users=True)
    assert every[contact["id"]] == 1
    assert (await counts("/fields", auth(owner), document_counts=True))[note["id"]] == 1
    denied = await api.client.get(
        f"{PREFIX}/tags", params={"document_counts": True, "all_users": True}, headers=auth(owner)
    )
    assert denied.status_code == 403


async def test_the_fields_of_a_document_type_from_the_type(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    invoice = await post(api, "/document-types", {"name": "Invoice"}, auth(admin))
    letter = await post(api, "/document-types", {"name": "Letter"}, auth(admin))

    def field(name: str, types: list[str] | None) -> dict[str, Any]:
        return {"name": name, "data_type": "text", "document_type_ids": types}

    amount = await post(api, "/fields", field("Amount", [letter["id"]]), auth(admin))
    number = await post(api, "/fields", field("Number", [invoice["id"], letter["id"]]), auth(admin))
    only = await post(api, "/fields", field("Only", [invoice["id"]]), auth(admin))
    global_ = await post(api, "/fields", field("Note", None), auth(admin))
    url = f"{PREFIX}/document-types/{invoice['id']}/fields"

    async def assign(body: list[dict[str, Any]], headers: dict[str, str]) -> Any:
        return await api.client.put(url, json={"fields": body}, headers=headers)

    # Amount comes in (required), Number stays optional, Only stays as it is.
    response = await assign(
        [
            {"field_id": amount["id"], "required": True},
            {"field_id": number["id"]},
            {"field_id": only["id"]},
        ],
        auth(admin),
    )
    assert response.status_code == 200, response.text
    by_name = {item["name"]: item for item in response.json()}
    assert set(by_name) == {"Amount", "Number", "Only"}
    assert invoice["id"] in by_name["Amount"]["required_document_type_ids"]
    assert set(by_name["Amount"]["document_type_ids"]) == {invoice["id"], letter["id"]}
    # Number is taken off: it stays for the letter.
    response = await assign(
        [{"field_id": amount["id"], "required": True}, {"field_id": only["id"]}], auth(admin)
    )
    assert response.status_code == 200, response.text
    assert {item["name"] for item in response.json()} == {"Amount", "Only"}
    # Only the invoice has Only; a global field belongs to every type; admins only.
    assert (await assign([{"field_id": amount["id"]}], auth(admin))).status_code == 422
    assert (await assign([{"field_id": global_["id"]}], auth(admin))).status_code == 422
    assert (await assign([], auth(owner))).status_code == 403
    # A document of the invoice with a value for Amount keeps it there.
    document = await green_document(api, auth(owner))
    changed = await api.client.patch(
        f"{PREFIX}/documents/{document}",
        json={"document_type_id": invoice["id"], "fields": {amount["id"]: "12"}},
        headers=auth(owner),
    )
    assert changed.status_code == 200, changed.text
    assert (await assign([{"field_id": only["id"]}], auth(admin))).status_code == 409


def _pdf(number: int) -> bytes:
    return (SAMPLES / "scan.pdf").read_bytes().rstrip() + f"\n%{number}\n%%EOF\n".encode()


async def test_downloads(api: Api) -> None:
    owner = await api.user()
    document = await green_document(api, auth(owner))
    original = await api.client.get(f"{PREFIX}/documents/{document}/original", headers=auth(owner))
    assert original.status_code == 200
    assert original.content == (SAMPLES / "scan.pdf").read_bytes()
    assert original.headers["content-type"] == "application/pdf"
    assert original.headers["content-disposition"].startswith("attachment;")
    assert "Bill%202026.pdf" in original.headers["content-disposition"]
    assert original.headers["x-content-type-options"] == "nosniff"
    assert original.headers["content-security-policy"].startswith("sandbox")
    await api.container.object_store.delete(archive_key(UUID(document)))  # type: ignore[arg-type]
    missing = await api.client.get(f"{PREFIX}/documents/{document}/archive", headers=auth(owner))
    assert missing.status_code == 404
    await api.container.object_store.put(
        archive_key(UUID(document)),  # type: ignore[arg-type]
        b"%PDF-1.7 archive",
        content_type="application/pdf",
    )
    archive = await api.client.get(f"{PREFIX}/documents/{document}/archive", headers=auth(owner))
    assert archive.content == b"%PDF-1.7 archive"
    assert archive.headers["content-disposition"].startswith("inline;")


async def test_moving_and_deleting(api: Api) -> None:
    owner = await api.user()
    document = await green_document(api, auth(owner))
    target = await post(api, "/drawers", {"name": "Archive"}, auth(owner))
    moved = await api.client.post(
        f"{PREFIX}/documents/{document}/move", json={"drawer_id": target["id"]}, headers=auth(owner)
    )
    assert moved.status_code == 204
    details = await api.client.get(f"{PREFIX}/documents/{document}", headers=auth(owner))
    assert details.json()["drawer_id"] == target["id"]
    deleted = await api.client.delete(f"{PREFIX}/documents/{document}", headers=auth(owner))
    assert deleted.status_code == 204
    gone = await api.client.get(f"{PREFIX}/documents/{document}", headers=auth(owner))
    assert gone.status_code == 404


async def test_drawers_and_shares(api: Api) -> None:
    owner, friend = await api.user(), await api.user("friend")
    drawer = await post(api, "/drawers", {"name": "Household"}, auth(owner))
    assert drawer["access"] == "read_write" and drawer["shares"] == []
    url = f"{PREFIX}/drawers/{drawer['id']}"
    shared = await api.client.put(
        f"{url}/shares/{friend.id}", json={"level": "read"}, headers=auth(owner)
    )
    assert shared.json()["shares"] == [{"user_id": str(friend.id), "level": "read"}]
    seen = (await api.client.get(f"{PREFIX}/drawers", headers=auth(friend))).json()
    assert {d["name"] for d in seen} == {"Default", "Household"}
    duplicate = await api.client.post(
        f"{PREFIX}/drawers", json={"name": "household"}, headers=auth(owner)
    )
    assert duplicate.status_code == 409
    default = next(d for d in seen if d["is_default"])
    cannot = await api.client.put(
        f"{PREFIX}/drawers/{default['id']}/shares/{owner.id}",
        json={"level": "read"},
        headers=auth(friend),
    )
    assert cannot.status_code == 422
    unshared = await api.client.delete(f"{url}/shares/{friend.id}", headers=auth(owner))
    assert unshared.json()["shares"] == []
    assert (await api.client.get(url, headers=auth(friend))).status_code == 404
    assert (await api.client.delete(url, headers=auth(owner))).status_code == 204


async def test_user_management(api: Api) -> None:
    admin = await api.admin("root")
    async with api.sign_in(admin) as session:
        client, csrf = session.client, session.headers
        response = await client.post(
            f"{PREFIX}/users", json={"username": "carol", "password": PASSWORD}, headers=csrf
        )
        assert response.status_code == 201, response.text
        created = response.json()
        assert created["role"] == "user" and created["active"] is True
        login = await api.client.post(
            f"{PREFIX}/auth/login", json={"username": "carol", "password": PASSWORD}
        )
        assert login.status_code == 200
        url = f"{PREFIX}/users/{created['id']}"
        promoted = await client.patch(url, json={"role": "admin"}, headers=csrf)
        assert promoted.json()["role"] == "admin"
        weak = await client.post(f"{url}/password", json={"password": "short"}, headers=csrf)
        assert weak.status_code == 422
        reset = await client.post(
            f"{url}/password", json={"password": "a brand new passphrase"}, headers=csrf
        )
        assert reset.status_code == 204
        own = await client.post(
            f"{PREFIX}/users/{admin.id}/password",
            json={"password": "a brand new passphrase"},
            headers=csrf,
        )
        assert own.status_code == 403  # the own password: POST /auth/password
        own_totp = await client.delete(f"{PREFIX}/users/{admin.id}/totp", headers=csrf)
        assert own_totp.status_code == 403
        last = await client.patch(
            f"{PREFIX}/users/{admin.id}", json={"active": False}, headers=csrf
        )
        assert last.status_code == 200  # carol is an active admin now
        taken = await client.post(f"{PREFIX}/users", json={"username": "CAROL"}, headers=csrf)
        assert taken.status_code == 401  # the admin just deactivated themselves


async def test_the_last_admin_stays(api: Api) -> None:
    admin = await api.admin("root")
    async with api.sign_in(admin) as session:  # a token changes no role or admin state
        for body in ({"role": "user"}, {"active": False}):
            response = await session.client.patch(
                f"{PREFIX}/users/{admin.id}", json=body, headers=session.headers
            )
            assert response.status_code == 409, response.text
    response = await api.client.delete(f"{PREFIX}/users/{admin.id}", headers=auth(admin))
    assert response.status_code == 409


async def test_secrets_do_not_come_back(api: Api) -> None:
    admin = await api.admin()
    async with api.sign_in(admin) as session:
        response = await session.client.post(
            f"{PREFIX}/users",
            json={"username": "dave", "password": "x"},
            headers=session.headers,
        )
    assert response.status_code == 422
    assert '"x"' not in response.text and "'x'" not in response.text
    response = await api.client.post(
        f"{PREFIX}/auth/login", json={"username": "dave", "password": 12345678901234}
    )
    assert response.status_code == 422
    assert "12345678901234" not in response.text


async def test_field_definitions_change(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    a = auth(admin)
    kind = await post(
        api, "/fields", {"name": "Kind", "data_type": "choice", "choices": ["a", "b"]}, a
    )
    invoice = await post(api, "/document-types", {"name": "Invoice"}, a)
    document = await green_document(api, auth(owner))
    await api.client.patch(
        f"{PREFIX}/documents/{document}",
        json={"fields": {kind["id"]: "a"}},
        headers=auth(owner),
    )
    url = f"{PREFIX}/fields/{kind['id']}"
    changed = await api.client.patch(url, json={"name": "Sort", "choices": ["a", "c"]}, headers=a)
    assert changed.status_code == 200, changed.text
    assert changed.json()["choices"] == ["a", "c"] and changed.json()["name"] == "Sort"
    in_use = await api.client.patch(url, json={"choices": ["c"]}, headers=a)
    assert in_use.status_code == 409
    narrower = await api.client.patch(url, json={"document_type_ids": [invoice["id"]]}, headers=a)
    assert narrower.status_code == 409  # the document has no type
    untouched = await api.client.patch(url, json={"name": "Sort"}, headers=a)
    assert untouched.json()["document_type_ids"] is None
    bad_changes: list[dict[str, Any]] = [{"data_type": "text"}, {"choices": []}]
    for bad in bad_changes:
        assert (await api.client.patch(url, json=bad, headers=a)).status_code == 422
    denied = await api.client.patch(url, json={"name": "X"}, headers=auth(owner))
    assert denied.status_code == 403


# --- M4-04: request sizes ----------------------------------------------------------


async def test_contact_identifiers(api: Api) -> None:
    a = auth(await api.admin())
    iban = {"kind": "iban", "value": "de89 3704 0044 0532 0130 00"}
    contact = await post(api, "/contacts", {"name": "Stadtwerke", "identifiers": [iban]}, a)
    assert contact["identifiers"] == [
        {"kind": "iban", "value": "DE89370400440532013000", "source": "manual"}
    ]
    path = f"{PREFIX}/contacts/{contact['id']}"
    domain = {"kind": "email_domain", "value": "www.stadtwerke.example"}
    response = await api.client.patch(path, json={"rejected_identifiers": [domain]}, headers=a)
    assert [item["source"] for item in response.json()["identifiers"]] == ["manual", "rejected"]
    other = await post(api, "/contacts", {"name": "Bank"}, a)
    response = await api.client.patch(
        f"{PREFIX}/contacts/{other['id']}", json={"identifiers": [iban]}, headers=a
    )
    assert response.status_code == 409
    for bad in (
        {"identifiers": [{"kind": "iban", "value": "DE00 1234"}]},
        {"identifiers": [{"kind": "phone", "value": "0621 1234"}]},
        {"identifiers": [{"kind": "email_domain", "value": "gmail.com"}]},
    ):
        assert (await api.client.patch(path, json=bad, headers=a)).status_code == 422


async def test_required_fields_and_title_patterns(api: Api) -> None:
    a = auth(await api.admin())
    payslip = await post(
        api,
        "/document-types",
        {"name": "Lohn", "title_pattern": "{{ document_date | date: '%Y' }}"},
        a,
    )
    assert payslip["title_pattern"] == "{{ document_date | date: '%Y' }}"
    field = await post(
        api,
        "/fields",
        {
            "name": "Zeitraum",
            "data_type": "text",
            "document_type_ids": [payslip["id"]],
            "required_document_type_ids": [payslip["id"]],
        },
        a,
    )
    assert (field["required"], field["required_document_type_ids"]) == (False, [payslip["id"]])
    path = f"{PREFIX}/fields/{field['id']}"
    response = await api.client.patch(path, json={"required_document_type_ids": []}, headers=a)
    assert response.json()["required_document_type_ids"] == []
    response = await api.client.patch(path, json={"required": True}, headers=a)
    assert response.status_code == 422  # a typed field is required per type
    type_path = f"{PREFIX}/document-types/{payslip['id']}"
    response = await api.client.patch(type_path, json={"title_pattern": "{{ amount }}"}, headers=a)
    assert response.status_code == 422
    response = await api.client.patch(type_path, json={"title_pattern": None}, headers=a)
    assert response.json()["title_pattern"] is None


async def test_a_field_tells_the_model_what_belongs_in_it(api: Api) -> None:
    a = auth(await api.admin())
    hint = "Gesamtbrutto des Monats, nicht das Grundgehalt"
    field = await post(
        api, "/fields", {"name": "LA_Brutto", "data_type": "amount", "description": hint}, a
    )
    assert field["description"] == hint
    path = f"{PREFIX}/fields/{field['id']}"
    response = await api.client.patch(path, json={"name": "LA_Gesamtbrutto"}, headers=a)
    assert response.json()["description"] == hint  # left out: kept
    response = await api.client.patch(path, json={"description": "x" * 301}, headers=a)
    assert response.status_code == 422
    response = await api.client.patch(path, json={"description": None}, headers=a)
    assert response.json()["description"] is None
    plain = await post(api, "/fields", {"name": "Notiz", "data_type": "text"}, a)
    assert plain["description"] is None


async def test_contact_aliases_and_type_descriptions(api: Api) -> None:
    a = auth(await api.admin())
    contact = await post(api, "/contacts", {"name": "Nord", "aliases": ["Nord KV"]}, a)
    assert contact["aliases"] == ["Nord KV"]
    tag = await post(api, "/tags", {"name": "tax"}, a)
    assert "aliases" not in tag and "description" not in tag
    path = f"{PREFIX}/contacts/{contact['id']}"
    response = await api.client.patch(path, json={"name": "Nord Gruppe"}, headers=a)
    assert response.json()["aliases"] == ["Nord KV"]  # left out: kept
    response = await api.client.patch(path, json={"aliases": ["Nord AG", "nord ag"]}, headers=a)
    assert (response.json()["name"], response.json()["aliases"]) == (
        "Nord Gruppe",
        ["Nord AG"],
    )
    other = await post(api, "/contacts", {"name": "Muster"}, a)
    response = await api.client.post(
        f"{PREFIX}/contacts", json={"name": "Other", "aliases": ["Nord Gruppe"]}, headers=a
    )
    assert response.status_code == 409
    response = await api.client.patch(
        f"{PREFIX}/contacts/{other['id']}", json={"aliases": ["Muster"]}, headers=a
    )
    assert response.status_code == 422  # its own name

    kind = await post(api, "/document-types", {"name": "Pay slip", "description": "Payroll"}, a)
    assert kind["description"] == "Payroll"
    path = f"{PREFIX}/document-types/{kind['id']}"
    response = await api.client.patch(path, json={"name": "Payslip"}, headers=a)
    assert response.json()["description"] == "Payroll"
    response = await api.client.patch(path, json={"description": None}, headers=a)
    assert response.json()["description"] is None
    response = await api.client.patch(path, json={"description": "x" * 301}, headers=a)
    assert response.status_code == 422
    listed = (await api.client.get(f"{PREFIX}/contacts", headers=a)).json()
    assert {item["name"]: item["aliases"] for item in listed} == {
        "Muster": [],
        "Nord Gruppe": ["Nord AG"],
    }


async def test_json_bodies_are_bounded(api: Api) -> None:
    """M4-04: only multipart uploads have a size limit (`PAPIQ_UPLOAD_MAX_SIZE`). A JSON body of
    any size is read into memory before validation, also at the public sign-in."""
    huge = '{"username": "' + "a" * (16 * 1024 * 1024) + '", "password": "x"}'
    response = await api.client.post(
        f"{PREFIX}/auth/login", content=huge, headers={"content-type": "application/json"}
    )
    assert response.status_code == 413, response.status_code


async def test_bodies_without_length_are_bounded_while_read(api: Api) -> None:
    user = await api.user()
    sent = 0

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal sent
        yield b'{"name": "'
        for _ in range(64):
            sent += 64 * 1024
            yield b"a" * (64 * 1024)
        yield b'"}'

    response = await api.client.post(
        f"{PREFIX}/drawers",
        content=chunks(),
        headers={**auth(user), "content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "the request body is larger than 1048576 bytes"


async def test_bodies_below_the_limit_pass(api: Api) -> None:
    user = await api.user()
    name = "a" * 200
    response = await api.client.post(f"{PREFIX}/drawers", json={"name": name}, headers=auth(user))
    assert response.status_code == 201
