"""The parts of the OpenAI API that the language model, the embeddings and the vision language
model (in OCRmyPDF's process) share: the URLs below the base URL (which includes the version
path), the key as a bearer token, a response's JSON object or the provider's error, and the
content of a chat answer."""

from typing import Any

import httpx2

from lekto.adapters.outbound.http_client import excerpt


class ProtocolError(Exception):
    """The endpoint answered, but not with what the API promises; the message says how."""


def chat_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def embeddings_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/embeddings"


def auth_headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def response_object(response: httpx2.Response) -> dict[str, Any]:
    """The JSON object of a response; ProtocolError for an error status (with the provider's
    message) or a body that is no JSON object."""
    if response.status_code >= 400:
        raise ProtocolError(f"HTTP {response.status_code}: {provider_message(response)}")
    try:
        data = response.json()
    except ValueError:
        raise ProtocolError("the response is not JSON") from None
    if not isinstance(data, dict):
        raise ProtocolError("the response is not a JSON object")
    return data


def provider_message(response: httpx2.Response) -> str:
    """The provider's error message (`{"error": {"message": ...}}` or `{"error": ...}`),
    shortened; the raw body if it is not the usual JSON."""
    try:
        data = response.json()
        detail = data["error"]["message"] if isinstance(data["error"], dict) else data["error"]
        text = str(detail)
    except (ValueError, KeyError, TypeError):
        text = response.text
    return excerpt(text) or response.reason_phrase


def answer_content(data: dict[str, Any]) -> str:
    """The text of the first choice of a chat answer (empty if it has none); ProtocolError if
    the answer has no choice with a message."""
    try:
        content = data["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        raise ProtocolError("unusable response") from None
    return content if isinstance(content, str) else ""
