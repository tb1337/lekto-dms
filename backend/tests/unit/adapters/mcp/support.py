"""What the tests of the MCP endpoint share: running the app, calling tools, reading results."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from fastapi import FastAPI
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult

from lekto.adapters.inbound.rest import PREFIX
from tests.unit.adapters.rest.support import Api

URL = f"https://lekto{PREFIX}/mcp"
TEXT = "Strom Rechnung März\n" + "Zeile mit Inhalt\n" * 20


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[None]:
    """Run the app's lifespan in one task of its own (the SDK's task group must be entered and
    left in the same task, which a fixture's setup and teardown are not)."""
    ready, stop = asyncio.Event(), asyncio.Event()

    async def lifespan() -> None:
        async with app.router.lifespan_context(app):
            ready.set()
            await stop.wait()

    task = asyncio.create_task(lifespan())
    await asyncio.wait_for(ready.wait(), timeout=10)
    try:
        yield
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=10)


@asynccontextmanager
async def connected(api: Api, headers: dict[str, str]) -> AsyncIterator[Client]:
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=api.app), base_url="https://lekto", headers=headers
    )
    async with http, Client(streamable_http_client(URL, http_client=http)) as client:
        yield client


async def call(api: Api, headers: dict[str, str], tool: str, **arguments: Any) -> CallToolResult:
    async with connected(api, headers) as client:
        return await client.call_tool(tool, arguments)


def data(result: CallToolResult) -> dict[str, Any]:
    """A tool's result: compact JSON as text, no structured content (no output schemas)."""
    assert not result.is_error, result.content
    assert result.structured_content is None
    (part,) = result.content
    text = getattr(part, "text", "")
    parsed = json.loads(text)
    assert text == json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))  # compact
    return dict(parsed)


def error(result: CallToolResult) -> str:
    assert result.is_error
    return "".join(getattr(part, "text", "") for part in result.content)


async def listed_tools(api: Api, headers: dict[str, str]) -> list[dict[str, Any]]:
    """The tool definitions as they go out to a client, unparsed."""
    response = await api.client.post(
        f"{PREFIX}/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={
            **headers,
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
    )
    assert response.status_code == 200, response.text
    tools: list[dict[str, Any]] = response.json()["result"]["tools"]
    return tools
