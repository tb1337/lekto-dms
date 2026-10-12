"""The bearer token of a request, as the REST API and the MCP endpoint read it."""

from papiq.core.domain.errors import AuthenticationError


def bearer_token(header: str) -> str:
    """The token of an `Authorization: Bearer <token>` header value; AuthenticationError for
    any other scheme or an empty token."""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("authentication is required")
    return token.strip()
