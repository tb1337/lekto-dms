"""The numbers of the page "System" about the automation: first runs, what became of them,
their times, and the verdicts of people per field and per signal."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, Field

from lekto.adapters.inbound.rest.schemas.refs import seal
from lekto.core.domain.documents import Channel
from lekto.core.domain.first_runs import Verdict
from lekto.core.domain.holder_evaluation import Case, HolderEvaluation, Tally
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import ContactId
from lekto.core.domain.pipeline import Lane, Node
from lekto.core.ports.identity import RefCipher
from lekto.core.services.automation import (
    AutomationReport,
    FieldVerdicts,
    Period,
    SignalHits,
    SignalReport,
    Times,
)

FIELD = Field(
    description="The field as checks name it: `contact`, `document_type`, `topic`, "
    "`document_date`, `space`, `tags`, or `field:<id>` for a custom field.",
    examples=["contact"],
)


class LanesOut(BaseModel):
    green: int = Field(description="Went through without a person.")
    yellow: int = Field(description="Stopped for a review.")
    red: int = Field(description="Failed.")


class FlowOut(BaseModel):
    first_lane: Lane
    lane: Lane | None = Field(description="Where they lie now; null: being processed again.")
    count: int


class MonthOut(BaseModel):
    start: date = Field(description="The month's first day, in the time zone asked for.")
    lanes: LanesOut = Field(description="The documents whose first run stopped that month.")


class TimesOut(BaseModel):
    count: int = Field(description="Documents measured.")
    median_ms: float | None
    p90_ms: float | None = Field(description="90th percentile, by nearest rank.")

    @classmethod
    def of(cls, times: Times) -> "TimesOut":
        return cls(count=times.count, median_ms=_ms(times.median), p90_ms=_ms(times.p90))


class StepTimesOut(TimesOut):
    node: Node


class VerdictsOut(BaseModel):
    taken: int = Field(description="The automation's value stood.")
    accepted: int = Field(description="The suggestion of an uncertain field was taken.")
    corrected: int = Field(description="The automation had a value or suggestion; another one won.")
    added: int = Field(description="The automation had none; the person gave one.")


class FieldVerdictsOut(BaseModel):
    field: str = FIELD
    name: str | None = Field(description="A custom field's name; null for the others.")
    verdicts: VerdictsOut
    early: int = Field(
        description="Decided before the first run stopped: nothing to judge, counted apart."
    )

    @classmethod
    def of(cls, item: FieldVerdicts) -> "FieldVerdictsOut":
        return cls(
            field=item.field,
            name=item.name,
            verdicts=VerdictsOut(
                taken=item.counts.get(Verdict.TAKEN, 0),
                accepted=item.counts.get(Verdict.ACCEPTED, 0),
                corrected=item.counts.get(Verdict.CORRECTED, 0),
                added=item.counts.get(Verdict.ADDED, 0),
            ),
            early=item.early,
        )


class AutomationOut(BaseModel):
    channels: list[Channel]
    period: Period
    since: datetime | None = Field(description="From when the period counts; null: all time.")
    lanes: LanesOut = Field(description="The documents by the lane their first run stopped in.")
    flow: list[FlowOut] = Field(description="What became of them: their lane now.")
    decided: int = Field(description="Of them, those a person decided a field of.")
    untouched: int = Field(
        description="Of them, the green ones nobody decided a field of: not contradicted, no hit."
    )
    months: list[MonthOut] = Field(
        description="By the month their first run stopped, oldest first: the last 12 months, for "
        "all time from the first month with documents (at most 60)."
    )
    duration: TimesOut = Field(
        description="From the start of receiving to the first stop, with the waits for a worker."
    )
    work: TimesOut = Field(description="The sum of the steps (side by side ones each counted).")
    steps: list[StepTimesOut] = Field(description="Per node, in the order of the graph.")
    fields: list[FieldVerdictsOut] = Field(
        description="The verdicts at the first decision of a person on each field, by when they "
        "were decided: the fields every document has first, then the custom ones by name."
    )

    @classmethod
    def of(cls, report: AutomationReport) -> "AutomationOut":
        return cls(
            channels=sorted(report.channels),
            period=report.period,
            since=report.since,
            lanes=_lanes(report.lanes),
            flow=[
                FlowOut(first_lane=item.first_lane, lane=item.lane, count=item.count)
                for item in report.flow
            ],
            decided=report.decided,
            untouched=report.untouched,
            months=[
                MonthOut(start=month.start, lanes=_lanes(month.lanes)) for month in report.months
            ],
            duration=TimesOut.of(report.duration),
            work=TimesOut.of(report.work),
            steps=[
                StepTimesOut(node=node, **TimesOut.of(times).model_dump())
                for node, times in report.steps.items()
            ],
            fields=[FieldVerdictsOut.of(item) for item in report.fields],
        )


class SignalHitsOut(BaseModel):
    field: str = FIELD
    signal: Node
    hits: int = Field(description="Its best value was the one the person decided.")
    misses: int = Field(description="Its best value was another.")
    decided: int = Field(description="Decisions on the field, whether the signal named one or not.")

    @classmethod
    def of(cls, item: SignalHits) -> "SignalHitsOut":
        return cls(
            field=item.field,
            signal=item.signal,
            hits=item.hits,
            misses=item.misses,
            decided=item.decided,
        )


class SignalsOut(BaseModel):
    channels: list[Channel]
    period: Period
    since: datetime | None
    signals: list[SignalHitsOut] = Field(
        description="Per field and signal that named a value for it. The date has no candidates "
        "of the signals: the language model's are its verdicts (taken over or accepted a hit, "
        "corrected a miss)."
    )

    @classmethod
    def of(cls, report: SignalReport) -> "SignalsOut":
        return cls(
            channels=sorted(report.channels),
            period=report.period,
            since=report.since,
            signals=[SignalHitsOut.of(item) for item in report.signals],
        )


def _lanes(lanes: Mapping[Lane, int]) -> LanesOut:
    return LanesOut(
        green=lanes.get(Lane.GREEN, 0), yellow=lanes.get(Lane.YELLOW, 0), red=lanes.get(Lane.RED, 0)
    )


def _ms(value: timedelta | None) -> float | None:
    return None if value is None else round(value.total_seconds() * 1000, 1)


class TallyOut(BaseModel):
    """How a measure fared against the decisions at the contacts."""

    right: int = Field(description="Said the contact's and confirmed, or foreign and rejected.")
    learned_rejected: int = Field(
        description="Said the contact's (or: confirm), the person rejected: training learns it."
    )
    refused_confirmed: int = Field(description="Said foreign (or: reject), the person confirmed.")
    unclear: int = Field(description="Said neither (for the recommendation: none).")
    unread: int = Field(description="Read before its kind had a holder (`read-facts` sets it).")

    @classmethod
    def of(cls, tally: Tally) -> "TallyOut":
        return cls(
            right=tally.right,
            learned_rejected=tally.learned_rejected,
            refused_confirmed=tally.refused_confirmed,
            unclear=tally.unclear,
            unread=tally.unread,
        )


class HolderKindOut(TallyOut):
    kind: IdentifierKind

    @classmethod
    def of_kind(cls, kind: IdentifierKind, tally: Tally) -> "HolderKindOut":
        return cls(kind=kind, **TallyOut.of(tally).model_dump())


class HoldersOut(BaseModel):
    kinds: list[HolderKindOut] = Field(description="The rule's holders, per kind with a holder.")
    recommendation: TallyOut = Field(description="The open list's recommendation, every kind.")

    @classmethod
    def of(cls, evaluation: HolderEvaluation) -> "HoldersOut":
        return cls(
            kinds=[HolderKindOut.of_kind(kind, tally) for kind, tally in evaluation.kinds.items()],
            recommendation=TallyOut.of(evaluation.recommendation),
        )


class HolderCaseOut(BaseModel):
    """One decision behind a number of the holders' evaluation."""

    kind: IdentifierKind
    value: str = Field(description="Normalised, as Lekto compares it.")
    ref: str = Field(description="The value's reference (`GET /documents/{id}/places/...`).")
    contact_id: UUID
    contact: str = Field(description="The contact's name.")
    confirmed: bool = Field(description="The person confirmed it (else rejected it).")
    document_ids: list[UUID] = Field(
        description="The confirmed documents of the contact that show it, the newest first."
    )


class HolderCasesOut(BaseModel):
    cases: list[HolderCaseOut] = Field(description="At most a hundred.")

    @classmethod
    def of(
        cls, cases: Sequence[Case], names: Mapping[ContactId, str], refs: RefCipher
    ) -> "HolderCasesOut":
        return cls(
            cases=[
                HolderCaseOut(
                    kind=case.kind,
                    value=case.value,
                    ref=seal(refs, case.kind, case.value),
                    contact_id=case.contact,
                    contact=names.get(case.contact, ""),
                    confirmed=case.confirmed,
                    document_ids=list(case.documents),
                )
                for case in cases
            ]
        )
