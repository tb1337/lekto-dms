"""Domain events. They are created by the aggregates and stored with the state change
(transactional outbox). Receivers recognise repeated deliveries by the event id. One is not
stored: `SearchMeaningReady` goes from the search straight to the searcher's event streams."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from lekto.core.domain.ids import DocumentId, EventId, SpaceId, UserId, new_id
from lekto.core.domain.pipeline import Lane, Node, Outcome
from lekto.core.domain.validation import require_utc


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    type: ClassVar[str]
    occurred_at: datetime
    id: EventId = field(default_factory=lambda: EventId(new_id()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", require_utc(self.occurred_at, "occurred_at"))


@dataclass(frozen=True, kw_only=True)
class DocumentEvent(DomainEvent):
    document_id: DocumentId


@dataclass(frozen=True, kw_only=True)
class DocumentReceived(DocumentEvent):
    type: ClassVar[str] = "document.received"


@dataclass(frozen=True, kw_only=True)
class NodeStarted(DocumentEvent):
    """A worker took the node up; again after a lost lease."""

    type: ClassVar[str] = "document.node_started"
    node: Node
    run: int


@dataclass(frozen=True, kw_only=True)
class NodeDeferred(DocumentEvent):
    """An attempt of the node failed with an error; the node waits and runs again at
    `retry_at`."""

    type: ClassVar[str] = "document.node_deferred"
    node: Node
    run: int
    retry_at: datetime

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "retry_at", require_utc(self.retry_at, "retry_at"))


@dataclass(frozen=True, kw_only=True)
class NodeDelegated(DocumentEvent):
    """The node waits for answers to its tasks ("running externally"); `deadline`: when the
    last of its open tasks ends at the latest (None while they wait to be sent)."""

    type: ClassVar[str] = "document.node_delegated"
    node: Node
    run: int
    deadline: datetime | None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.deadline is not None:
            object.__setattr__(self, "deadline", require_utc(self.deadline, "deadline"))


@dataclass(frozen=True, kw_only=True)
class NodeCompleted(DocumentEvent):
    type: ClassVar[str] = "document.node_completed"
    node: Node
    run: int
    outcome: Outcome


@dataclass(frozen=True, kw_only=True)
class LaneChanged(DocumentEvent):
    """`None` means no lane: the document is being processed."""

    type: ClassVar[str] = "document.lane_changed"
    old: Lane | None
    new: Lane | None


@dataclass(frozen=True, kw_only=True)
class DocumentFiled(DocumentEvent):
    type: ClassVar[str] = "document.filed"
    space_id: SpaceId


@dataclass(frozen=True, kw_only=True)
class ReviewRequired(DocumentEvent):
    """The document waits in the inbox for its editors: uncertain (yellow) or failed (red)."""

    type: ClassVar[str] = "document.review_required"
    lane: Lane


@dataclass(frozen=True, kw_only=True)
class DocumentConfirmed(DocumentEvent):
    """A person confirmed the document in the inbox; processing goes on from there."""

    type: ClassVar[str] = "document.confirmed"


@dataclass(frozen=True, kw_only=True)
class DocumentMoved(DocumentEvent):
    """The document lies in another space (`space_id`): a person moved or handed it over
    (`by_person`), or processing or a rule did. `handed_over`: into the personal space of
    another user than the one who moved it (or, moved by processing or a rule, uploaded it)."""

    type: ClassVar[str] = "document.moved"
    space_id: SpaceId
    by_person: bool
    handed_over: bool


@dataclass(frozen=True, kw_only=True)
class DocumentUpdated(DocumentEvent):
    type: ClassVar[str] = "document.updated"
    fields: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class DocumentDeleted(DocumentEvent):
    """`readers`: who could read the document when it was deleted (the document is gone, so
    nobody can be checked afterwards). Internal: pushed events and webhook requests do not
    carry it."""

    type: ClassVar[str] = "document.deleted"
    readers: tuple[UserId, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ClassifierTrained(DomainEvent):
    """A new model of the classifier was stored. For the admins (event stream), not for
    webhooks."""

    type: ClassVar[str] = "classifier.trained"
    number: int
    examples: int


@dataclass(frozen=True, kw_only=True)
class SearchMeaningReady(DomainEvent):
    """The meaning of a query that a search of `user_id` had to do without (it was not ready in
    time) is ready now: a search for it again takes the meaning into account. Not stored, for
    the user's event streams only (the API process that searched hands it on)."""

    type: ClassVar[str] = "search.meaning_ready"
    user_id: UserId
    query: str


DOCUMENT_EVENT_TYPES: dict[str, type[DocumentEvent]] = {
    kind.type: kind
    for kind in (
        DocumentReceived,
        NodeStarted,
        NodeDeferred,
        NodeDelegated,
        NodeCompleted,
        LaneChanged,
        ReviewRequired,
        DocumentConfirmed,
        DocumentFiled,
        DocumentMoved,
        DocumentUpdated,
        DocumentDeleted,
    )
}
"""The events about a document: those webhooks subscribe to."""

EVENT_TYPES: dict[str, type[DomainEvent]] = {
    **DOCUMENT_EVENT_TYPES,
    ClassifierTrained.type: ClassifierTrained,
}
