"""Which tools there are, what each may do, and who sees it.

Every tool has a class: a `read` tool only reads, a `write` tool changes, but nothing a person
could not undo (Tobi, 01.11.2026: no deleting, moving or reprocessing; the client links to the
web UI for those). A token with scope `read` sees the read tools only, a tool for admins only
admins see. The list of tools is filtered per caller, and a call of a tool the caller does not
see is refused with the reason (`Visibility`).

A name is `<domain>_<verb>`: one of `DOMAINS`, then one of `VERBS`. The underscore separates
them; the protocol allows dots, but clients refuse them.
"""

import functools
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, ListToolsResult, TextContent, ToolAnnotations
from starlette.requests import Request

from lekto.core.domain.errors import DomainError, SearchUnavailableError
from lekto.core.services.auth import Principal

DOMAINS = (
    "documents",
    "document_types",
    "inbox",
    "facts",
    "relations",
    "contacts",
    "fields",
    "tags",
    "identifiers",
    "rules",
    "expected",
    "lenses",
    "spaces",
    "system",
)
VERBS = (
    "search",
    "list",
    "facets",
    "get",
    "text",
    "page",
    "log",
    "dry_run",
    "update",
    "retry",
    "confirm",
    "mark_seen",
    "decide",
    "set",
    "remove",
    "find",
    "open",
    "status",
)
MAX_NAME = 40
"""Characters of a name: Claude Code puts `mcp__lekto__` before it, and 64 is the limit."""


class ToolClass(StrEnum):
    READ = "read"
    WRITE = "write"


def split_name(name: str) -> tuple[str, str] | None:
    """Domain and verb of a tool name; None if it is not one of each."""
    for domain in DOMAINS:
        verb = name.removeprefix(domain + "_")
        if verb != name and verb in VERBS:
            return domain, verb
    return None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    tool_class: ToolClass
    admin: bool = False
    idempotent: bool = False

    def __post_init__(self) -> None:
        if len(self.name) > MAX_NAME or split_name(self.name) is None:
            raise ValueError(f"tool name {self.name!r} is not <domain>_<verb>")

    @property
    def annotations(self) -> ToolAnnotations:
        if self.tool_class is ToolClass.READ:
            return ToolAnnotations(read_only_hint=True, open_world_hint=False)
        return ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=self.idempotent,
            open_world_hint=False,
        )

    def refusal(self, principal: Principal | None) -> str | None:
        """Why `principal` may not use the tool; None if they may."""
        if principal is None:
            return "authentication is required"
        if self.tool_class is ToolClass.WRITE and not principal.can_write:
            return "this API token may only read"
        if self.admin and not principal.user.is_active_admin:
            return "only admins may use this tool"
        return None


type Tool = Callable[..., Awaitable[Any]]


class Tools:
    """Adds tools to the server with their class, and puts them into `specs` (which
    `Visibility` reads)."""

    def __init__(self, server: MCPServer, specs: dict[str, ToolSpec]) -> None:
        self._server = server
        self._specs = specs

    def read(self, name: str, description: str, *, admin: bool = False) -> Callable[[Tool], Tool]:
        return self._add(ToolSpec(name, ToolClass.READ, admin=admin), description)

    def write(
        self, name: str, description: str, *, idempotent: bool, admin: bool = False
    ) -> Callable[[Tool], Tool]:
        spec = ToolSpec(name, ToolClass.WRITE, admin=admin, idempotent=idempotent)
        return self._add(spec, description)

    def _add(self, spec: ToolSpec, description: str) -> Callable[[Tool], Tool]:
        def add(tool: Tool) -> Tool:
            self._server.tool(
                name=spec.name,
                description=description,
                annotations=spec.annotations,
                # What a tool returns is its text (`output.compact`); an output schema would
                # more than double the definitions every conversation loads.
                structured_output=False,
            )(_guarded(tool))
            self._specs[spec.name] = spec
            return tool

        return add


def _guarded(tool: Tool) -> Tool:
    """Turn the core's errors into the tool's error text."""

    @functools.wraps(tool)
    async def run(*args: Any, **kwargs: Any) -> Any:
        try:
            return await tool(*args, **kwargs)
        except SearchUnavailableError:
            raise ToolError("search is not available") from None
        except DomainError as error:
            raise ToolError(str(error)) from None

    return run


def principal_of(ctx: Context) -> Principal:
    """The caller, put there by the bearer check in front of the server."""
    principal = _principal(ctx.request_context.request)
    if principal is None:
        raise ToolError("authentication is required")
    return principal


def _principal(request: object) -> Principal | None:
    principal = getattr(getattr(request, "state", None), "principal", None)
    if not isinstance(request, Request) or not isinstance(principal, Principal):
        return None
    return principal


class Visibility:
    """Middleware: lists the tools the caller may use, and refuses a call of any other. The list
    leaves out the titles pydantic gives every schema and parameter: they repeat the names, and
    the definitions are loaded into every conversation (the SDK checks arguments against the
    schemas as they were registered)."""

    def __init__(self, specs: Mapping[str, ToolSpec]) -> None:
        self._specs = specs

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        principal = _principal(ctx.request)
        if ctx.method == "tools/call":
            spec = self._specs.get(str((ctx.params or {}).get("name")))
            refusal = None if spec is None else spec.refusal(principal)
            if refusal is not None:
                text = TextContent(type="text", text=refusal)
                return CallToolResult(content=[text], is_error=True)
            return await call_next(ctx)
        result = await call_next(ctx)
        if ctx.method != "tools/list":
            return result
        # The chain hands the list on as the dictionary that goes out (its cache scope is
        # `private`: per caller); the model only in case that changes.
        if isinstance(result, ListToolsResult):
            result = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        if isinstance(result, dict) and isinstance(result.get("tools"), list):
            listed: list[dict[str, Any]] = result["tools"]
            tools = [_untitled(tool) for tool in listed if self._sees(tool.get("name"), principal)]
            return {**result, "tools": tools}
        return result

    def _sees(self, name: object, principal: Principal | None) -> bool:
        spec = self._specs.get(name) if isinstance(name, str) else None
        return spec is not None and spec.refusal(principal) is None


def _untitled(value: Any) -> Any:
    """`value` without the key `title` where it is text: a schema's title, not a parameter
    named so (in `properties` that is a schema)."""
    if isinstance(value, dict):
        return {
            key: _untitled(item)
            for key, item in value.items()
            if not (key == "title" and isinstance(item, str))
        }
    if isinstance(value, list):
        return [_untitled(item) for item in value]
    return value
