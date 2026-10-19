"""MCP server over HTTP with bearer tokens; uses the same services as the REST API."""

from lekto.adapters.inbound.mcp.app import McpEndpoint

__all__ = ["McpEndpoint"]
