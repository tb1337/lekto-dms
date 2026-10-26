"""Endpoints for users, master data, spaces and document metadata: they do what they say."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from lekto.adapters.inbound.rest import PREFIX
from lekto.core.domain.ids import DocumentId, new_id
from lekto.core.domain.users import Role
from lekto.core.services.objects import archive_key
from tests.api import auth
from tests.builders import PASSWORD, SAMPLES
from tests.unit.adapters.rest.support import Api, post, unique_pdf, upload


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
    document = await upload(api, o)

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
    assert body["title"] == "Electricity" and body["access"] == "edit"
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
        content = unique_pdf(str(number))
        ids.append(
            await upload(api, auth(owner), content=content, filename=f"{number}.pdf", drain=False)
        )
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
    # Several contacts: documents of one of them.
    first, second = [
        await post(api, "/contacts", {"name": name}, auth(admin)) for name in ("Nord", "Süd")
    ]
    for document, contact in ((ids[0], first), (ids[2], second)):
        await api.client.patch(
            f"{PREFIX}/documents/{document}",
            json={"contact_id": contact["id"]},
            headers=auth(owner),
        )
    either = await api.client.get(
        f"{PREFIX}/documents",
        params=[("contact_id", first["id"]), ("contact_id", second["id"])],
        headers=auth(owner),
    )
    assert {item["id"] for item in either.json()["items"]} == {ids[0], ids[2]}
    for bad in ({"cursor": "!!"}, {"limit": 0}, {"limit": 201}, {"lane": "blue"}):
        response = await api.client.get(f"{PREFIX}/documents", params=bad, headers=auth(owner))
        assert response.status_code == 422, bad


async def test_listing_sorts_by_date_title_and_field_and_filters_by_field(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    definition = {"name": "Note", "data_type": "text", "document_type_ids": None}
    note = await post(api, "/fields", definition, auth(admin))
    due_field = {"name": "Due", "data_type": "date", "document_type_ids": None}
    due = await post(api, "/fields", due_field, auth(admin))
    ids = []
    for number in range(3):
        content = unique_pdf(str(10 + number))
        ids.append(
            await upload(api, auth(owner), content=content, filename=f"{number}.pdf", drain=False)
        )
    await api.drain()
    changes = [
        {
            "title": "Zahnarzt",
            "document_date": "2026-03-01",
            "fields": {note["id"]: "x", due["id"]: "2026-12-01"},
        },
        {"title": "arzt", "document_date": "2025-01-01", "fields": {due["id"]: "2026-11-01"}},
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
    # By the value of a field; without one last.
    assert await listed(sort="field", sort_field_id=due["id"]) == [ids[1], ids[0], ids[2]]
    assert await listed(sort="-field", sort_field_id=due["id"]) == [ids[0], ids[1], ids[2]]
    # Dated within a period, both days included; either end may stay open.
    year = {"document_date_from": "2026-01-01", "document_date_to": "2026-12-31"}
    assert await listed(**year) == [ids[0]]
    assert await listed(document_date_to="2025-01-01") == [ids[1]]
    assert await listed(document_date_from="2025-01-01", sort="document_date") == ids[1::-1]
    for bad_params in (
        {"sort": "size"},
        {"sort": "field"},
        {"sort": "title", "sort_field_id": due["id"]},
        {"sort": "field", "sort_field_id": note["id"]},  # text does not sort
        {"sort": "field", "sort_field_id": str(new_id())},
        {"document_date_from": "2026-02-01", "document_date_to": "2026-01-01"},
        {"document_date_from": "2026-02-30"},
    ):
        bad = await api.client.get(f"{PREFIX}/documents", params=bad_params, headers=auth(owner))
        assert bad.status_code == 422, bad_params
    # The search index holds no field values.
    search = {"q": "arzt", "sort": "field", "sort_field_id": due["id"]}
    bad = await api.client.get(f"{PREFIX}/documents/search", params=search, headers=auth(owner))
    assert bad.status_code == 422


async def test_counts_for_the_filters_of_the_documents(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    nord = await post(api, "/contacts", {"name": "Nord"}, auth(admin))
    ids = []
    for number in range(3):
        content = unique_pdf(str(20 + number))
        ids.append(
            await upload(api, auth(owner), content=content, filename=f"{number}.pdf", drain=False)
        )
    await api.drain()
    changes = [
        {"contact_id": nord["id"], "document_date": "2026-09-30"},
        {"contact_id": nord["id"], "document_date": "2025-12-24"},
        {"document_date": None},
    ]
    for id, change in zip(ids, changes, strict=True):
        response = await api.client.patch(
            f"{PREFIX}/documents/{id}", json=change, headers=auth(owner)
        )
        assert response.status_code == 200, response.text

    async def facets(**params: Any) -> dict[str, Any]:
        response = await api.client.get(
            f"{PREFIX}/documents/facets", params=params, headers=auth(owner)
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    counted = await facets()
    assert counted["total"] == 3
    assert counted["contacts"] == [{"id": nord["id"], "count": 2}, {"id": None, "count": 1}]
    assert counted["years"] == [
        {"year": 2026, "count": 1, "months": [{"month": "2026-09", "count": 1}]},
        {"year": 2025, "count": 1, "months": [{"month": "2025-12", "count": 1}]},
    ]
    assert counted["undated"] == 1
    # The period counts without its own choice; the contacts follow it.
    in_2026 = await facets(document_date_from="2026-01-01", document_date_to="2026-12-31")
    assert in_2026["total"] == 1
    assert [year["year"] for year in in_2026["years"]] == [2026, 2025]
    assert in_2026["contacts"] == [{"id": nord["id"], "count": 1}]
    everyone = await api.client.get(
        f"{PREFIX}/documents/facets", params={"all_users": True}, headers=auth(owner)
    )
    assert everyone.status_code == 403


async def test_master_data_with_their_document_counts(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    contact = await post(api, "/contacts", {"name": "ACME"}, auth(admin))
    unused = await post(api, "/contacts", {"name": "Nobody"}, auth(admin))
    definition = {"name": "Note", "data_type": "text", "document_type_ids": None}
    note = await post(api, "/fields", definition, auth(admin))
    document = await upload(api, auth(owner))
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
    # `all_users` is for admins whether or not counts are asked for.
    for path in ("/contacts", "/document-types", "/tags", "/fields"):
        denied = await api.client.get(
            f"{PREFIX}{path}", params={"all_users": True}, headers=auth(owner)
        )
        assert denied.status_code == 403, path
        assert set((await counts(path, auth(admin), all_users=True)).values()) <= {None}, path


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
    twice = await assign([{"field_id": only["id"]}, {"field_id": only["id"]}], auth(admin))
    assert twice.status_code == 422
    assert twice.json()["detail"] == "fields: Value error, each field once"
    assert (await assign([], auth(owner))).status_code == 403
    # A document of the invoice with a value for Amount keeps it there.
    document = await upload(api, auth(owner))
    changed = await api.client.patch(
        f"{PREFIX}/documents/{document}",
        json={"document_type_id": invoice["id"], "fields": {amount["id"]: "12"}},
        headers=auth(owner),
    )
    assert changed.status_code == 200, changed.text
    assert (await assign([{"field_id": only["id"]}], auth(admin))).status_code == 409


async def test_a_document_type_is_created_with_its_fields(api: Api) -> None:
    """Issue #73: one request, all or nothing; the pattern may name the fields it comes with."""
    admin = await api.admin()
    letter = await post(api, "/document-types", {"name": "Letter"}, auth(admin))
    amount = await post(
        api,
        "/fields",
        {"name": "Amount", "data_type": "text", "document_type_ids": [letter["id"]]},
        auth(admin),
    )
    body = {
        "name": "Invoice",
        "title_pattern": "Invoice {{ field.amount }}",
        "fields": [{"field_id": amount["id"], "required": True}],
    }
    invoice = await post(api, "/document-types", body, auth(admin))
    fields = (await api.client.get(f"{PREFIX}/fields", headers=auth(admin))).json()
    (stored,) = [item for item in fields if item["id"] == amount["id"]]
    assert set(stored["document_type_ids"]) == {letter["id"], invoice["id"]}
    assert invoice["id"] in stored["required_document_type_ids"]
    # A field that does not exist: no type either.
    missing = {"name": "Reminder", "fields": [{"field_id": str(UUID(int=7))}]}
    refused = await api.client.post(f"{PREFIX}/document-types", json=missing, headers=auth(admin))
    assert refused.status_code == 404
    types = (await api.client.get(f"{PREFIX}/document-types", headers=auth(admin))).json()
    assert "Reminder" not in {item["name"] for item in types}


async def test_downloads(api: Api) -> None:
    owner = await api.user()
    document = await upload(api, auth(owner))
    original = await api.client.get(f"{PREFIX}/documents/{document}/original", headers=auth(owner))
    assert original.status_code == 200
    assert original.content == (SAMPLES / "scan.pdf").read_bytes()
    assert original.headers["content-type"] == "application/pdf"
    assert original.headers["content-disposition"].startswith("attachment;")
    assert "Bill%202026.pdf" in original.headers["content-disposition"]
    assert original.headers["x-content-type-options"] == "nosniff"
    assert original.headers["content-security-policy"].startswith("sandbox")
    await api.container.object_store.delete(archive_key(DocumentId(UUID(document))))
    missing = await api.client.get(f"{PREFIX}/documents/{document}/archive", headers=auth(owner))
    assert missing.status_code == 404
    await api.container.object_store.put(
        archive_key(DocumentId(UUID(document))),
        b"%PDF-1.7 archive",
        content_type="application/pdf",
    )
    archive = await api.client.get(f"{PREFIX}/documents/{document}/archive", headers=auth(owner))
    assert archive.content == b"%PDF-1.7 archive"
    assert archive.headers["content-disposition"].startswith("inline;")


async def test_moving_and_deleting(api: Api) -> None:
    owner = await api.user()
    document = await upload(api, auth(owner))
    before = await api.client.get(f"{PREFIX}/documents/{document}", headers=auth(owner))
    assert before.json()["space_confirmed_at"] is None
    target = await post(api, "/spaces", {"name": "Archive"}, auth(owner))
    moved = await api.client.post(
        f"{PREFIX}/documents/{document}/move", json={"space_id": target["id"]}, headers=auth(owner)
    )
    assert moved.status_code == 204
    details = await api.client.get(f"{PREFIX}/documents/{document}", headers=auth(owner))
    assert details.json()["space_id"] == target["id"]
    # A person's move decides the space: the filing box says when.
    assert details.json()["space_confirmed_at"] is not None
    deleted = await api.client.delete(f"{PREFIX}/documents/{document}", headers=auth(owner))
    assert deleted.status_code == 204
    gone = await api.client.get(f"{PREFIX}/documents/{document}", headers=auth(owner))
    assert gone.status_code == 404


async def test_moving_into_a_space_one_only_reads_names_it(api: Api) -> None:
    owner, friend = await api.user(), await api.user()
    document = await upload(api, auth(friend))
    space = await post(api, "/spaces", {"name": "Household"}, auth(owner))
    await api.client.put(
        f"{PREFIX}/spaces/{space['id']}/members/{friend.id}",
        json={"role": "read"},
        headers=auth(owner),
    )
    refused = await api.client.post(
        f"{PREFIX}/documents/{document}/move", json={"space_id": space["id"]}, headers=auth(friend)
    )
    assert refused.status_code == 403
    assert refused.json()["space_id"] == space["id"]


async def test_a_space_describes_what_belongs_in_it(api: Api) -> None:
    owner, friend = await api.user(), await api.user()
    space = await post(
        api, "/spaces", {"name": "Haushalt", "description": " Wohnung, Nebenkosten "}, auth(owner)
    )
    assert space["description"] == "Wohnung, Nebenkosten"
    url = f"{PREFIX}/spaces/{space['id']}"
    renamed = await api.client.patch(url, json={"name": "Zuhause"}, headers=auth(owner))
    assert (renamed.json()["name"], renamed.json()["description"]) == (
        "Zuhause",
        "Wohnung, Nebenkosten",
    )
    cleared = await api.client.patch(url, json={"description": None}, headers=auth(owner))
    assert cleared.json()["description"] is None
    too_long = await api.client.patch(url, json={"description": "x" * 301}, headers=auth(owner))
    assert too_long.status_code == 422
    personal = (await api.client.get(f"{PREFIX}/spaces", headers=auth(friend))).json()[0]
    described = await api.client.patch(
        f"{PREFIX}/spaces/{personal['id']}", json={"description": "Arbeit"}, headers=auth(friend)
    )
    assert described.json()["description"] == "Arbeit"
    refused = await api.client.patch(
        f"{PREFIX}/spaces/{personal['id']}", json={"name": "Mine"}, headers=auth(friend)
    )
    assert refused.status_code == 422
    # An editor of the friend's personal space does not write its description: its user does.
    await api.client.put(
        f"{PREFIX}/spaces/{personal['id']}/members/{owner.id}",
        json={"role": "edit"},
        headers=auth(friend),
    )
    foreign = await api.client.patch(
        f"{PREFIX}/spaces/{personal['id']}", json={"description": "Mein"}, headers=auth(owner)
    )
    assert foreign.status_code == 403


async def test_spaces_and_members(api: Api) -> None:
    owner, friend = await api.user(), await api.user("friend")
    space = await post(api, "/spaces", {"name": "Household"}, auth(owner))
    mine = [
        {
            "user_id": str(owner.id),
            "role": "edit",
            "username": owner.username,
            "display_name": None,
            "active": True,
        }
    ]
    assert (space["role"], space["members"], space["personal_of"]) == ("edit", mine, None)
    url = f"{PREFIX}/spaces/{space['id']}"
    shared = await api.client.put(
        f"{url}/members/{friend.id}", json={"role": "read"}, headers=auth(owner)
    )
    assert {(m["user_id"], m["role"]) for m in shared.json()["members"]} == {
        (str(owner.id), "edit"),
        (str(friend.id), "read"),
    }
    seen = (await api.client.get(f"{PREFIX}/spaces", headers=auth(friend))).json()
    assert {(d["name"], d["personal_of"]) for d in seen} == {
        ("Personal", str(friend.id)),
        ("Household", None),
    }
    # An admin lists their own spaces like everyone, every space only with `all_users`.
    admin = await api.user("admin", role=Role.ADMIN)
    own = (await api.client.get(f"{PREFIX}/spaces", headers=auth(admin))).json()
    assert [d["personal_of"] for d in own] == [str(admin.id)]
    every = await api.client.get(
        f"{PREFIX}/spaces", params={"all_users": True}, headers=auth(admin)
    )
    assert "Household" in {d["name"] for d in every.json()}
    refused = await api.client.get(
        f"{PREFIX}/spaces", params={"all_users": True}, headers=auth(friend)
    )
    assert refused.status_code == 403
    duplicate = await api.client.post(
        f"{PREFIX}/spaces", json={"name": "household"}, headers=auth(friend)
    )
    assert duplicate.status_code == 409
    personal = next(d for d in seen if d["personal_of"])
    keeps = await api.client.put(
        f"{PREFIX}/spaces/{personal['id']}/members/{friend.id}",
        json={"role": "read"},
        headers=auth(friend),
    )
    assert keeps.status_code == 422  # its user always edits it
    lent = await api.client.put(
        f"{PREFIX}/spaces/{personal['id']}/members/{owner.id}",
        json={"role": "read"},
        headers=auth(friend),
    )
    assert lent.status_code == 200  # a personal space may be shared
    unshared = await api.client.delete(f"{url}/members/{friend.id}", headers=auth(owner))
    assert unshared.json()["members"] == mine
    assert (await api.client.get(url, headers=auth(friend))).status_code == 404
    # A deactivated member keeps their place, with their name for the others.
    await api.client.put(f"{url}/members/{friend.id}", json={"role": "read"}, headers=auth(owner))
    admin = await api.admin()
    await api.services.users.update(admin.id, friend.id, active=False)
    listed = (await api.client.get(url, headers=auth(owner))).json()["members"]
    assert {(m["username"], m["active"]) for m in listed} == {
        (owner.username, True),
        ("friend", False),
    }
    await api.services.users.update(admin.id, friend.id, active=True)
    # A reader leaves a space themselves.
    await api.client.put(f"{url}/members/{friend.id}", json={"role": "read"}, headers=auth(owner))
    left = await api.client.delete(f"{url}/members/{friend.id}", headers=auth(friend))
    assert left.status_code == 204, left.text
    assert (await api.client.get(url, headers=auth(friend))).status_code == 404
    assert (await api.client.delete(url, headers=auth(owner))).status_code == 204


async def test_everyone_finds_where_to_hand_a_document_over(api: Api) -> None:
    """`GET /users` names every user's personal space, so a user can hand a document over to
    someone whose space they are no member of."""
    owner, friend = await api.user("owner"), await api.user("friend")
    listed = await api.client.get(f"{PREFIX}/users", headers=auth(owner))
    assert listed.status_code == 200
    entry = next(item for item in listed.json() if item["username"] == "friend")
    assert set(entry) == {"id", "username", "personal_space_id"}
    single = await api.client.get(f"{PREFIX}/users/{friend.id}", headers=auth(owner))
    assert single.json()["personal_space_id"] == entry["personal_space_id"]
    document = await upload(api, auth(owner), content=unique_pdf("handed"), drain=False)
    moved = await api.client.post(
        f"{PREFIX}/documents/{document}/move",
        json={"space_id": entry["personal_space_id"]},
        headers=auth(owner),
    )
    assert moved.status_code == 204, moved.text
    theirs = await api.client.get(f"{PREFIX}/documents/{document}", headers=auth(friend))
    assert theirs.json()["space_id"] == entry["personal_space_id"]
    assert (
        await api.client.get(f"{PREFIX}/documents/{document}", headers=auth(owner))
    ).status_code == 404


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


async def test_deleting_a_user_settles_the_spaces_that_stop_it(api: Api) -> None:
    """Tobi, 22.10.2026: the API names the spaces, the admin decides in one request."""
    admin, anna = await api.admin("root"), await api.user("anna")
    document = await upload(api, auth(anna), content=unique_pdf("anna"))
    url = f"{PREFIX}/users/{anna.id}"
    removal = await api.client.get(f"{url}/removal", headers=auth(admin))
    assert removal.status_code == 200, removal.text
    (blocking,) = removal.json()["blocking_spaces"]
    assert (blocking["personal"], blocking["documents"], blocking["choices"]) == (
        True,
        1,
        ["move_to"],
    )
    assert (await api.client.get(f"{url}/removal", headers=auth(anna))).status_code == 403
    refused = await api.client.delete(url, headers=auth(admin))
    assert refused.status_code == 409
    assert [item["space_id"] for item in refused.json()["blocking_spaces"]] == [
        blocking["space_id"]
    ]
    target = (await api.client.get(f"{PREFIX}/users/{admin.id}", headers=auth(admin))).json()[
        "personal_space_id"
    ]
    both = {"space_id": blocking["space_id"], "move_to": target, "remove": True}
    unclear = await api.client.request("DELETE", url, json={"spaces": [both]}, headers=auth(admin))
    assert unclear.status_code == 422
    settle = {"spaces": [{"space_id": blocking["space_id"], "move_to": target}]}
    deleted = await api.client.request("DELETE", url, json=settle, headers=auth(admin))
    assert deleted.status_code == 204, deleted.text
    moved = await api.client.get(f"{PREFIX}/documents/{document}", headers=auth(admin))
    assert (moved.json()["space_id"], moved.json()["uploaded_by"]) == (target, None)


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


async def test_when_a_document_came_in_is_set_and_orders_the_list(api: Api) -> None:
    owner = await api.user()
    o = auth(owner)
    first = await upload(api, o, content=unique_pdf("first"))
    second = await upload(api, o, content=unique_pdf("second"))
    await api.drain()
    url = f"{PREFIX}/documents/{first}"
    log = (await api.client.get(f"{url}/log", headers=o)).json()

    response = await api.client.patch(
        url, json={"created_at": "2023-01-02T09:30:00+01:00"}, headers=o
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert datetime.fromisoformat(body["created_at"]) == datetime(2023, 1, 2, 8, 30, tzinfo=UTC)
    # It confirms nothing, and the rules do not run: the log has no entry more.
    assert body["confirmed_at"] is None
    assert len((await api.client.get(f"{url}/log", headers=o)).json()) == len(log)
    # Sorted by when they came in, the first arrival is the older one now.
    listed = await api.client.get(f"{PREFIX}/documents?sort=-created_at", headers=o)
    assert [item["id"] for item in listed.json()["items"]] == [second, first]
    oldest = await api.client.get(f"{PREFIX}/documents?sort=created_at", headers=o)
    assert [item["id"] for item in oldest.json()["items"]] == [first, second]
    # Never ahead, always with a time zone, never null.
    for wrong in ("2999-01-01T00:00:00Z", "2023-01-02T09:30:00", None):
        response = await api.client.patch(url, json={"created_at": wrong}, headers=o)
        assert response.status_code == 422, (wrong, response.text)


async def test_field_definitions_change(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    a = auth(admin)
    kind = await post(
        api, "/fields", {"name": "Kind", "data_type": "choice", "choices": ["a", "b"]}, a
    )
    invoice = await post(api, "/document-types", {"name": "Invoice"}, a)
    document = await upload(api, auth(owner))
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
        {
            "kind": "iban",
            "value": "DE89370400440532013000",
            "source": "manual",
            "topic_id": None,
            "user_id": None,
        }
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


async def test_a_field_is_set_by_hand(api: Api) -> None:
    a = auth(await api.admin())
    asn = await post(
        api, "/fields", {"name": "ASN", "data_type": "number", "assignment": "manual"}, a
    )
    assert asn["assignment"] == "manual"
    read = await api.client.patch(
        f"{PREFIX}/fields/{asn['id']}", json={"assignment": "auto"}, headers=a
    )
    assert read.json()["assignment"] == "auto"
    kept = await api.client.patch(f"{PREFIX}/fields/{asn['id']}", json={"name": "AS"}, headers=a)
    assert kept.json()["assignment"] == "auto"


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
    """M4-04: only multipart uploads have a size limit (`LEKTO_UPLOAD_MAX_SIZE`). A JSON body of
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
        f"{PREFIX}/spaces",
        content=chunks(),
        headers={**auth(user), "content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "the request body is larger than 1048576 bytes"


async def test_bodies_below_the_limit_pass(api: Api) -> None:
    user = await api.user()
    name = "a" * 200
    response = await api.client.post(f"{PREFIX}/spaces", json={"name": name}, headers=auth(user))
    assert response.status_code == 201


async def test_tags_with_scopes_trees_and_groups(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    a, o = auth(admin), auth(owner)
    insurance = await post(api, "/tags", {"name": "Insurance"}, a)
    health = await post(api, "/tags", {"name": "Health", "parent_id": insurance["id"]}, a)
    paid = await post(api, "/tags", {"name": "Paid", "assignment": "manual"}, a)
    insurer = await post(api, "/tags", {"name": "Insurance", "scope": "contact"}, a)
    bills = await post(api, "/tags", {"name": "Bills", "scope": "document_type"}, a)
    assert (health["scope"], health["parent_id"], health["path"]) == (
        "document",
        insurance["id"],
        ["Insurance", "Health"],
    )
    assert (health["assignment"], health["shown"]) == ("auto", True)
    assert (paid["assignment"], insurer["assignment"], insurer["shown"]) == (
        "manual",
        "manual",
        False,
    )
    for body, status in (
        ({"name": "insurance"}, 409),  # names are unique per scope
        ({"name": "X", "scope": "contact", "assignment": "auto"}, 422),
        ({"name": "X", "parent_id": insurer["id"]}, 422),  # another scope
        ({"name": "X", "scope": "person"}, 422),
        ({"name": "X", "parent_id": str(UUID(int=7))}, 404),
    ):
        response = await api.client.post(f"{PREFIX}/tags", json=body, headers=a)
        assert response.status_code == status, (body, response.text)

    contact = await post(api, "/contacts", {"name": "Nord", "group_ids": [insurer["id"]]}, a)
    kind = await post(api, "/document-types", {"name": "Invoice", "group_ids": [bills["id"]]}, a)
    assert (contact["group_ids"], kind["group_ids"]) == ([insurer["id"]], [bills["id"]])
    wrong = await api.client.patch(
        f"{PREFIX}/contacts/{contact['id']}", json={"group_ids": [bills["id"]]}, headers=a
    )
    assert wrong.status_code == 422, wrong.text
    unknown = await api.client.post(
        f"{PREFIX}/document-types", json={"name": "X", "group_ids": [str(UUID(int=8))]}, headers=a
    )
    assert unknown.status_code == 404, unknown.text

    document = await upload(api, o)
    changed = await api.client.patch(
        f"{PREFIX}/documents/{document}",
        json={
            "tag_ids": [insurance["id"], health["id"]],
            "contact_id": contact["id"],
            "document_type_id": kind["id"],
        },
        headers=o,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["tag_ids"] == [health["id"]]  # the parent gives way to the child
    group_tag = await api.client.patch(
        f"{PREFIX}/documents/{document}", json={"tag_ids": [insurer["id"]]}, headers=o
    )
    assert group_tag.status_code == 422, group_tag.text

    async def listed(**params: Any) -> list[str]:
        response = await api.client.get(f"{PREFIX}/documents", params=params, headers=o)
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()["items"]]

    assert await listed(tag_id=insurance["id"]) == [document]
    assert await listed(contact_group_id=insurer["id"]) == [document]
    assert await listed(document_type_group_id=bills["id"]) == [document]
    assert await listed(document_type_group_id=insurer["id"]) == []
    # Several groups: the contact (type) in one of them.
    assert await listed(contact_group_id=[str(UUID(int=9)), insurer["id"]]) == [document]
    assert await listed(document_type_group_id=[bills["id"], insurer["id"]]) == [document]

    # The tree in order, with counts; one scope.
    response = await api.client.get(f"{PREFIX}/tags", params={"document_counts": True}, headers=o)
    assert [(tag["name"], tag["scope"], tag["document_count"]) for tag in response.json()] == [
        ("Insurance", "document", 1),
        ("Health", "document", 1),
        ("Paid", "document", 0),
        ("Insurance", "contact", 1),
        ("Bills", "document_type", 1),
    ]
    groups = await api.client.get(f"{PREFIX}/tags", params={"scope": "contact"}, headers=o)
    assert [tag["id"] for tag in groups.json()] == [insurer["id"]]

    # Moved to the top, hidden; then deleted once nothing uses it.
    moved = await api.client.patch(
        f"{PREFIX}/tags/{health['id']}", json={"parent_id": None, "shown": False}, headers=a
    )
    assert moved.status_code == 200, moved.text
    assert (moved.json()["parent_id"], moved.json()["path"], moved.json()["shown"]) == (
        None,
        ["Health"],
        False,
    )
    below = await api.client.patch(
        f"{PREFIX}/tags/{insurance['id']}", json={"parent_id": insurance["id"]}, headers=a
    )
    assert below.status_code == 422
    used = await api.client.delete(f"{PREFIX}/tags/{insurer['id']}", headers=a)
    assert used.status_code == 409 and "contacts are in" in used.text
    gone = await api.client.delete(f"{PREFIX}/tags/{paid['id']}", headers=a)
    assert gone.status_code == 204


async def test_groups_and_topics_come_with_their_contacts_and_types(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    a, o = auth(admin), auth(owner)
    insurer = await post(api, "/tags", {"name": "Insurer", "scope": "contact"}, a)
    health = await post(
        api, "/tags", {"name": "Health", "scope": "contact", "parent_id": insurer["id"]}, a
    )
    work = await post(api, "/tags", {"name": "Work", "scope": "topic"}, a)
    bills = await post(api, "/tags", {"name": "Bills", "scope": "document_type"}, a)
    await post(api, "/tags", {"name": "Paid"}, a)
    groups = [insurer["id"], health["id"]]
    await post(
        api, "/contacts", {"name": "Nord", "group_ids": groups, "topic_ids": [work["id"]]}, a
    )
    await post(api, "/contacts", {"name": "Süd", "group_ids": [health["id"]]}, a)
    await post(api, "/document-types", {"name": "Invoice", "group_ids": [bills["id"]]}, a)

    async def listed(**params: Any) -> list[tuple[str, Any, Any]]:
        response = await api.client.get(f"{PREFIX}/tags", params=params, headers=o)
        assert response.status_code == 200, response.text
        return [
            (tag["name"], tag["contact_count"], tag["document_type_count"])
            for tag in response.json()
        ]

    assert await listed(document_counts=True) == [
        ("Paid", None, None),
        ("Insurer", 2, None),  # Nord once, though in Insurer and in Health below it
        ("Health", 2, None),
        ("Bills", None, 1),
        ("Work", 1, None),
    ]
    assert {count for _, *counts in await listed() for count in counts} == {None}


async def test_tags_and_types_carry_icons_and_colours(api: Api) -> None:
    admin, user = await api.admin(), await api.user()
    a = auth(admin)
    tag = await post(api, "/tags", {"name": "Health", "icon": "heart-pulse", "color": "#B45309"}, a)
    assert (tag["icon"], tag["color"]) == ("heart-pulse", "#b45309")
    topic = await post(api, "/tags", {"name": "Car", "scope": "topic", "color": "sky"}, a)
    assert (topic["icon"], topic["color"]) == (None, "sky")
    for body in (
        {"name": "X", "icon": "Heart"},
        {"name": "X", "icon": "x" * 65},
        {"name": "X", "color": "purple"},
        {"name": "X", "color": "#12345"},
        {"name": "X", "color": ""},
    ):
        response = await api.client.post(f"{PREFIX}/tags", json=body, headers=a)
        assert response.status_code == 422, (body, response.text)
    url = f"{PREFIX}/tags/{tag['id']}"
    kept = await api.client.patch(url, json={"name": "Health care"}, headers=a)
    assert (kept.json()["icon"], kept.json()["color"]) == ("heart-pulse", "#b45309")
    removed = await api.client.patch(url, json={"icon": None, "color": "pink"}, headers=a)
    assert (removed.json()["icon"], removed.json()["color"]) == (None, "pink")
    refused = await api.client.patch(url, json={"icon": "house"}, headers=auth(user))
    assert refused.status_code == 403

    kind = await post(api, "/document-types", {"name": "Invoice", "icon": "receipt"}, a)
    assert kind["icon"] == "receipt"
    type_url = f"{PREFIX}/document-types/{kind['id']}"
    described = await api.client.patch(type_url, json={"description": "Bills"}, headers=a)
    assert described.json()["icon"] == "receipt"
    cleared = await api.client.patch(type_url, json={"icon": None}, headers=a)
    assert cleared.json()["icon"] is None
    wrong = await api.client.patch(type_url, json={"icon": "receipt euro"}, headers=a)
    assert wrong.status_code == 422
    listed = await api.client.get(f"{PREFIX}/tags", headers=auth(user))
    assert {item["name"]: item["color"] for item in listed.json()} == {
        "Health care": "pink",
        "Car": "sky",
    }


async def test_topics_at_contacts_identifiers_and_documents(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    a, o = auth(admin), auth(owner)
    insurance = await post(api, "/tags", {"name": "Insurance", "scope": "topic"}, a)
    health = await post(
        api, "/tags", {"name": "Health", "scope": "topic", "parent_id": insurance["id"]}, a
    )
    work = await post(api, "/tags", {"name": "Work", "scope": "topic"}, a)
    assert (work["assignment"], work["shown"]) == ("auto", True)
    listed = await api.client.get(f"{PREFIX}/tags", params={"scope": "topic"}, headers=o)
    assert [item["path"] for item in listed.json()] == [
        ["Insurance"],
        ["Insurance", "Health"],
        ["Work"],
    ]
    number = {"kind": "personnel_number", "value": "004711", "topic_id": work["id"]}
    contact = await post(
        api,
        "/contacts",
        {"name": "Nord", "topic_ids": [work["id"], health["id"]], "identifiers": [number]},
        a,
    )
    assert contact["topic_ids"] == sorted([work["id"], health["id"]])
    assert contact["identifiers"] == [
        {
            "kind": "personnel_number",
            "value": "4711",
            "source": "manual",
            "topic_id": work["id"],
            "user_id": None,
        }
    ]
    path = f"{PREFIX}/contacts/{contact['id']}"
    attach = {"kind": "customer_number", "value": "KV-2026-1", "topic_id": insurance["id"]}
    refused = await api.client.post(f"{path}/identifiers", json=attach, headers=a)
    assert refused.status_code == 422, refused.text
    assert "topic" in refused.json()["detail"]  # Nord does not enable Insurance
    attach["topic_id"] = health["id"]
    attached = await api.client.post(f"{path}/identifiers", json=attach, headers=a)
    assert attached.status_code == 200, attached.text
    assert [item["topic_id"] for item in attached.json()["identifiers"]] == [
        health["id"],
        work["id"],
    ]
    wrong = await api.client.patch(path, json={"topic_ids": [insurance["id"], "x"]}, headers=a)
    assert wrong.status_code == 422

    document = await upload(api, o)
    url = f"{PREFIX}/documents/{document}"
    no_contact = await api.client.patch(url, json={"topic_id": work["id"]}, headers=o)
    assert no_contact.status_code == 422, no_contact.text
    response = await api.client.patch(
        url, json={"contact_id": contact["id"], "topic_id": health["id"]}, headers=o
    )
    assert response.json()["topic_id"] == health["id"], response.text
    not_enabled = await api.client.patch(url, json={"topic_id": insurance["id"]}, headers=o)
    assert not_enabled.status_code == 422
    chosen = await api.client.patch(url, json={"topic_id": insurance["id"]}, headers=a)
    assert chosen.json()["topic_id"] == insurance["id"]
    enabled = (await api.client.get(path, headers=a)).json()["topic_ids"]
    assert insurance["id"] in enabled
    # Taking it away again is refused while the document carries it.
    kept = await api.client.patch(path, json={"topic_ids": [work["id"]]}, headers=a)
    assert kept.status_code == 409
    for topic, found in ((insurance, [document]), (work, [])):
        page = await api.client.get(
            f"{PREFIX}/documents", params={"topic_id": topic["id"]}, headers=o
        )
        assert [item["id"] for item in page.json()["items"]] == found
    second = await upload(api, o, content=unique_pdf("1"), filename="second.pdf")
    await api.client.patch(
        f"{PREFIX}/documents/{second}",
        json={"contact_id": contact["id"], "topic_id": work["id"]},
        headers=o,
    )
    # Several topics: the documents with one of them (or one below it), newest first.
    for topics, found in (
        ([work, insurance], [second, document]),
        ([work, health], [second]),
        ([health], []),
    ):
        params = [("topic_id", topic["id"]) for topic in topics]
        page = await api.client.get(f"{PREFIX}/documents", params=params, headers=o)
        assert [item["id"] for item in page.json()["items"]] == found, page.text
    counted = await api.client.get(
        f"{PREFIX}/tags", params={"scope": "topic", "document_counts": True}, headers=o
    )
    assert {item["name"]: item["document_count"] for item in counted.json()} == {
        "Insurance": 1,
        "Health": 0,
        "Work": 1,
    }
    assert (
        await api.client.delete(f"{PREFIX}/tags/{insurance['id']}", headers=a)
    ).status_code == 409


async def test_a_document_type_is_a_relation_target(api: Api) -> None:
    """Issue #145: an admin marks a type whose documents others refer to by a number."""
    a = auth(await api.admin())
    contract = await post(api, "/document-types", {"name": "Vertrag", "relation_target": True}, a)
    assert contract["relation_target"] is True
    invoice = await post(api, "/document-types", {"name": "Rechnung"}, a)
    assert invoice["relation_target"] is False
    path = f"{PREFIX}/document-types/{invoice['id']}"
    changed = await api.client.patch(path, json={"relation_target": True}, headers=a)
    assert changed.json()["relation_target"] is True
    renamed = await api.client.patch(path, json={"name": "Rechnungen"}, headers=a)
    assert renamed.json()["relation_target"] is True  # left out: it stays
    nulled = await api.client.patch(path, json={"relation_target": None}, headers=a)
    assert nulled.json()["relation_target"] is True  # null too
    user = auth(await api.user())
    denied = await api.client.patch(path, json={"relation_target": False}, headers=user)
    assert denied.status_code == 403
