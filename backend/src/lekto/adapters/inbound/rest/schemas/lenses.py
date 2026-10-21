"""Lenses: a user's saved looks at the documents."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.core.domain.ids import (
    ContactId,
    DocumentTypeId,
    FieldId,
    SpaceId,
    TagId,
)
from lekto.core.domain.lenses import (
    MAX_CARD_FIELDS,
    MAX_FILTER_VALUES,
    MAX_NAME_LENGTH,
    MAX_QUERY_LENGTH,
    Grouping,
    Layout,
    Lens,
    LensFilter,
    LensSort,
    RelativePeriod,
)


def _ids() -> Any:
    """A list of ids of one kind, empty by default."""
    return Field(default_factory=list, max_length=MAX_FILTER_VALUES)


class LensFilterBody(BaseModel):
    """The filters as `GET /documents` takes them, with a list for each repeated parameter."""

    model_config = ConfigDict(extra="forbid")

    contact_ids: list[UUID] = _ids()
    document_type_ids: list[UUID] = _ids()
    contact_group_ids: list[UUID] = _ids()
    document_type_group_ids: list[UUID] = _ids()
    topic_ids: list[UUID] = _ids()
    tag_ids: list[UUID] = _ids()
    space_ids: list[UUID] = _ids()
    field_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None
    document_period: RelativePeriod | None = Field(
        default=None,
        description=(
            "A period that moves with the day the lens is opened; not together with "
            "`document_date_from` or `_to`."
        ),
    )

    def domain(self) -> LensFilter:
        return LensFilter(
            contact_ids=tuple(ContactId(id) for id in self.contact_ids),
            document_type_ids=tuple(DocumentTypeId(id) for id in self.document_type_ids),
            contact_group_ids=tuple(TagId(id) for id in self.contact_group_ids),
            document_type_group_ids=tuple(TagId(id) for id in self.document_type_group_ids),
            topic_ids=tuple(TagId(id) for id in self.topic_ids),
            tag_ids=tuple(TagId(id) for id in self.tag_ids),
            space_ids=tuple(SpaceId(id) for id in self.space_ids),
            field_id=None if self.field_id is None else FieldId(self.field_id),
            date_from=self.document_date_from,
            date_to=self.document_date_to,
            relative_period=self.document_period,
        )

    @classmethod
    def of(cls, filter: LensFilter) -> "LensFilterBody":
        return cls(
            contact_ids=list(filter.contact_ids),
            document_type_ids=list(filter.document_type_ids),
            contact_group_ids=list(filter.contact_group_ids),
            document_type_group_ids=list(filter.document_type_group_ids),
            topic_ids=list(filter.topic_ids),
            tag_ids=list(filter.tag_ids),
            space_ids=list(filter.space_ids),
            field_id=filter.field_id,
            document_date_from=filter.date_from,
            document_date_to=filter.date_to,
            document_period=filter.relative_period,
        )


SORT_HELP = (
    "`relevance` (only with `query`), or a key of `GET /documents`; `field` and `-field` sort "
    "by `sort_field_id` (not with `query`). None: as the list or the search sorts by default."
)
GROUPING_HELP = (
    "What the documents stand under: `month` of their document date, `due`: how soon "
    "`due_field_id` is due (overdue, within seven days, later, none), `document_type`, "
    "`contact`."
)
CARD_FIELDS_HELP = f"The fields a card shows, in this order; at most {MAX_CARD_FIELDS}."
DUE_HELP = "A date field: the deadline of the documents (yellow from seven days before, red after)."


class LensCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "To pay",
                    "filter": {"tag_ids": ["01a1f0c2-7c5e-7d43-9b1e-3c4b5d6e7f80"]},
                    "grouping": "due",
                    "due_field_id": "01a1f0c2-7c5e-7d43-9b1e-3c4b5d6e7f81",
                    "card_field_ids": [
                        "01a1f0c2-7c5e-7d43-9b1e-3c4b5d6e7f82",
                        "01a1f0c2-7c5e-7d43-9b1e-3c4b5d6e7f81",
                    ],
                }
            ]
        },
    )

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH, description="Unique per user.")
    filter: LensFilterBody = Field(default_factory=LensFilterBody)
    query: str | None = Field(default=None, max_length=MAX_QUERY_LENGTH, description="Words.")
    sort: LensSort | None = Field(default=None, description=SORT_HELP)
    sort_field_id: UUID | None = None
    grouping: Grouping = Field(default=Grouping.NONE, description=GROUPING_HELP)
    layout: Layout = Layout.GRID
    card_field_ids: list[UUID] = Field(
        default_factory=list, max_length=MAX_CARD_FIELDS, description=CARD_FIELDS_HELP
    )
    due_field_id: UUID | None = Field(default=None, description=DUE_HELP)


class LensPatch(BaseModel):
    """Parts left out stay as they are; `null` clears `query`, `sort`, `sort_field_id` and
    `due_field_id`."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"name": "Bills"}]})

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    filter: LensFilterBody | None = None
    query: str | None = Field(default=None, max_length=MAX_QUERY_LENGTH)
    sort: LensSort | None = Field(default=None, description=SORT_HELP)
    sort_field_id: UUID | None = None
    grouping: Grouping | None = Field(default=None, description=GROUPING_HELP)
    layout: Layout | None = None
    card_field_ids: list[UUID] | None = Field(
        default=None, max_length=MAX_CARD_FIELDS, description=CARD_FIELDS_HELP
    )
    due_field_id: UUID | None = Field(default=None, description=DUE_HELP)


class LensOrder(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "ids": [
                        "01a1f0c2-7c5e-7d43-9b1e-3c4b5d6e7f83",
                        "01a1f0c2-7c5e-7d43-9b1e-3c4b5d6e7f84",
                    ]
                }
            ]
        },
    )

    ids: list[UUID] = Field(description="Each of the caller's lenses once, in the new order.")


class LensOut(BaseModel):
    id: UUID
    name: str
    position: int = Field(description="Where it stands among the user's lenses, from 0.")
    filter: LensFilterBody
    query: str | None
    sort: LensSort | None
    sort_field_id: UUID | None
    grouping: Grouping
    layout: Layout
    card_field_ids: list[UUID]
    due_field_id: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, lens: Lens) -> "LensOut":
        return cls(
            id=lens.id,
            name=lens.name,
            position=lens.position,
            filter=LensFilterBody.of(lens.filter),
            query=lens.query,
            sort=lens.sort,
            sort_field_id=lens.sort_field_id,
            grouping=lens.grouping,
            layout=lens.layout,
            card_field_ids=list(lens.card_field_ids),
            due_field_id=lens.due_field_id,
            created_at=lens.created_at,
            updated_at=lens.updated_at,
        )
