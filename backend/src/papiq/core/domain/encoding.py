"""Encodings for URLs and cookies: base64url without padding (RFC 4648, section 5), the PKCE
challenge made with it (RFC 7636), and the parameters of a URL's query."""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit


def base64url(data: bytes) -> str:
    """`data` in the URL-safe base64 alphabet, without `=` padding."""
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def from_base64url(text: str) -> bytes:
    """The bytes of `base64url`, padding optional. Raises ValueError."""
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def pkce_challenge(verifier: str) -> str:
    """The S256 code challenge of a PKCE code verifier."""
    return base64url(hashlib.sha256(verifier.encode()).digest())


def query_parameters(url: str) -> dict[str, str]:
    """The parameters of the query of `url`, each with its first value."""
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
