"""`read-facts`: queue reading the facts of every document again."""

from lekto.composition.container import build_container, build_services
from lekto.composition.settings import Settings


async def run_read_facts(settings: Settings) -> int:
    """Queue reading the facts of every document with a text again: the worker reads the codes
    on its pages and the identifiers its text shows, with their holders. Returns how many
    documents were queued."""
    container = build_container(settings)
    try:
        services = build_services(container, settings)
        return await services.pipeline.request_facts()
    finally:
        await container.aclose()
