"""Query parameters that routes share: the filter of documents (`GET /documents`,
`GET /documents/search`), the switches to every user's documents and rules (`all_users`), and
document counts; and how their descriptions say who may call them."""

from datetime import date
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query
from fastapi.exceptions import RequestValidationError

from lekto.core.domain.document_facts import FactCriterion, FactRole
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import ContactId, DocumentTypeId, FieldId, SpaceId, TagId
from lekto.core.domain.periods import Period
from lekto.core.domain.pipeline import Lane
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.search import PROCESSING, lane_value
from lekto.core.ports.repository import DocumentFilter

ADMINS_ONLY = "Admins only."
SESSION_ONLY_NOTE = " Needs a session; API tokens are refused (403)."

MAX_IDS = 50
"""Ids of one kind a filter names at most."""
MAX_FACTS = 5
"""Facts a filter names at most."""


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
    fact: Annotated[
        list[str] | None,
        Query(
            max_length=MAX_FACTS,
            description=(
                "A fact the document has (none a person rejected), as `kind:value:role`: the "
                "value as written (it needs its kind; it may hold colons), any part empty for "
                "any (`invoice_number:4711:`, `contract_number::`, `::refers`). Several: all "
                "of them. A person's facts (the kinds that are a person's alone, the role "
                "`person`) only for admins (403); 422 for one that is none."
            ),
        ),
    ] = None,
) -> DocumentFilter:
    """The query parameters of the document list as a filter (the search takes the same).
    Several contacts, types, spaces, contact groups, type groups or topics: one of them (each
    kind one set). Each tag is a set of its own: all of them. The service adds the tags below
    them. `document_date_from`, `document_date_to`: the document date lies between them, both
    days included (either end may stay open)."""

    def sets(ids: list[UUID] | None) -> tuple[frozenset[TagId], ...]:
        return tuple(frozenset({TagId(id)}) for id in dict.fromkeys(ids or ()))

    def either(ids: list[UUID] | None) -> tuple[frozenset[TagId], ...]:
        return (frozenset(TagId(id) for id in ids),) if ids else ()

    return DocumentFilter(
        contacts=frozenset(ContactId(id) for id in contact_id) if contact_id else None,
        document_types=(
            frozenset(DocumentTypeId(id) for id in document_type_id) if document_type_id else None
        ),
        tags=sets(tag_id),
        contact_groups=either(contact_group_id),
        document_type_groups=either(document_type_group_id),
        topics=frozenset(TagId(id) for id in topic_id) if topic_id else None,
        spaces=frozenset(SpaceId(id) for id in space_id) if space_id else None,
        lanes=None if not lane else frozenset(_LANES[item] for item in lane),
        field=None if field_id is None else FieldId(field_id),
        document_dates=_dates(document_date_from, document_date_to),
        facts=tuple(_fact(item) for item in dict.fromkeys(fact or ())),
    )


def _fact(written: str) -> FactCriterion:
    """A fact of the filter as `kind:value:role`: the kind before the first colon, the role
    after the last, the value between (a value may hold colons, a time of day). 422 with the
    reason for one that is none."""
    kind, colon, rest = written.partition(":")
    value, colon_too, role = rest.rpartition(":")
    if not (colon and colon_too):
        raise ValidationError(because(ReasonCode.FACT_CRITERION_EMPTY))
    kind, value, role = kind.strip(), value.strip(), role.strip()
    if kind and kind not in IdentifierKind:
        raise ValidationError(because(ReasonCode.FACT_KIND_UNKNOWN, kind=kind))
    if role and role not in FactRole:
        raise ValidationError(because(ReasonCode.FACT_KIND_UNKNOWN, kind=role))
    return FactCriterion.written(
        IdentifierKind(kind) if kind else None,
        value or None,
        FactRole(role) if role else None,
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
    bool, Query(description="The rules of every space instead of the caller's (admins).")
]
AllSpaces = Annotated[bool, Query(description="Every space instead of the caller's (admins).")]
DocumentCounts = Annotated[
    bool, Query(description="Count the documents of each (`document_count`).")
]
