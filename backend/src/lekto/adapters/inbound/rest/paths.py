"""Where the API lives, for the app and for answers that link to it."""

PREFIX = "/api/v1"

HEALTH_PATH = f"{PREFIX}/health"
"""The health check: public, and left out of the access log."""
OIDC_CALLBACK_PATH = f"{PREFIX}/auth/oidc/callback"
"""Where the identity provider sends the browser back (the redirect URI); the access log leaves
out its query."""
MCP_PATH = f"{PREFIX}/mcp"
"""The MCP endpoint, mounted beside the API's routes."""


def logo_url(contact: object, version: int) -> str:
    """The logo of a contact (`GET /contacts/{id}/logo`), with its version: a new logo is a new
    URL, so a browser may keep one as long as it likes."""
    return f"{PREFIX}/contacts/{contact}/logo?v={version}"
