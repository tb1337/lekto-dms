"""Guards of the tools as a whole (Tobi, 01.11.2026, umsetzungsplan "MCP"): their names, the
budget of their definitions, and their documentation."""

import json
import re
from pathlib import Path

from lekto.adapters.inbound.mcp.registry import MAX_NAME, split_name
from tests.unit.adapters.mcp.support import listed_tools
from tests.unit.adapters.rest.support import Api, Scene

BUDGET = 20_000
"""Characters of all tool definitions as a client receives them (about 5,000 tokens): they are
loaded into every conversation. Write descriptions short and put what all tools share into the
instructions before raising it."""

README = Path(__file__).parents[4] / "README.md"
_SECTION = re.compile(r"^## MCP\n(.*?)(?=^## )", re.MULTILINE | re.DOTALL)
_ROW = re.compile(r"^\| `([a-z_]+)` \| (read|write) \| ", re.MULTILINE)


async def test_the_definitions_stay_within_their_budget(api: Api, scene: Scene) -> None:
    tools = await listed_tools(api, scene.headers["admin"])
    size = len(json.dumps(tools, ensure_ascii=False, separators=(",", ":")))
    assert size <= BUDGET, f"the tool definitions take {size} characters, the budget is {BUDGET}"
    for tool in tools:
        assert "outputSchema" not in tool, tool["name"]
        assert "title" not in tool["inputSchema"], tool["name"]


async def test_every_name_is_a_domain_and_a_verb(api: Api, scene: Scene) -> None:
    for tool in await listed_tools(api, scene.headers["admin"]):
        assert split_name(tool["name"]) is not None, tool["name"]
        assert len(tool["name"]) <= MAX_NAME, tool["name"]


async def test_every_tool_is_documented_with_its_class(api: Api, scene: Scene) -> None:
    """backend/README.md, section MCP: one row per tool with its class, read or write."""
    tools = await listed_tools(api, scene.headers["admin"])
    expected = {
        tool["name"]: "read" if tool["annotations"].get("readOnlyHint") else "write"
        for tool in tools
    }
    section = _SECTION.search(README.read_text(encoding="utf-8"))
    assert section is not None, "README.md has no section MCP"
    documented = dict(_ROW.findall(section.group(1)))
    assert documented == expected
