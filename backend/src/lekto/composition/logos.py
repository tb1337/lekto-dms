"""`fetch-logos`: queue fetching the logos of contacts from their websites."""

from lekto.composition.container import build_container, build_services
from lekto.composition.errors import ConfigurationError
from lekto.composition.settings import Settings
from lekto.core.domain.errors import LogoFetchDisabledError


async def run_fetch_logos(settings: Settings) -> int:
    """Queue a fetch for every contact without a logo that has a domain whose fetch has not
    failed; the worker fetches. Returns how many were queued. ConfigurationError without
    `LEKTO_LOGO_FETCH`."""
    container = build_container(settings)
    try:
        return await build_services(container, settings).logos.request_all()
    except LogoFetchDisabledError as error:
        raise ConfigurationError(f"{error}: set LEKTO_LOGO_FETCH=true") from None
    finally:
        await container.aclose()
