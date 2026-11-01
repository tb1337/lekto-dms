"""The tools, one module per domain (`registry.DOMAINS`)."""

from lekto.adapters.inbound.context import ApiContext
from lekto.adapters.inbound.mcp.registry import Tools
from lekto.adapters.inbound.mcp.tools.documents import add_document_tools
from lekto.adapters.inbound.mcp.tools.expected import add_expected_tools
from lekto.adapters.inbound.mcp.tools.facts import add_fact_tools
from lekto.adapters.inbound.mcp.tools.inbox import add_inbox_tools
from lekto.adapters.inbound.mcp.tools.listing import add_listing_tools
from lekto.adapters.inbound.mcp.tools.master_data import add_master_data_tools
from lekto.adapters.inbound.mcp.tools.spaces import add_space_tools


def add_tools(tools: Tools, context: ApiContext) -> None:
    add_document_tools(tools, context)
    add_listing_tools(tools, context)
    add_inbox_tools(tools, context)
    add_fact_tools(tools, context)
    add_master_data_tools(tools, context)
    add_space_tools(tools, context)
    add_expected_tools(tools, context)
