"""The fixtures of the MCP tests: the API with the endpoint, and a scene of users and documents."""

from collections.abc import AsyncIterator
from uuid import UUID

import httpx2
import pytest

from lekto.adapters.outbound.memory import ManualClock
from lekto.composition.container import build_memory_container, build_services
from lekto.core.domain.ids import DocumentId
from lekto.core.services.objects import text_key
from tests import builders
from tests.unit.adapters.mcp.support import TEXT, running
from tests.unit.adapters.rest.support import Api, Scene, indexed_scene, make_app


@pytest.fixture
async def api() -> AsyncIterator[Api]:
    """The API with the MCP endpoint, its lifespan running."""

    clock = ManualClock(builders.NOW)
    container = build_memory_container(clock)
    services = build_services(container)
    builders.skip_classification(services.pipeline)
    app = make_app(container, services, mcp=True, text_max=100)
    async with running(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="https://lekto") as client:
            yield Api(container, services, app, client, clock)


@pytest.fixture
async def scene(api: Api) -> Scene:
    scene = await indexed_scene(api)
    for which in (scene.green, scene.yellow):
        await api.container.object_store.put(
            text_key(DocumentId(UUID(which))),
            TEXT.encode(),
            content_type="text/markdown",
        )
    return scene
