"""Domain events as outbox rows: type, id and time in columns, the other fields as JSON, under
their names. Which class a type is comes from `EVENT_TYPES`; how each field is written and read,
from `_FIELDS`."""

import dataclasses
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from papiq.core.domain.events import EVENT_TYPES, DomainEvent
from papiq.core.domain.ids import DocumentId, EventId, SpaceId, UserId
from papiq.core.domain.json_value import JsonObject, JsonValue
from papiq.core.domain.pipeline import Lane, Node, Outcome


def _lane_out(lane: Lane | None) -> JsonValue:
    return None if lane is None else lane.value


def _lane(value: str | None) -> Lane | None:
    return None if value is None else Lane(value)


_FIELDS: dict[str, tuple[Callable[[Any], JsonValue], Callable[[Any], object]]] = {
    "document_id": (str, lambda value: DocumentId(UUID(value))),
    "readers": (
        lambda readers: [str(reader) for reader in readers],
        lambda value: tuple(UserId(UUID(reader)) for reader in value),
    ),
    "node": (lambda node: node.value, Node),
    "run": (int, int),
    "retry_at": (lambda at: at.isoformat(), datetime.fromisoformat),
    "outcome": (lambda outcome: outcome.value, Outcome),
    "old": (_lane_out, _lane),
    "new": (_lane_out, _lane),
    "space_id": (str, lambda value: SpaceId(UUID(value))),
    "fields": (list, tuple),
    "number": (int, int),
    "examples": (int, int),
}
"""Per field of an event: how it is written to the payload and read back."""
_COLUMNS = frozenset({"id", "occurred_at"})


def encode(event: DomainEvent) -> JsonObject:
    """The payload of an event: every field except type, id and time."""
    if EVENT_TYPES.get(event.type) is not type(event):
        raise ValueError(f"no outbox mapping for event type {event.type!r}")
    return {
        item.name: _FIELDS[item.name][0](getattr(event, item.name))
        for item in dataclasses.fields(event)
        if item.name not in _COLUMNS
    }


def decode(type: str, id: UUID, occurred_at: datetime, payload: dict[str, Any]) -> DomainEvent:
    """The event of an outbox row; a field an older row lacks takes its default."""
    kind = EVENT_TYPES.get(type)
    if kind is None:
        raise ValueError(f"unknown event type {type!r}")
    fields = {name: _FIELDS[name][1](value) for name, value in payload.items()}
    return kind(id=EventId(id), occurred_at=occurred_at, **fields)
