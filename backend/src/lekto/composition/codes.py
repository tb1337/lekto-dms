"""`read-codes`: queue reading the facts of documents from before codes were read."""

from lekto.composition.container import build_container, build_services
from lekto.composition.settings import Settings


async def run_read_codes(settings: Settings) -> int:
    """Queue reading the facts of every document with a text: the worker reads the codes on its
    pages and keeps the identifiers it shows. Returns how many documents were queued."""
    container = build_container(settings)
    try:
        services = build_services(container, settings)
        return await services.pipeline.request_facts()
    finally:
        await container.aclose()
