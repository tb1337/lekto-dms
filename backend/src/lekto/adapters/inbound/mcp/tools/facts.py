"""The tools of the domain `facts`: a person's decision about a number a document shows (Tobi,
01.11.2026, umsetzungsplan "MCP", PR 5). A correction at the contact changes master data and
stays in the web UI."""

from typing import Annotated, Literal

from mcp.server.mcpserver import Context
from pydantic import Field

from lekto.adapters.inbound.context import ApiContext
from lekto.adapters.inbound.mcp.names import Names, similar_names
from lekto.adapters.inbound.mcp.output import compact
from lekto.adapters.inbound.mcp.registry import Tools, principal_of
from lekto.adapters.inbound.mcp.tools.documents import FactsOut, facts_out
from lekto.core.domain.document_facts import FactRole
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import short_id
from lekto.core.services.fact_decisions import FactAction, FactDecision

type Action = Literal["add", "correct", "reject", "withdraw"]


def add_fact_tools(tools: Tools, context: ApiContext) -> None:
    @tools.write(
        "facts_decide",
        "Decide about a fact of a document (the kinds and roles as documents_get include facts "
        "shows them): add one (with role), correct its value (new_value) or role, reject it, "
        "or withdraw your decision. Answers the facts after it.",
        idempotent=True,
    )
    async def facts_decide(
        ctx: Context,
        id: str,
        action: Action,
        kind: str,
        value: Annotated[str, Field(min_length=1, max_length=200)],
        role: FactRole | None = None,
        new_value: Annotated[str | None, Field(min_length=1, max_length=200)] = None,
    ) -> str:
        principal = principal_of(ctx)
        user = principal.id
        document = await context.documents.resolve(user, id)
        decision = FactDecision(
            action=FactAction(action),
            kind=_kind(kind),
            value=value,
            role=role,
            new_value=new_value,
        )
        await context.documents.decide_fact(user, document, decision, via=principal.via)
        names = await Names.load(context, user)
        report = await context.documents.facts(user, document)
        return compact(FactsOut(id=short_id(document), facts=facts_out(report, names)))


def _kind(name: str) -> IdentifierKind:
    """The kind of fact `name` names; an error with similar ones for none (the kinds are many,
    their names in the schema would cost every conversation)."""
    try:
        return IdentifierKind(name.strip().lower())
    except ValueError:
        alike = similar_names(name, [kind.value for kind in IdentifierKind])
        hint = f"; similar: {', '.join(alike)}" if alike else ""
        raise ValidationError(f"no kind of fact named '{name}'{hint}") from None
