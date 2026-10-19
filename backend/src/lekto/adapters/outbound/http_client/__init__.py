"""What the adapters that speak HTTP over httpx2 share: describing a failure (without the URL,
whose path may carry a secret), a shortened excerpt of a service's error message, the host and
port of an endpoint, and the protocol of OpenAI-compatible endpoints (`openai`)."""

import ssl
from urllib.parse import urlsplit

import httpx2

EXCERPT = 300
"""Characters of a service's error message kept in an error."""
CONNECT_TIMEOUT = 5.0
"""Seconds to connect, within a request's limit."""


def excerpt(text: str) -> str:
    """`text` on one line, at most `EXCERPT` characters."""
    return " ".join(text.split())[:EXCERPT]


def describe_failure(failure: httpx2.HTTPError) -> str:
    """The kind of failure of a request, for an error or the log: TLS, time, connection,
    redirects, or the exception's name."""
    cause: BaseException | None = failure
    while cause is not None:
        if isinstance(cause, ssl.SSLCertVerificationError):
            return "the TLS certificate was not accepted"
        if isinstance(cause, ssl.SSLError):
            return "TLS handshake failed"
        cause = cause.__cause__ or cause.__context__
    if isinstance(failure, httpx2.TimeoutException):
        return "no answer in time"
    if isinstance(failure, httpx2.ConnectError):
        return "cannot connect"
    if isinstance(failure, httpx2.TooManyRedirects):
        return "too many redirects"
    return f"request failed: {type(failure).__name__}"


def endpoint_of(url: str) -> str:
    """Host and port of a URL, without credentials or path."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:  # IPv6
        host = f"[{host}]"
    return f"{host}:{parts.port}" if parts.port else host
