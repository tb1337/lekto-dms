"""The tools of the master data: contacts, document types, fields and tags, read only (Tobi,
01.11.2026: master data is changed in the web UI)."""

from typing import Annotated, Literal

from mcp.server.mcpserver import Context
from pydantic import BaseModel, Field

from lekto.adapters.inbound.context import ApiContext
from lekto.adapters.inbound.mcp.output import compact
from lekto.adapters.inbound.mcp.registry import Tools, principal_of
from lekto.core.domain.master_data import TagScope
from lekto.core.domain.tag_tree import TagTree

PATH_SEPARATOR = " / "
type Scope = Literal["document", "contact", "document_type", "topic"]
"""`TagScope` as a parameter: the enum would put its docstring into the schema."""


class TagsOut(BaseModel):
    """The tags of each scope asked for, each as its path from the top-level tag down."""

    document: list[str] | None = None
    contact: list[str] | None = None
    document_type: list[str] | None = None
    topic: list[str] | None = None


def add_master_data_tools(tools: Tools, context: ApiContext) -> None:
    @tools.read(
        "tags_list",
        "The tags by scope, in the order of their trees, each as its path from the top ' / ' "
        "between names; the other tools take a tag's own name. document: tags of documents "
        "(a tag finds those below it too); topic: topics (the topic of a document); contact "
        "and document_type: groups of contacts and types.",
    )
    async def tags_list(
        ctx: Context, scope: Annotated[Scope | None, Field(description="Default: all.")] = None
    ) -> str:
        user = principal_of(ctx).id
        tree = TagTree.of(await context.master_data.list_tags(user))
        scopes = list(TagScope) if scope is None else [TagScope(scope)]
        return compact(
            TagsOut.model_validate(
                {
                    wanted.value: [
                        PATH_SEPARATOR.join(tree.path(tag.id)) for tag in tree.of_scope(wanted)
                    ]
                    for wanted in scopes
                }
            )
        )
