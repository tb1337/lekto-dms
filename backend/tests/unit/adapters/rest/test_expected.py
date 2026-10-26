"""`GET /expected` (#145 PR 12)."""

from lekto.adapters.inbound.rest import PREFIX
from tests.api import auth
from tests.unit.adapters.rest.support import Api


async def test_the_expected_documents_of_the_caller(api: Api) -> None:
    owner = await api.user()
    found = await api.client.get(f"{PREFIX}/expected", headers=auth(owner))
    assert (found.status_code, found.json()) == (200, [])
    others = await api.client.get(f"{PREFIX}/expected?all_users=true", headers=auth(owner))
    assert others.status_code == 403
    admin = await api.admin()
    every = await api.client.get(f"{PREFIX}/expected?all_users=true", headers=auth(admin))
    assert every.status_code == 200
