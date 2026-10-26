"""`relate`: queue finding the relations of documents from before the node `relate`."""

from lekto.composition.container import build_container, build_services
from lekto.composition.settings import Settings


async def run_relate(settings: Settings) -> int:
    """Queue finding the relations of every document that is not being processed: the worker
    relates it with the documents it refers to and those that refer to it. Returns how many
    documents were queued."""
    container = build_container(settings)
    try:
        services = build_services(container, settings)
        return await services.pipeline.request_relations()
    finally:
        await container.aclose()
