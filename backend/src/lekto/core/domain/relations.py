"""Relations between documents (`.idea/bezuege.md`, issue #145 PR 9): a directed link from the
newer document to the older one it refers to (a reminder to its invoice, a correction to the
original, an invoice to its contract). Two documents stay two documents; relations are n:m and
have no kind of their own, the types at both ends give their sense.

A relation is set (sure), suggested (unsure: shown at the document, never yellow), or rejected
by a person (so recognition does not suggest it again). It comes from a person or from Lekto,
with the evidence Lekto had (a shared number, a period). Only who reads both documents sees it;
who edits the newer and reads the older sets or removes it by hand.

The pair is stored in the order of when it was made; a document date set or changed since may
turn it, so the direction is read from the documents' dates now (`services.relations`), and a
pair is looked up in either order."""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import DocumentId, UserId
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.validation import require_utc


class RelationOrigin(StrEnum):
    PERSON = "person"  # a person set it
    LEKTO = "lekto"  # Lekto recognised it (`relate`)


class RelationState(StrEnum):
    SET = "set"  # it holds
    SUGGESTED = "suggested"  # Lekto is unsure: a person decides
    REJECTED = "rejected"  # a person said it does not hold: not suggested again


@dataclass(frozen=True, kw_only=True)
class Relation:
    """`newer` refers to `older` (`bezieht sich auf`). `evidence`: what Lekto had (`kind` of
    source and its values), empty for a person's. `decided_by`, `decided_at`: the person who set,
    accepted or rejected it last."""

    newer: DocumentId
    older: DocumentId
    origin: RelationOrigin
    state: RelationState
    created_at: datetime
    evidence: JsonObject = field(default_factory=dict)
    decided_by: UserId | None = None
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.newer == self.older:
            raise ValidationError("a document does not refer to itself")
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))
        if self.decided_at is not None:
            object.__setattr__(self, "decided_at", require_utc(self.decided_at, "decided_at"))

    @property
    def key(self) -> tuple[DocumentId, DocumentId]:
        return self.newer, self.older

    def other(self, document: DocumentId) -> DocumentId:
        """The other end of the relation, seen from `document`."""
        return self.older if document == self.newer else self.newer


def ordered(
    first: tuple[DocumentId, date | None, datetime],
    second: tuple[DocumentId, date | None, datetime],
) -> tuple[DocumentId, DocumentId]:
    """Which of two documents (each with its document date and when it came in) is the newer
    and which the older: by the document date, else when they came in; the newer first."""

    def when(item: tuple[DocumentId, date | None, datetime]) -> tuple[date, datetime, str]:
        _, dated, came = item
        return (dated or came.date(), came, str(item[0]))

    newer, older = sorted((first, second), key=when, reverse=True)
    return newer[0], older[0]
