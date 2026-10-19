"""Reading a document with the vision language model over HTTP: the model in `GET /pipeline`,
the request (`POST /documents/{id}/vision`), the reading and its advice, the prompt."""

import dataclasses
from collections.abc import AsyncIterator

import httpx2
import pytest

from lekto.adapters.inbound.rest import PREFIX
from lekto.adapters.outbound.memory import FAKE_VISION, FakeOcr, ManualClock
from lekto.composition.container import build_memory_container, build_services
from tests import builders
from tests.api import auth
from tests.unit.adapters.rest.support import DOCUMENTS, Api, make_app, upload


@pytest.fixture
async def vision_api() -> AsyncIterator[Api]:
    clock = ManualClock(builders.NOW)
    container = dataclasses.replace(build_memory_container(clock), ocr=FakeOcr(vision=FAKE_VISION))
    services = build_services(container)
    builders.skip_classification(services.pipeline)
    app = make_app(container, services)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://papiq") as client:
        yield Api(container, services, app, client, clock)


async def test_the_pipeline_names_the_model(api: Api, vision_api: Api) -> None:
    without = await api.client.get(f"{PREFIX}/pipeline", headers=auth(await api.user()))
    assert without.json()["vision"] is None
    user = await vision_api.user()
    response = await vision_api.client.get(f"{PREFIX}/pipeline", headers=auth(user))
    assert response.json()["vision"] == {"model": "fake-vlm", "endpoint": "vlm.example:443"}


async def test_the_owner_has_the_document_read_with_the_model(vision_api: Api) -> None:
    api = vision_api
    owner = await api.user()
    url = f"{DOCUMENTS}/{await upload(api, auth(owner))}"
    before = (await api.client.get(url, headers=auth(owner))).json()
    assert before["processing"]["vision"] is False
    reading = await api.client.get(f"{url}/reading", headers=auth(owner))
    assert reading.status_code == 200
    assert reading.json() == {
        "vision": False,
        "pages": [
            {
                "page": 1,
                "words": 20,
                "unsure": 0,
                "content": None,  # the fake counts no content
                "content_unsure": None,
                "poor": False,
            }
        ],
        "advice": None,
    }

    asked = await api.client.post(f"{url}/vision", headers=auth(owner))
    assert asked.status_code == 202, asked.text
    processing = asked.json()["processing"]
    assert (processing["status"], processing["vision"]) == ("processing", True)
    assert processing["run"] == before["processing"]["run"] + 1
    # Not twice at once.
    assert (await api.client.post(f"{url}/vision", headers=auth(owner))).status_code == 409
    await api.drain()

    read = (await api.client.get(f"{url}/reading", headers=auth(owner))).json()
    assert (read["vision"], read["advice"]) == (True, None)
    log = (await api.client.get(f"{url}/log", headers=auth(owner))).json()
    ocr = [entry for entry in log if entry["node"] == "ocr"][-1]
    assert ocr["output"]["vision"]["model"] == "fake-vlm"
    exchanges = await api.client.get(f"{url}/exchanges/ocr", headers=auth(owner))
    assert exchanges.status_code == 200
    (run,) = exchanges.json()
    assert run["run"] == processing["run"]
    assert run["calls"][0]["model"] == "fake-vlm"


async def test_only_the_owner_and_admins(vision_api: Api) -> None:
    api = vision_api
    owner, other, admin = await api.user(), await api.user(), await api.admin()
    url = f"{DOCUMENTS}/{await upload(api, auth(owner))}"
    assert (await api.client.post(f"{url}/vision")).status_code == 401
    assert (await api.client.post(f"{url}/vision", headers=auth(other))).status_code == 404
    assert (await api.client.get(f"{url}/reading", headers=auth(other))).status_code == 404
    assert (await api.client.get(f"{url}/reading", headers=auth(admin))).status_code == 200
    assert (await api.client.post(f"{url}/vision", headers=auth(admin))).status_code == 202


async def test_without_a_model_it_cannot_be_asked_for(api: Api) -> None:
    owner = await api.user()
    url = f"{DOCUMENTS}/{await upload(api, auth(owner))}"
    response = await api.client.post(f"{url}/vision", headers=auth(owner))
    assert response.status_code == 409
    assert "no vision language model is configured" in response.json()["detail"]
