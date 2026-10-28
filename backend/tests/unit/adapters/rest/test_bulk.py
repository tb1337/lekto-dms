"""Changing many documents at once over the API."""

from tests import builders
from tests.api import auth
from tests.unit.adapters.rest.support import DOCUMENTS, Api, post, unique_pdf, upload

BULK = f"{DOCUMENTS}/bulk"


async def test_tags_are_added_to_the_documents_of_a_filter_and_the_progress_followed(
    api: Api,
) -> None:
    admin, owner, other = await api.admin(), await api.user(), await api.user()
    o = auth(owner)
    tax = await post(api, "/tags", {"name": "Steuer"}, auth(admin))
    mine = [await upload(api, o, content=unique_pdf(str(n))) for n in range(2)]
    await upload(api, auth(other), content=unique_pdf("other"))

    response = await api.client.post(
        BULK, json={"action": {"kind": "change_tags", "add_tag_ids": [tax["id"]]}}, headers=o
    )
    assert response.status_code == 202, response.text
    assert (response.json()["status"], response.json()["total"]) == ("queued", 2)
    await builders.drain(api.services.bulk)

    progress = await api.client.get(response.headers["location"], headers=o)
    assert progress.status_code == 200, progress.text
    body = progress.json()
    assert (body["kind"], body["status"], body["done"], body["changed"]) == (
        "change_tags",
        "done",
        2,
        2,
    )
    for id in mine:
        document = (await api.client.get(f"{DOCUMENTS}/{id}", headers=o)).json()
        assert document["tag_ids"] == [tax["id"]]
    hidden = await api.client.get(response.headers["location"], headers=auth(other))
    assert hidden.status_code == 404


async def test_documents_by_id_skip_what_the_caller_cannot_change(api: Api) -> None:
    owner, other = await api.user(), await api.user()
    o = auth(owner)
    mine = await upload(api, o, content=unique_pdf("mine"))
    theirs = await upload(api, auth(other), content=unique_pdf("theirs"))

    response = await api.client.post(
        BULK,
        json={"document_ids": [mine, theirs], "action": {"kind": "delete"}},
        headers=o,
    )
    assert response.status_code == 202, response.text
    await builders.drain(api.services.bulk)

    body = (await api.client.get(response.headers["location"], headers=o)).json()
    assert body["changed"] == 1
    assert [(item["document_id"], item["reasons"][0]["code"]) for item in body["skipped"]] == [
        (theirs, "skip_not_available")
    ]
    assert (await api.client.get(f"{DOCUMENTS}/{mine}", headers=o)).status_code == 404


async def test_a_bulk_request_is_checked(api: Api) -> None:
    owner = await api.user()
    o = auth(owner)
    mine = await upload(api, o)

    async def refused(params: dict[str, str | bool], body: object, status: int = 422) -> None:
        response = await api.client.post(BULK, params=params, json=body, headers=o)
        assert response.status_code == status, response.text

    await refused({}, {"action": {"kind": "change_tags"}})  # which tags?
    same = {"kind": "change_tags", "add_tag_ids": [mine], "remove_tag_ids": [mine]}
    await refused({}, {"action": same})
    await refused({}, {"action": {"kind": "move"}})  # where to?
    await refused({}, {"action": {"kind": "reprocess", "from_node": "receive"}})
    await refused({"q": "Rechnung"}, {"document_ids": [mine], "action": {"kind": "confirm"}})
    await refused({}, {"document_ids": [], "action": {"kind": "confirm"}})
    await refused({"all_users": True}, {"action": {"kind": "confirm"}}, 403)
