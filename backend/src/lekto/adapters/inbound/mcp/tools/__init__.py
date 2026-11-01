"""The tools, one module per domain (`registry.DOMAINS`)."""

from lekto.adapters.inbound.context import ApiContext
from lekto.adapters.inbound.mcp.registry import Tools
from lekto.adapters.inbound.mcp.tools.documents import add_document_tools
from lekto.adapters.inbound.mcp.tools.expected import add_expected_tools
from lekto.adapters.inbound.mcp.tools.master_data import add_master_data_tools


def add_tools(tools: Tools, context: ApiContext) -> None:
    add_document_tools(tools, context)
    add_master_data_tools(tools, context)
    add_expected_tools(tools, context)
