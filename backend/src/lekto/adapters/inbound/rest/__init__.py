"""REST API (FastAPI). The OpenAPI specification is the contract for all clients."""

from lekto.adapters.inbound.rest.app import PREFIX, close_event_streams, create_app
from lekto.adapters.inbound.rest.auth import current_user
from lekto.adapters.inbound.rest.context import ApiContext, HealthCheck
from lekto.adapters.inbound.rest.paths import HEALTH_PATH, MCP_PATH, OIDC_CALLBACK_PATH

__all__ = [
    "HEALTH_PATH",
    "MCP_PATH",
    "OIDC_CALLBACK_PATH",
    "PREFIX",
    "ApiContext",
    "HealthCheck",
    "close_event_streams",
    "create_app",
    "current_user",
]
