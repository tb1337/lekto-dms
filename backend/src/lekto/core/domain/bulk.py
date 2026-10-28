"""Changing many documents at once (`.idea/umsetzungsplan.md`, "Massenaktionen und Seiten in der
Dokumentliste"): one action on documents a person selected in the documents list, a page of them
or all the hits of a search and filters, worked through in the background.

The selection is fixed when the person starts: the documents it names then, at most
`MAX_DOCUMENTS`. Each document then goes through the same change a person makes on one (rights,
change rules, events, decisions), one transaction each; one that cannot be changed is skipped
with its reason, and the others go on.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import (
    BulkOperationId,
    ContactId,
    DocumentId,
    DocumentTypeId,
    SpaceId,
    TagId,
    UserId,
    new_id,
)
from lekto.core.domain.json_value import JsonObject, JsonValue, as_list, as_text
from lekto.core.domain.pipeline import Node
from lekto.core.domain.reasons import Reason, ReasonCode, because
from lekto.core.domain.validation import require_utc

MAX_DOCUMENTS = 10_000
"""Documents one action changes at most."""

MAX_IDS = 500
"""Documents a selection names one by one at most (a page or a few pages)."""

_FIELDS = ("add", "remove", "contact", "document_type", "topic", "space", "node")


class BulkKind(StrEnum):
    CHANGE_TAGS = "change_tags"
    SET_CONTACT = "set_contact"
    SET_DOCUMENT_TYPE = "set_document_type"
    SET_TOPIC = "set_topic"
    MOVE = "move"
    CONFIRM = "confirm"
    REPROCESS = "reprocess"
    DELETE = "delete"


TAKES: Mapping[BulkKind, frozenset[str]] = {
    BulkKind.CHANGE_TAGS: frozenset({"add", "remove"}),
    BulkKind.SET_CONTACT: frozenset({"contact"}),
    BulkKind.SET_DOCUMENT_TYPE: frozenset({"document_type"}),
    BulkKind.SET_TOPIC: frozenset({"topic"}),
    BulkKind.MOVE: frozenset({"space"}),
    BulkKind.REPROCESS: frozenset({"node"}),
    BulkKind.CONFIRM: frozenset(),
    BulkKind.DELETE: frozenset(),
}
"""The fields of `BulkAction` each kind of action takes; any other given is a mistake."""


@dataclass(frozen=True)
class BulkAction:
    """What to do to each document: the tags to `add` and to `remove`; a contact, type or topic
    to set (None: to clear); the space to move into; the node to process again from."""

    kind: BulkKind
    add: frozenset[TagId] = frozenset()
    remove: frozenset[TagId] = frozenset()
    contact: ContactId | None = None
    document_type: DocumentTypeId | None = None
    topic: TagId | None = None
    space: SpaceId | None = None
    node: Node | None = None

    def __post_init__(self) -> None:
        given = {name for name in _FIELDS if getattr(self, name)}
        if stray := given - TAKES[self.kind]:
            raise ValidationError(f"{self.kind.value} takes no {', '.join(sorted(stray))}")
        if self.kind is BulkKind.CHANGE_TAGS and not (self.add or self.remove):
            raise ValidationError("name the tags to add or remove")
        if self.add & self.remove:
            raise ValidationError("a tag is both added and removed")
        if self.kind is BulkKind.MOVE and self.space is None:
            raise ValidationError("name the space to move into")
        if self.kind is BulkKind.REPROCESS and (self.node is None or self.node is Node.RECEIVE):
            raise ValidationError("name the step to process again from")

    def to_json(self) -> JsonObject:
        add: list[JsonValue] = [str(tag) for tag in sorted(self.add)]
        remove: list[JsonValue] = [str(tag) for tag in sorted(self.remove)]
        return {
            "kind": self.kind.value,
            "add": add,
            "remove": remove,
            "contact": None if self.contact is None else str(self.contact),
            "document_type": None if self.document_type is None else str(self.document_type),
            "topic": None if self.topic is None else str(self.topic),
            "space": None if self.space is None else str(self.space),
            "node": None if self.node is None else self.node.value,
        }

    @classmethod
    def from_json(cls, data: JsonValue) -> "BulkAction":
        if not isinstance(data, dict):
            raise ValidationError("an action is an object")

        def uuid(name: str) -> UUID | None:
            value = as_text(data.get(name))
            return None if value is None else UUID(value)

        contact, document_type, topic, space = (
            uuid(name) for name in ("contact", "document_type", "topic", "space")
        )
        node = as_text(data.get("node"))
        return cls(
            kind=BulkKind(str(data.get("kind"))),
            add=frozenset(TagId(UUID(str(tag))) for tag in as_list(data.get("add"))),
            remove=frozenset(TagId(UUID(str(tag))) for tag in as_list(data.get("remove"))),
            contact=None if contact is None else ContactId(contact),
            document_type=None if document_type is None else DocumentTypeId(document_type),
            topic=None if topic is None else TagId(topic),
            space=None if space is None else SpaceId(space),
            node=None if node is None else Node(node),
        )


class BulkStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(kw_only=True)
class BulkOperation:
    """A person's action on the documents they selected, worked through in the background.
    `position`: how many of `documents` are done; `changed` of them changed, `unchanged` were as
    the action wants them already, `skipped` left as they were, each with why."""

    id: BulkOperationId
    user_id: UserId
    action: BulkAction
    documents: tuple[DocumentId, ...]
    status: BulkStatus = BulkStatus.QUEUED
    position: int = 0
    changed: int = 0
    unchanged: int = 0
    skipped: list[tuple[DocumentId, Reason]] = field(default_factory=list)
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.documents:
            raise ValidationError("select at least one document")
        if len(self.documents) > MAX_DOCUMENTS:
            raise ValidationError(because(ReasonCode.BULK_TOO_MANY, max=MAX_DOCUMENTS))
        if len(set(self.documents)) != len(self.documents):
            raise ValidationError("a document is selected twice")
        self.created_at = require_utc(self.created_at, "created_at")

    @classmethod
    def create(
        cls,
        *,
        user_id: UserId,
        action: BulkAction,
        documents: tuple[DocumentId, ...],
        now: datetime,
    ) -> Self:
        return cls(
            id=BulkOperationId(new_id()),
            user_id=user_id,
            action=action,
            documents=documents,
            created_at=now,
        )

    @property
    def remaining(self) -> tuple[DocumentId, ...]:
        return self.documents[self.position :]

    @property
    def finished(self) -> bool:
        return self.status in (BulkStatus.DONE, BulkStatus.FAILED)

    def record_changed(self) -> None:
        self.changed += 1
        self._next()

    def record_unchanged(self) -> None:
        self.unchanged += 1
        self._next()

    def record_skipped(self, document: DocumentId, reason: Reason) -> None:
        self.skipped.append((document, reason))
        self._next()

    def _next(self) -> None:
        self.position += 1
        self.status = BulkStatus.RUNNING

    def finish(self, now: datetime, error: str | None = None) -> None:
        self.status = BulkStatus.FAILED if error else BulkStatus.DONE
        self.error = error
        self.finished_at = require_utc(now, "finished_at")
