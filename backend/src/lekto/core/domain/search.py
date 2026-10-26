"""What the search index holds, and who may find it.

The index is derived from the repository and the object store and can always be rebuilt from
them. `Visibility.allows` is the reach rule of `permissions.py` in the form of an index document:
a test keeps both in line, and every search needs a `Visibility`.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import (
    ContactId,
    DocumentId,
    DocumentTypeId,
    FieldId,
    SpaceId,
    TagId,
)
from lekto.core.domain.permissions import Reach, within_reach
from lekto.core.domain.pipeline import Lane

PROCESSING = "processing"
"""The lane value of a document that has none yet."""
LAYOUT = 7
"""The shape of what the index holds of a document. An entry of an older layout is written
anew by the reconciliation (2: the ids of the fields with a value, and the title's sort key;
3: `space_id` instead of `drawer_id`; 4: tags with their ancestors, and the groups of the
contact and the type; 5: the topic with its ancestors; 6: no owner, rights by space only;
7: the facts, by their tokens and their values)."""
FIRST_LAYOUT = 1
"""The layout of an entry that names none: written before layouts were counted."""


def lane_value(lane: Lane | None) -> str:
    return PROCESSING if lane is None else lane.value


@dataclass(frozen=True)
class EmbeddingStamp:
    """Which model computed the vectors of a document, from which text: `digest` covers the
    texts that were embedded. Vectors whose stamp differs from the current one are stale."""

    model: str
    digest: str


@dataclass(frozen=True, kw_only=True)
class IndexDocument:
    """A document as the index holds it. Names are indexed for the search, ids for the filters.

    Tags and the topic come with their ancestors, and the groups of the document's contact and
    type with theirs (`tag_tree`): a document is found by a tag or a topic above the one it
    carries, by name and by id.

    `vectors` holds one vector per section of the text (all of one length); `embedding` says
    how they were made and is required with them. `vectors=None` keeps the vectors (and their
    stamp) that the index already holds for the document: for an update after which the text,
    and so the vectors, did not change.
    """

    id: DocumentId
    version: int
    space_id: SpaceId
    lane: Lane | None
    title: str
    filename: str
    text: str = ""
    contact_id: ContactId | None = None
    contact: str | None = None
    document_type_id: DocumentTypeId | None = None
    document_type: str | None = None
    tag_ids: tuple[TagId, ...] = ()
    tags: tuple[str, ...] = ()
    contact_group_ids: tuple[TagId, ...] = ()
    contact_groups: tuple[str, ...] = ()
    document_type_group_ids: tuple[TagId, ...] = ()
    document_type_groups: tuple[str, ...] = ()
    topic_ids: tuple[TagId, ...] = ()  # the topic and those above it
    topics: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    field_ids: tuple[FieldId, ...] = ()  # the fields with a value, for the filter
    # The facts (none rejected): their tokens for the filter (`document_facts.fact_tokens`),
    # their values, normalised, for the words ("R20260815" for "R-2026-0815").
    facts: tuple[str, ...] = ()
    fact_values: tuple[str, ...] = ()
    document_date: date | None = None
    created_at: datetime
    # A person set or confirmed its metadata (`Document.confirmed_at`): it may vote as a
    # neighbour of a new document.
    confirmed: bool = False
    vectors: tuple[tuple[float, ...], ...] | None = field(default=(), repr=False)
    embedding: EmbeddingStamp | None = None

    def __post_init__(self) -> None:
        if self.vectors is None:
            if self.embedding is not None:
                raise ValidationError("kept vectors keep their stamp: give none")
            return
        if self.vectors and self.embedding is None:
            raise ValidationError("vectors need an embedding stamp")
        if len({len(vector) for vector in self.vectors}) > 1 or any(
            not vector for vector in self.vectors
        ):
            raise ValidationError("vectors must be non-empty and of one length")

    @property
    def lane_value(self) -> str:
        return lane_value(self.lane)


@dataclass(frozen=True)
class IndexState:
    """What the index knows about a document, without the content."""

    id: DocumentId
    version: int
    embedding: EmbeddingStamp | None
    layout: int = LAYOUT


@dataclass(frozen=True)
class Visibility:
    """What the one searching may find: every document in the spaces they edit (`edits`), the
    green ones in the spaces they only read (`reads`; `permissions.within_reach`).
    `everything`: every document, for an admin who asks for all users' documents."""

    edits: frozenset[SpaceId]
    reads: frozenset[SpaceId] = frozenset()
    everything: bool = False

    @classmethod
    def of(cls, reach: Reach) -> "Visibility":
        return cls(reach.edits, reach.reads)

    def allows(self, document: IndexDocument) -> bool:
        return self.everything or within_reach(self.edits, self.reads, document)


@dataclass(frozen=True)
class Segment:
    """A piece of text of a hit, marked if it matched the query."""

    text: str
    match: bool = False
