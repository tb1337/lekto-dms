"""The documents expected next (`GET /expected`)."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.series import Cadence, SeriesState
from lekto.core.services.expected import Expected


class NamedOut(BaseModel):
    id: UUID
    name: str


class SeriesNumberOut(BaseModel):
    kind: IdentifierKind
    value: str = Field(description="Normalised, as Lekto compares it.")


class LastDocumentOut(BaseModel):
    id: UUID
    title: str
    document_date: date


class ExpectedOut(BaseModel):
    """A series and the document it expects next."""

    contact: NamedOut
    document_type: NamedOut
    number: SeriesNumberOut | None = Field(
        description="The contract or customer number the series follows, if its documents show one."
    )
    cadence: Cadence = Field(
        description="A calendar step (`weekly` to `yearly`) or `days` (see `interval_days`)."
    )
    interval_days: int = Field(description="The median gap between its documents.")
    spread_days: int = Field(description="How far a document may come off its step (± days).")
    documents: int = Field(description="How many documents the series has (one per period).")
    last: LastDocumentOut
    next_date: date
    next_period: str | None = Field(
        description="The period the next document is for, in ISO notation (`2026-11`), where "
        "the series carries one."
    )
    state: SeriesState = Field(
        description="`overdue` (its date and spread are over), `soon` (in the next 30 days), "
        "`later`, or `ended` (two dates missed)."
    )

    @classmethod
    def of(cls, item: Expected) -> "ExpectedOut":
        series = item.series
        key = series.key
        number = (
            None if key.number is None else SeriesNumberOut(kind=key.number[0], value=key.number[1])
        )
        last = item.last
        assert last.document_date is not None
        return cls(
            contact=NamedOut(id=key.contact_id, name=item.contact),
            document_type=NamedOut(id=key.document_type_id, name=item.document_type),
            number=number,
            cadence=series.cadence,
            interval_days=series.interval,
            spread_days=series.spread,
            documents=len(series.documents),
            last=LastDocumentOut(id=last.id, title=last.title, document_date=last.document_date),
            next_date=series.next_date,
            next_period=None if series.next_period is None else series.next_period.notation,
            state=item.state,
        )
