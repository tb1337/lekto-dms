"""The stream of documents (`GET /documents/stream`)."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from lekto.core.domain.documents import Document
from lekto.core.domain.pipeline import Lane as DocumentLane
from lekto.core.domain.series import Cadence, SeriesState
from lekto.core.services.stream import Lane, LaneKind, Stream


class StreamDocumentOut(BaseModel):
    """A document as the stream shows it."""

    id: UUID
    title: str
    document_date: date | None
    created_at: datetime
    contact_id: UUID | None
    document_type_id: UUID | None
    lane: DocumentLane | None

    @classmethod
    def of(cls, document: Document) -> "StreamDocumentOut":
        return cls(
            id=document.id,
            title=document.title,
            document_date=document.document_date,
            created_at=document.created_at,
            contact_id=document.contact_id,
            document_type_id=document.document_type_id,
            lane=document.lane,
        )


class ExpectedNextOut(BaseModel):
    """The document a series expects next: a placeholder at the end of its lane."""

    next_date: date
    next_period: str | None = Field(description="In ISO notation (`2026-11`), where it has one.")
    state: SeriesState
    cadence: Cadence
    spread_days: int


class StreamLaneOut(BaseModel):
    kind: LaneKind = Field(
        description="`series`; `branch` (documents that refer to one of a series or to its "
        "target, with the chain of theirs); `chain` (documents related only among themselves); "
        "`single` (documents without series and relation)."
    )
    documents: list[StreamDocumentOut] = Field(description="Oldest first.")
    contact_id: UUID | None = Field(description="Of a series.")
    document_type_id: UUID | None = Field(description="Of a series.")
    number: str | None = Field(description="The contract or customer number a series follows.")
    target: StreamDocumentOut | None = Field(
        description="The relation target at the start of a series (the contract); one may stand "
        "at the start of several."
    )
    expected: ExpectedNextOut | None = Field(
        description="Of a series that has not ended: the document it expects next."
    )
    parent: int | None = Field(description="Of a branch: the index of its series lane.")
    joins: UUID | None = Field(
        description="Of a branch: the document of the series (or its target) it refers to."
    )
    folded: bool = Field(
        description="Beyond 24 lanes of series and chains, the rest (with their branches): shown "
        "on demand."
    )

    @classmethod
    def of(cls, lane: Lane) -> "StreamLaneOut":
        series = lane.series
        expected = None
        if series is not None and lane.state is not SeriesState.ENDED:
            assert lane.state is not None
            expected = ExpectedNextOut(
                next_date=series.next_date,
                next_period=None if series.next_period is None else series.next_period.notation,
                state=lane.state,
                cadence=series.cadence,
                spread_days=series.spread,
            )
        key = None if series is None else series.key
        return cls(
            kind=lane.kind,
            documents=[StreamDocumentOut.of(item) for item in lane.documents],
            contact_id=None if key is None else key.contact_id,
            document_type_id=None if key is None else key.document_type_id,
            number=None if key is None or key.number is None else key.number[1],
            target=None if lane.target is None else StreamDocumentOut.of(lane.target),
            expected=expected,
            parent=lane.parent,
            joins=lane.joins,
            folded=lane.folded,
        )


class StreamOut(BaseModel):
    lanes: list[StreamLaneOut]
    truncated: bool = Field(
        description="More documents than a stream shows (500, the newest): a narrower filter "
        "shows it whole."
    )

    @classmethod
    def of(cls, stream: Stream) -> "StreamOut":
        return cls(
            lanes=[StreamLaneOut.of(lane) for lane in stream.lanes],
            truncated=stream.truncated,
        )
