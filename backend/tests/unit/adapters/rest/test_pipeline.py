"""The processing graph over HTTP."""

from papiq.adapters.inbound.rest import PREFIX
from tests.api import auth
from tests.unit.adapters.rest.support import Api

PIPELINE = f"{PREFIX}/pipeline"
REPARSE = f"{PIPELINE}/reparse"


async def test_the_graph_lists_every_node_with_its_needs(api: Api) -> None:
    user = await api.user()
    response = await api.client.get(PIPELINE, headers=auth(user))
    assert response.status_code == 200
    nodes = response.json()["nodes"]
    assert [node["node"] for node in nodes] == [
        "receive",
        "ocr",
        "pages",
        "parse",
        "signal_llm",
        "signal_classifier",
        "signal_neighbours",
        "signal_facts",
        "judge",
        "fields",
        "apply_rules",
        "file",
    ]
    by_name = {node["node"]: node["requires"] for node in nodes}
    assert by_name["receive"] == []
    assert by_name["ocr"] == by_name["pages"] == ["receive"]
    assert by_name["file"] == ["apply_rules", "pages"]
    assert by_name["judge"] == [
        "signal_classifier",
        "signal_facts",
        "signal_llm",
        "signal_neighbours",
    ]


async def test_the_graph_needs_a_session(api: Api) -> None:
    assert (await api.client.get(PIPELINE)).status_code == 401


async def test_only_admins_have_every_text_read_again(api: Api) -> None:
    user, admin = await api.user(), await api.admin()
    assert (await api.client.post(REPARSE)).status_code == 401
    assert (await api.client.post(REPARSE, headers=auth(user))).status_code == 403
    response = await api.client.post(REPARSE, headers=auth(admin))
    assert response.status_code == 202
    assert response.json() == {"queued": 0}
