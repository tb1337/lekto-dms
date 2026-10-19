"""`render-pages`: queue the page images of documents from before the pages node existed."""

from lekto.composition.container import build_container, build_services
from lekto.composition.settings import Settings
from lekto.core.domain.pipeline import Node


async def run_render_pages(settings: Settings) -> int:
    """Queue a catch-up job for every document whose pages were skipped; the worker renders
    them. Returns how many documents were queued."""
    container = build_container(settings)
    try:
        services = build_services(container, settings)
        return await services.pipeline.catch_up(Node.PAGES)
    finally:
        await container.aclose()
