"""`/lenses`: a user's saved looks at the documents over the API."""

from lekto.adapters.inbound.rest import PREFIX
from tests.api import auth
from tests.unit.adapters.rest.support import Api, post


async def test_a_lens_is_created_changed_ordered_and_deleted(api: Api) -> None:
    admin, user = await api.admin(), await api.user()
    due = await post(
        api, "/fields", {"name": "Due", "data_type": "date", "document_type_ids": None}, auth(admin)
    )
    tag = await post(api, "/tags", {"name": "to pay"}, auth(admin))
    body = {
        "name": "To pay",
        "filter": {"tag_ids": [tag["id"]], "document_period": "last_12_months"},
        "sort": "field",
        "sort_field_id": due["id"],
        "grouping": "due",
        "due_field_id": due["id"],
        "card_field_ids": [due["id"]],
    }
    created = await post(api, "/lenses", body, auth(user))
    assert created["position"] == 0 and created["layout"] == "grid"
    assert created["filter"]["tag_ids"] == [tag["id"]]
    assert created["filter"]["document_period"] == "last_12_months"
    assert created["filter"]["contact_ids"] == [] and created["query"] is None
    url = f"{PREFIX}/lenses/{created['id']}"

    # `null` clears, left out stays.
    changed = await api.client.patch(
        url,
        json={"name": "Bills", "sort": None, "sort_field_id": None, "query": "power"},
        headers=auth(user),
    )
    assert changed.status_code == 200, changed.text
    shown = changed.json()
    assert (shown["name"], shown["sort"], shown["query"]) == ("Bills", None, "power")
    assert shown["due_field_id"] == due["id"] and shown["grouping"] == "due"

    other = await post(api, "/lenses", {"name": "Tax"}, auth(user))
    ordered = await api.client.put(
        f"{PREFIX}/lenses/order", json={"ids": [other["id"], created["id"]]}, headers=auth(user)
    )
    assert ordered.status_code == 200, ordered.text
    assert [lens["name"] for lens in ordered.json()] == ["Tax", "Bills"]
    listed = (await api.client.get(f"{PREFIX}/lenses", headers=auth(user))).json()
    assert [lens["position"] for lens in listed] == [0, 1]

    assert (await api.client.delete(url, headers=auth(user))).status_code == 204
    assert (await api.client.get(url, headers=auth(user))).status_code == 404


async def test_a_lens_is_its_owners_alone(api: Api) -> None:
    admin, owner, other = await api.admin(), await api.user(), await api.user()
    lens = await post(api, "/lenses", {"name": "Mine"}, auth(owner))
    url = f"{PREFIX}/lenses/{lens['id']}"
    for stranger in (other, admin):
        assert (await api.client.get(url, headers=auth(stranger))).status_code == 404
        patched = await api.client.patch(url, json={"name": "x"}, headers=auth(stranger))
        assert patched.status_code == 404
        assert (await api.client.delete(url, headers=auth(stranger))).status_code == 404
        listed = await api.client.get(f"{PREFIX}/lenses", headers=auth(stranger))
        assert listed.json() == []
    assert (await api.client.get(f"{PREFIX}/lenses")).status_code == 401


async def test_lenses_that_do_not_fit_are_refused(api: Api) -> None:
    admin, user = await api.admin(), await api.user()
    note = await post(
        api,
        "/fields",
        {"name": "Note", "data_type": "text", "document_type_ids": None},
        auth(admin),
    )
    await post(api, "/lenses", {"name": "Taken"}, auth(user))
    for body, status in (
        ({"name": "taken"}, 409),
        ({"name": ""}, 422),
        ({"name": "x", "grouping": "due"}, 422),
        ({"name": "x", "sort": "relevance"}, 422),
        ({"name": "x", "sort": "field", "sort_field_id": note["id"]}, 422),
        ({"name": "x", "due_field_id": note["id"]}, 422),
        ({"name": "x", "card_field_ids": [note["id"]] * 4}, 422),
        (
            {
                "name": "x",
                "filter": {"document_period": "this_year", "document_date_from": "2026-01-01"},
            },
            422,
        ),
        ({"name": "x", "colour": "red"}, 422),
    ):
        response = await api.client.post(f"{PREFIX}/lenses", json=body, headers=auth(user))
        assert response.status_code == status, (body, response.text)
    order = await api.client.put(f"{PREFIX}/lenses/order", json={"ids": []}, headers=auth(user))
    assert order.status_code == 422
