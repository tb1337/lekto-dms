"""The tools of the domain `inbox`: what waits for the caller, confirming it, marking it seen
(Tobi, 01.11.2026, umsetzungsplan "MCP", PR 5). Where a document belongs is the person's to
decide in the web UI: an assistant does not move documents (decision 3)."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from lekto.adapters.inbound.context import ApiContext
from lekto.adapters.inbound.mcp.names import Names
from lekto.adapters.inbound.mcp.output import compact
from lekto.adapters.inbound.mcp.registry import Tools, principal_of
from lekto.adapters.inbound.mcp.tools.documents import (
    ChangesIn,
    OpenOut,
    UpdateOut,
    changes_of,
    open_out,
    update_out,
)
from lekto.core.domain.classification import SPACE
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import short_id
from lekto.core.domain.inbox import InboxTab

INBOX_SIZE = 20
"""Documents one page of the inbox returns unless the client asks for more."""
INBOX_MAX = 50

type TabName = Literal["new", "review", "intervene", "processing", "done"]


class DoneOut(BaseModel):
    how: str
    at: datetime
    by: str | None
    via_token: str | None


class InboxItemOut(BaseModel):
    id: str
    title: str
    tab: str
    contact: str | None
    document_type: str | None
    document_date: date | None
    open: list[OpenOut]
    done: DoneOut | None


class InboxOut(BaseModel):
    counts: dict[str, int]
    items: list[InboxItemOut]
    next_after: str | None


def add_inbox_tools(tools: Tools, context: ApiContext) -> None:
    @tools.read(
        "inbox_list",
        "What waits for you, newest first: review (yellow: a person should check), intervene "
        "(red: processing failed), new (green, not seen yet), processing; done: what left it "
        "in 14 days. Each with what is open and why. counts: per tab.",
    )
    async def inbox_list(
        ctx: Context,
        tab: TabName | None = None,
        limit: Annotated[int, Field(ge=1, le=INBOX_MAX)] = INBOX_SIZE,
        after: Annotated[str | None, Field(description="next_after of the page before.")] = None,
    ) -> str:
        user = principal_of(ctx).id
        names = await Names.load(context, user)
        position = None if after is None else await context.documents.resolve(user, after)
        items = await context.inbox.items(
            user,
            tab=None if tab is None else InboxTab(tab),
            after=position,
            limit=limit,
        )
        summary = await context.inbox.summary(user)
        people = {person.id: person.label for person in await context.users.list_users(user)}
        return compact(
            InboxOut(
                counts={tab.value: count for tab, count in summary.counts.items()},
                items=[
                    InboxItemOut(
                        id=short_id(item.document.id),
                        title=item.document.title,
                        tab=item.state.tab.value,
                        contact=names.contact(item.document.contact_id),
                        document_type=names.document_type(item.document.document_type_id),
                        document_date=item.document.document_date,
                        open=[open_out(node, names) for node in item.open],
                        done=(
                            None
                            if item.state.done is None
                            else DoneOut(
                                how=item.state.done.how.value,
                                at=item.state.done.at,
                                by=people.get(item.state.done.by, "a former account"),
                                via_token=(
                                    None
                                    if item.state.done.via is None
                                    else item.state.done.via.name
                                ),
                            )
                        ),
                    )
                    for item in items
                ],
                next_after=short_id(items[-1].document.id) if len(items) == limit else None,
            )
        )

    @tools.write(
        "inbox_confirm",
        "Confirm a yellow or red document: every open field needs a decision. changes: the "
        "values you decide, keys as in documents_update; accept_suggestions takes the "
        "suggestions for the rest; a value it has is kept. Processing goes on to filing. "
        "Where it belongs (space) is the person's to decide in the web UI.",
        idempotent=False,
    )
    async def inbox_confirm(
        ctx: Context,
        id: str,
        changes: dict[str, Any] | None = None,
        accept_suggestions: bool = False,
    ) -> str:
        principal = principal_of(ctx)
        user = principal.id
        names = await Names.load(context, user)
        document = await context.documents.resolve(user, id)
        try:
            given = ChangesIn.model_validate(changes or {})
        except PydanticValidationError as error:
            raise ValidationError(f"changes: {_first(error)}") from None
        review = await context.documents.review(user, document)
        if any(check.field == SPACE for node in review.open for check in node.fields):
            raise ValidationError(
                "where the document belongs is open: the person decides it in the web UI"
            )
        before = review.document
        view = await context.pipeline.confirm(
            user,
            document,
            changes_of(given, names),
            accept_suggestions=accept_suggestions,
            via=principal.via,
        )
        if view is None:
            return compact(UpdateOut(id=short_id(document), filed_away=True))
        return compact(update_out(before, view.document, view.access, names))

    @tools.write(
        "inbox_mark_seen",
        "Mark a new document as seen, so it leaves your inbox (seen: false makes it new "
        "again). Seen changes nothing else.",
        idempotent=True,
    )
    async def inbox_mark_seen(ctx: Context, id: str, seen: bool = True) -> str:
        principal = principal_of(ctx)
        document = await context.documents.resolve(principal.id, id)
        if seen:
            await context.inbox.mark_seen(principal.id, document, via=principal.via)
        else:
            await context.inbox.mark_unseen(principal.id, document)
        return compact(UpdateOut(id=short_id(document)))


def _first(error: PydanticValidationError) -> str:
    problem = error.errors()[0]
    where = ".".join(str(part) for part in problem["loc"])
    return f"{where}: {problem['msg']}" if where else str(problem["msg"])
