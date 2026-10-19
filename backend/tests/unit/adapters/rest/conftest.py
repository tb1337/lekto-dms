"""The API on in-memory adapters (`support.Api`). Callers authenticate for real: test users get
an API token (`tests.api.auth`) or sign in with their password (`Api.sign_in`)."""

from collections.abc import AsyncIterator

import httpx2
import pytest

from lekto.adapters.outbound.memory import ManualClock
from lekto.composition.container import build_memory_container, build_services
from tests import builders
from tests.unit.adapters.rest.support import Api, make_app


@pytest.fixture
async def api() -> AsyncIterator[Api]:
    clock = ManualClock(builders.NOW)
    container = build_memory_container(clock)
    services = build_services(container)
    builders.skip_classification(services.pipeline)
    app = make_app(container, services)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://papiq") as client:
        yield Api(container, services, app, client, clock)
