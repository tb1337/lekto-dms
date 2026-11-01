"""Identifiers: UUIDv7 (time-ordered), one distinct type per entity."""

import os
import re
import time
from typing import NewType
from uuid import UUID

UserId = NewType("UserId", UUID)
SpaceId = NewType("SpaceId", UUID)
DocumentId = NewType("DocumentId", UUID)
ContactId = NewType("ContactId", UUID)
ClassifierModelId = NewType("ClassifierModelId", UUID)
DocumentTypeId = NewType("DocumentTypeId", UUID)
TagId = NewType("TagId", UUID)
FieldId = NewType("FieldId", UUID)
EventId = NewType("EventId", UUID)
JobId = NewType("JobId", UUID)
SessionId = NewType("SessionId", UUID)
ApiTokenId = NewType("ApiTokenId", UUID)
ExternalIdentityId = NewType("ExternalIdentityId", UUID)
RuleId = NewType("RuleId", UUID)
RuleApplicationId = NewType("RuleApplicationId", UUID)
BulkOperationId = NewType("BulkOperationId", UUID)
WebhookId = NewType("WebhookId", UUID)
DeliveryId = NewType("DeliveryId", UUID)
TaskId = NewType("TaskId", UUID)
LensId = NewType("LensId", UUID)

_TIMESTAMP_BITS = 48
_RANDOM_BITS = 80

SHORT_ID = 8
"""Characters of a short id: the end of the id, its random bits (Tobi, 01.11.2026, umsetzungsplan
"MCP", decision 8; the start is the time and stays the same for a minute)."""
_REFERENCE = re.compile(rf"[0-9a-f]{{{SHORT_ID},12}}|[0-9a-f]{{32}}")


def short_id(id: UUID) -> str:
    """The last `SHORT_ID` characters of `id`: how an assistant names a document."""
    return id.hex[-SHORT_ID:]


def id_reference(text: str) -> str | None:
    """`text` as the end of an id it names, in hex: a short id (`SHORT_ID` to 12 characters, the
    last group) or the whole id, with or without hyphens; None for anything else."""
    hex = text.strip().lower().replace("-", "")
    return hex if _REFERENCE.fullmatch(hex) else None


def ends_with(id: UUID, references: frozenset[str]) -> bool:
    """Whether `id` ends with one of `references` (`id_reference`)."""
    return any(id.hex.endswith(reference) for reference in references)


def new_id() -> UUID:
    """A new UUIDv7 (RFC 9562): Unix time in milliseconds, then random bits.

    IDs sort by creation time to the millisecond; within a millisecond the order is random.
    """
    milliseconds = time.time_ns() // 1_000_000 & ((1 << _TIMESTAMP_BITS) - 1)
    random = int.from_bytes(os.urandom(_RANDOM_BITS // 8))
    value = milliseconds << _RANDOM_BITS | random
    value = value & ~(0xF << 76) | 0x7 << 76  # version 7
    value = value & ~(0x3 << 62) | 0x2 << 62  # variant RFC 9562
    return UUID(int=value)
