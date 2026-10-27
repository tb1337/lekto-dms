"""The relations between documents over HTTP (#145 PR 9)."""

from tests.api import auth
from tests.unit.adapters.rest.support import DOCUMENTS, Api, upload


async def test_relating_documents(api: Api) -> None:
    owner = await api.user()
    first = await upload(api, auth(owner))
    second = await upload(api, auth(owner), content=b"%PDF-1.7 other")

    related = await api.client.post(
        f"{DOCUMENTS}/{second}/relations", json={"document_id": first}, headers=auth(owner)
    )
    assert related.status_code == 200, related.text
    body = related.json()
    assert body["editable"] is True
    # The later upload is the newer: it refers to the first.
    (item,) = body["refers_to"]
    assert (item["document"]["id"], item["origin"], item["state"]) == (first, "person", "set")
    again = await api.client.post(
        f"{DOCUMENTS}/{first}/relations", json={"document_id": second}, headers=auth(owner)
    )
    assert (again.status_code, again.json()["reason"]["code"]) == (409, "relation_exists")
    seen = (await api.client.get(f"{DOCUMENTS}/{first}/relations", headers=auth(owner))).json()
    assert [item["document"]["id"] for item in seen["referred_by"]] == [second]

    removed = await api.client.delete(
        f"{DOCUMENTS}/{first}/relations/{second}", headers=auth(owner)
    )
    assert removed.status_code == 200
    assert removed.json()["referred_by"] == []
    gone = await api.client.delete(f"{DOCUMENTS}/{first}/relations/{second}", headers=auth(owner))
    assert (gone.status_code, gone.json()["reason"]["code"]) == (404, "relation_not_found")
