"""Query parameters that several routes share: the filter of documents (`GET /documents`,
`GET /documents/search`), the switch to every user's documents, and document counts."""

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query

from papiq.core.domain.ids import ContactId, DocumentTypeId, FieldId, SpaceId, TagId
from papiq.core.domain.pipeline import Lane
from papiq.core.domain.search import PROCESSING, lane_value
from papiq.core.ports import DocumentFilter

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
    contact_id: UUID | None = None,
    document_type_id: UUID | None = None,
    tag_id: Ids = None,
    space_id: UUID | None = None,
    lane: Annotated[list[LaneFilter] | None, Query(max_length=len(LaneFilter))] = None,
    field_id: UUID | None = None,
    contact_group_id: Ids = None,
    document_type_group_id: Ids = None,
    topic_id: Ids = None,
) -> DocumentFilter:
    """The query parameters of the document list as a filter (the search takes the same).
    Each tag or group is one set, the topics one more (a document has one topic: one of them);
    the service adds the tags below them."""

    def sets(ids: list[UUID] | None) -> tuple[frozenset[TagId], ...]:
        return tuple(frozenset({TagId(id)}) for id in dict.fromkeys(ids or ()))

    return DocumentFilter(
        contact=None if contact_id is None else ContactId(contact_id),
        document_type=None if document_type_id is None else DocumentTypeId(document_type_id),
        tags=sets(tag_id),
        contact_groups=sets(contact_group_id),
        document_type_groups=sets(document_type_group_id),
        topics=frozenset(TagId(id) for id in topic_id) if topic_id else None,
        space=None if space_id is None else SpaceId(space_id),
        lanes=None if not lane else frozenset(_LANES[item] for item in lane),
        field=None if field_id is None else FieldId(field_id),
    )


Filter = Annotated[DocumentFilter, Depends(document_filter)]
AllDocuments = Annotated[
    bool, Query(description="Every user's documents instead of the caller's reach (admins).")
]
CountAll = Annotated[
    bool, Query(description="Count every user's documents instead of the caller's reach (admins).")
]
DocumentCounts = Annotated[
    bool, Query(description="Count the documents of each (`document_count`).")
]
