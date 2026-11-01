"""The tools that look at many documents: list them by filters, or count and sum them (Tobi,
01.11.2026, umsetzungsplan "MCP", decisions 1 and 7: "Was habe ich 2025 für Strom bezahlt?" is
answered by the server, not by adding up a hundred answers)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from mcp.server.mcpserver import Context
from pydantic import BaseModel, Field

from lekto.adapters.inbound.context import ApiContext
from lekto.adapters.inbound.mcp.names import Names, find
from lekto.adapters.inbound.mcp.output import compact
from lekto.adapters.inbound.mcp.registry import Tools, principal_of
from lekto.adapters.inbound.schemas import FieldJson, field_json
from lekto.core.domain.aggregates import Aggregate, GroupBy, GroupKey
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import FieldType
from lekto.core.domain.ids import FieldId, LensId, UserId, short_id
from lekto.core.domain.periods import Period
from lekto.core.domain.pipeline import Lane
from lekto.core.ports.repository import DocumentFilter

LIST_SIZE = 20
"""Documents one list returns unless the client asks for more."""
LIST_MAX = 50

type LaneName = Literal["green", "yellow", "red", "processing"]
type GroupName = Literal["year", "month", "contact", "document_type", "topic", "tag"]

_LANES: dict[str, Lane | None] = {"green": Lane.GREEN, "yellow": Lane.YELLOW, "red": Lane.RED}


class ListItem(BaseModel):
    id: str
    title: str
    lane: str | None
    contact: str | None
    document_type: str | None
    topic: str | None
    tags: list[str]
    document_date: date | None
    fields: dict[str, FieldJson]


class ListOut(BaseModel):
    items: list[ListItem]
    next_offset: int | None


class GroupOut(BaseModel):
    key: str | None  # none: without one
    count: int
    sum: dict[str, Decimal]


class CountOut(BaseModel):
    count: int
    sum: dict[str, Decimal]
    groups: list[GroupOut] | None
    hits_only: bool | None  # words: as far as the search reaches


def add_listing_tools(tools: Tools, context: ApiContext) -> None:
    @tools.read(
        "documents_list",
        "Documents by filters, newest first; or, with group_by or sum, counted: count and the "
        "sum of an amount field per currency, per group too. Filters by name as in "
        "documents_search, lane, document_date_from/_to (YYYY-MM-DD); query: with these "
        "words; lens: the filters of a lens (others given replace its own). fields: names of "
        "fields to show.",
    )
    async def documents_list(
        ctx: Context,
        contact: str | None = None,
        document_type: str | None = None,
        tags: Annotated[list[str] | None, Field(max_length=50)] = None,
        topics: Annotated[list[str] | None, Field(max_length=50)] = None,
        lane: LaneName | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
        query: Annotated[str | None, Field(min_length=1, max_length=500)] = None,
        lens: str | None = None,
        group_by: GroupName | None = None,
        sum: str | None = None,
        fields: Annotated[list[str] | None, Field(max_length=10)] = None,
        limit: Annotated[int, Field(ge=1, le=LIST_MAX)] = LIST_SIZE,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> str:
        user = principal_of(ctx).id
        names = await Names.load(context, user)
        filter, words = await _lens(context, user, lens)
        if contact is not None:
            filter = replace(filter, contacts=frozenset({names.find_contact(contact)}))
        if document_type is not None:
            chosen = frozenset({names.find_document_type(document_type)})
            filter = replace(filter, document_types=chosen)
        if tags:
            filter = replace(filter, tags=tuple(frozenset({names.find_tag(t)}) for t in tags))
        if topics:
            filter = replace(filter, topics=frozenset(names.find_topic(t) for t in topics))
        if lane is not None:
            filter = replace(filter, lanes=frozenset({_LANES.get(lane)}))
        if document_date_from is not None or document_date_to is not None:
            period = Period(document_date_from or date.min, document_date_to or date.max)
            filter = replace(filter, document_dates=period)
        words = query or words
        if group_by is not None or sum is not None:
            amount = None if sum is None else _amount(names, sum)
            among = (
                None if words is None else await context.require_search().hits(user, words, filter)
            )
            counted = await context.documents.aggregate(
                user,
                filter,
                by=None if group_by is None else GroupBy(group_by),
                amount=amount,
                among=among,
            )
            return compact(_counted(counted, group_by, names, words is not None))
        shown = [names.find_field(name).id for name in fields or ()]
        if words is not None:
            page = await context.require_search().search(
                user, words, filter, offset=offset, limit=limit
            )
            documents = [item.document for item in page.items]
            following = page.next_offset
        else:
            listed = await context.documents.query(user, filter, offset=offset, limit=limit + 1)
            documents = [item.document for item in listed[:limit]]
            following = offset + limit if len(listed) > limit else None
        return compact(
            ListOut(
                items=[
                    ListItem(
                        id=short_id(document.id),
                        title=document.title,
                        lane=None if document.lane is None else document.lane.value,
                        contact=names.contact(document.contact_id),
                        document_type=names.document_type(document.document_type_id),
                        topic=names.topic(document.topic_id),
                        tags=names.tag_names(document.tag_ids),
                        document_date=document.document_date,
                        fields={
                            names.field_name(id): field_json(document.fields[id])
                            for id in shown
                            if id in document.fields
                        },
                    )
                    for document in documents
                ],
                next_offset=following,
            )
        )


async def _lens(
    context: ApiContext, user: UserId, name: str | None
) -> tuple[DocumentFilter, str | None]:
    """The filter and the words of the caller's lens named `name`; none without a name."""
    if name is None:
        return DocumentFilter(), None
    lenses = {lens.id: lens for lens in await context.lenses.list_lenses(user)}
    lens = lenses[LensId(find("lens", name, {id: lens.name for id, lens in lenses.items()}))]
    return context.lenses.documents_of(lens), lens.query


def _amount(names: Names, name: str) -> FieldId:
    definition = names.find_field(name)
    if definition.data_type is not FieldType.AMOUNT:
        raise ValidationError(f"the field '{definition.name}' holds no amount")
    return definition.id


def _counted(counted: Aggregate, by: GroupName | None, names: Names, words: bool) -> CountOut:
    def key(value: GroupKey) -> str | None:
        if value is None or isinstance(value, str):
            return value
        match by:
            case "contact":
                return names.contact(value)
            case "document_type":
                return names.document_type(value)
            case "topic":
                return names.topic(value)
        return next(iter(names.tag_names([value])), None)

    return CountOut(
        count=counted.total,
        sum=counted.sums,
        groups=(
            None
            if counted.groups is None
            else [GroupOut(key=key(g.key), count=g.count, sum=g.sums) for g in counted.groups]
        ),
        hits_only=True if words else None,
    )
