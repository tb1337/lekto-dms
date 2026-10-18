import secrets
from collections.abc import AsyncIterator

import pytest

from papiq.adapters.outbound.meilisearch import MeilisearchIndex
from papiq.composition.settings import Settings
from tests.integration.services import drop, new_index


@pytest.fixture
async def search_index(meilisearch_settings: Settings) -> AsyncIterator[MeilisearchIndex]:
    """An empty index of its own that takes vectors of `DIMENSIONS` numbers; removed afterwards."""
    name = f"papiq-test-{secrets.token_hex(6)}"
    index = new_index(meilisearch_settings, name)
    try:
        yield index
    finally:
        await index.aclose()
        await drop(meilisearch_settings, name, f"{name}-rebuild")
