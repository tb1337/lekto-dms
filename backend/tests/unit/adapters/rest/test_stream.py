"""`GET /documents/stream` (#145 PR 13)."""

from lekto.adapters.inbound.rest import PREFIX
from tests.api import auth
from tests.unit.adapters.rest.support import Api, upload


async def test_the_stream_of_the_caller_s_documents(api: Api) -> None:
    owner = await api.user()
    first = await upload(api, auth(owner))
    found = await api.client.get(f"{PREFIX}/documents/stream", headers=auth(owner))
    assert found.status_code == 200, found.text
    body = found.json()
    (lane,) = body["lanes"]
    assert (lane["kind"], [item["id"] for item in lane["documents"]]) == ("single", [first])
    assert (body["relations"], body["truncated"]) == ([], False)
    others = await api.client.get(f"{PREFIX}/documents/stream?all_users=true", headers=auth(owner))
    assert others.status_code == 403
