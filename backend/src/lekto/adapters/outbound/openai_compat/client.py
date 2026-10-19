"""OpenAI-compatible chat completions and embeddings over httpx2.

Works with Ollama (`http://host:11434/v1`) and cloud providers that follow the OpenAI API. The
base URL includes the version path; `/chat/completions` and `/embeddings` are appended
(`http_client.openai`).

- One client per adapter keeps its connections; the composition closes it (`aclose`).
- `timeout` limits a whole request, from sending to the last byte of the answer.
- Structured output: `response_format` `json_schema` (strict) by default; `json_object` for
  providers that only promise JSON. The answer is not checked here (see the port).
- No retries of its own: failures raise, and the pipeline's retry policy repeats the node.
- Neither the API key nor document content is logged; errors carry the HTTP status and a short
  excerpt of the provider's message.
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Any, Literal

import httpx2

from lekto.adapters.outbound.http_client import endpoint_of
from lekto.adapters.outbound.http_client.openai import (
    ProtocolError,
    answer_content,
    auth_headers,
    chat_url,
    embeddings_url,
    response_object,
)
from lekto.core.domain.errors import EmbeddingsError, LanguageModelError
from lekto.core.ports.embeddings import EmbeddingResult
from lekto.core.ports.llm import StructuredAnswer, StructuredRequest

log = logging.getLogger(__name__)

type ResponseFormat = Literal["json_schema", "json_object"]


class OpenAiCompatLanguageModel:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        temperature: float | None,
        seed: int | None = None,
        timeout: float,
        response_format: ResponseFormat,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """`temperature` None leaves it to the endpoint (some models reject one); `timeout` in
        seconds. The composition takes them from the settings. `transport` replaces the
        network in tests."""
        self._model = model
        self._temperature = temperature
        self._seed = seed
        self._format = response_format
        self._endpoint = endpoint_of(base_url)
        self._client = _Client(chat_url(base_url), api_key, timeout, transport, LanguageModelError)

    @property
    def model(self) -> str:
        return self._model

    @property
    def endpoint(self) -> str:
        return self._endpoint

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(self, request: StructuredRequest) -> StructuredAnswer:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "stream": False,
            "response_format": self._response_format(request),
        }
        if self._temperature is not None:
            body["temperature"] = self._temperature
        if self._seed is not None:
            body["seed"] = self._seed
        data = await self._client.post(body)
        try:
            content = answer_content(data)
        except ProtocolError:
            raise LanguageModelError("the language model sent an unusable response") from None
        usage = data.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        return StructuredAnswer(
            content=content,
            model=str(data.get("model") or self._model),
            fingerprint=_optional_text(data.get("system_fingerprint")),
            usage=usage,
        )

    def _response_format(self, request: StructuredRequest) -> dict[str, Any]:
        if self._format == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {"name": request.schema_name, "schema": request.schema, "strict": True},
        }


class OpenAiCompatEmbeddings:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """`timeout` in seconds, from the settings. `transport` replaces the network in
        tests."""
        self._model = model
        self._client = _Client(
            embeddings_url(base_url), api_key, timeout, transport, EmbeddingsError
        )

    @property
    def model(self) -> str:
        return self._model

    async def aclose(self) -> None:
        await self._client.aclose()

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[], model=self._model)
        body = {"model": self._model, "input": list(texts)}
        data = await self._client.post(body)
        try:
            items = sorted(data["data"], key=lambda item: int(item["index"]))
            vectors = [tuple(float(value) for value in item["embedding"]) for item in items]
        except (KeyError, TypeError, ValueError):
            raise EmbeddingsError("the embedding model sent an unusable response") from None
        if [int(item["index"]) for item in items] != list(range(len(texts))):
            raise EmbeddingsError(f"expected {len(texts)} vectors, got {len(vectors)}")
        if len({len(vector) for vector in vectors}) != 1 or not vectors[0]:
            raise EmbeddingsError("the embedding model sent vectors of different length")
        return EmbeddingResult(vectors=vectors, model=str(data.get("model") or self._model))


class _Client:
    """POSTs JSON to one URL of an endpoint and returns the JSON object of the answer; `error`
    for anything else."""

    def __init__(
        self,
        url: str,
        api_key: str | None,
        timeout: float,
        transport: httpx2.AsyncBaseTransport | None,
        error: type[LanguageModelError] | type[EmbeddingsError],
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._error = error
        self._client = httpx2.AsyncClient(
            transport=transport, timeout=timeout, headers=auth_headers(api_key)
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def post(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with asyncio.timeout(self._timeout):
                response = await self._client.post(self._url, json=body)
        except (TimeoutError, httpx2.TimeoutException):
            raise self._error(f"no answer within {self._timeout:g} seconds") from None
        except httpx2.HTTPError as failure:
            endpoint = endpoint_of(self._url)
            raise self._error(f"cannot reach {endpoint}: {type(failure).__name__}") from None
        try:
            return response_object(response)
        except ProtocolError as problem:
            raise self._error(str(problem)) from None


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
