"""`reparse`: read the text of every document again, after an update of the parser."""

from lekto.composition.container import build_container, build_services
from lekto.composition.settings import Settings


async def run_reparse(settings: Settings) -> int:
    """Queue a job for every document whose text can be read again; the worker reads them.
    Returns how many documents were queued."""
    container = build_container(settings)
    try:
        services = build_services(container, settings)
        return await services.pipeline.reparse()
    finally:
        await container.aclose()
