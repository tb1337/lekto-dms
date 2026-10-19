"""Query parameters that routes share: the filter of documents (`GET /documents`,
`GET /documents/search`), the switches to every user's documents and rules (`all_users`), and
document counts; and how their descriptions say who may call them."""

from datetime import date
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query
from fastapi.exceptions import RequestValidationError

from lekto.core.domain.ids import ContactId, DocumentTypeId, FieldId, SpaceId, TagId
from lekto.core.domain.periods import Period
from lekto.core.domain.pipeline import Lane
from lekto.core.domain.search import PROCESSING, lane_value
from lekto.core.ports.repository import DocumentFilter

ADMINS_ONLY = "Admins only."
SESSION_ONLY_NOTE = " Needs a session; API tokens are refused (403)."

MAX_IDS = 50
"""Ids of one kind a filter names at most."""


class LaneFilter(StrEnum):
    """A lane, or `processing`: documents that have no lane yet."""

    GREEN = Lane.GREEN.value
    YELLOW = Lane.YELLOW.value
    RED = Lane.RED.value
    PROCESSING = PROCESSING


# Every lane, and none, as the API names it (a lane without a member fails here, at import).
_LANES: dict[LaneFilter, Lane | None] = {
    LaneFilter(lane_value(lane)): lane for lane in (*Lane, None)
}

type Ids = Annotated[list[UUID] | None, Query(max_length=MAX_IDS)]


def document_filter(
    contact_id: Ids = None,
    document_type_id: Ids = None,
    tag_id: Ids = None,
    space_id: Ids = None,
    lane: Annotated[list[LaneFilter] | None, Query(max_length=len(LaneFilter))] = None,
    field_id: UUID | None = None,
    contact_group_id: Ids = None,
    document_type_group_id: Ids = None,
    topic_id: Ids = None,
    document_date_from: date | None = None,
    document_date_to: date | None = None,
) -> DocumentFilter:
    """The query parameters of the document list as a filter (the search takes the same).
    Several contacts, types or spaces: one of them. Each tag or group is one set, the topics one
    more (a document has one topic: one of them); the service adds the tags below them.
    `document_date_from`, `document_date_to`: the document date lies between them, both days
    included (either end may stay open)."""

    def sets(ids: list[UUID] | None) -> tuple[frozenset[TagId], ...]:
        return tuple(frozenset({TagId(id)}) for id in dict.fromkeys(ids or ()))

    return DocumentFilter(
        contacts=frozenset(ContactId(id) for id in contact_id) if contact_id else None,
        document_types=(
            frozenset(DocumentTypeId(id) for id in document_type_id) if document_type_id else None
        ),
        tags=sets(tag_id),
        contact_groups=sets(contact_group_id),
        document_type_groups=sets(document_type_group_id),
        topics=frozenset(TagId(id) for id in topic_id) if topic_id else None,
        spaces=frozenset(SpaceId(id) for id in space_id) if space_id else None,
        lanes=None if not lane else frozenset(_LANES[item] for item in lane),
        field=None if field_id is None else FieldId(field_id),
        document_dates=_dates(document_date_from, document_date_to),
    )


def _dates(start: date | None, end: date | None) -> Period | None:
    if start is None and end is None:
        return None
    if start is not None and end is not None and end < start:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("query", "document_date_to"),
                    "msg": "the end of the period lies before its start",
                    "input": end.isoformat(),
                }
            ]
        )
    return Period(start or date.min, end or date.max)


Filter = Annotated[DocumentFilter, Depends(document_filter)]
AllDocuments = Annotated[
    bool, Query(description="Every user's documents instead of the caller's reach (admins).")
]
CountAll = Annotated[
    bool, Query(description="Count every user's documents instead of the caller's reach (admins).")
]
AllInboxes = Annotated[
    bool,
    Query(
        description="Every user's inbox instead of the caller's, with the caller's seen (admins)."
    ),
]
AllRules = Annotated[
    bool, Query(description="The rules of every user instead of the caller's (admins).")
]
DocumentCounts = Annotated[
    bool, Query(description="Count the documents of each (`document_count`).")
]
