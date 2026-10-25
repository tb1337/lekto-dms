"""The facts of processing in `first_runs` and `field_verdicts`, and the statistics over them:
counted by the database where a count is wanted, the times read as values (the medians are the
domain's, `domain.statistics`)."""

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, case, func, literal, select

from lekto.adapters.outbound.sql import tables as t
from lekto.adapters.outbound.sql.transaction import Transaction
from lekto.core.domain.first_runs import Decision, FieldVerdict, FirstRun, Verdict
from lekto.core.domain.ids import DocumentId
from lekto.core.domain.pipeline import Lane, Node
from lekto.core.domain.validation import require_utc
from lekto.core.ports.repository import FactsScope, LaneCount, RunTimes, SignalCount

_runs, _verdicts, _documents = t.first_runs, t.field_verdicts, t.documents
_SIGNALS: dict[Node, Any] = {
    Node.SIGNAL_LLM: _verdicts.c.signal_llm,
    Node.SIGNAL_CLASSIFIER: _verdicts.c.signal_classifier,
    Node.SIGNAL_NEIGHBOURS: _verdicts.c.signal_neighbours,
    Node.SIGNAL_FACTS: _verdicts.c.signal_facts,
}


_NODES = {node.value: node for node in Node}
_MICROSECOND = timedelta(microseconds=1)


class SqlProcessingFacts:
    def __init__(self, transaction: Transaction) -> None:
        self._tx = transaction

    async def add_first_run(self, run: FirstRun) -> None:
        statement = self._tx.database.insert(_runs).values(
            document_id=run.document_id,
            started_at=run.started_at,
            stopped_at=run.stopped_at,
            steps={node.value: _micros(step) for node, step in run.steps.items()},
        )
        await self._tx.write(statement.on_conflict_do_nothing(index_elements=[_runs.c.document_id]))

    async def add_verdicts(self, verdicts: Collection[FieldVerdict]) -> None:
        rows = [
            {
                "document_id": verdict.document_id,
                "field": verdict.field,
                "verdict": verdict.verdict.value,
                "decided_at": verdict.decided_at,
                "decision": verdict.decision.value,
                **{signal.value: verdict.signals.get(signal) for signal in _SIGNALS},
            }
            for verdict in verdicts
        ]
        if rows:
            statement = self._tx.database.insert(_verdicts).on_conflict_do_nothing(
                index_elements=[_verdicts.c.document_id, _verdicts.c.field]
            )
            await self._tx.write(statement, rows)

    async def first_run(self, document: DocumentId) -> FirstRun | None:
        row = (await self._tx.read(select(_runs).where(_runs.c.document_id == document))).first()
        if row is None:
            return None
        return FirstRun(
            document_id=DocumentId(row.document_id),
            started_at=row.started_at,
            stopped_at=row.stopped_at,
            steps=_steps(row.steps),
        )

    async def verdicts(self, document: DocumentId) -> list[FieldVerdict]:
        rows = await self._tx.read(
            select(_verdicts).where(_verdicts.c.document_id == document).order_by(_verdicts.c.field)
        )
        return [
            FieldVerdict(
                document_id=DocumentId(row.document_id),
                field=row.field,
                verdict=Verdict(row.verdict),
                decided_at=row.decided_at,
                decision=Decision(row.decision),
                signals={
                    signal: value
                    for signal in _SIGNALS
                    if (value := getattr(row, signal.value)) is not None
                },
            )
            for row in rows
        ]

    async def lane_counts(self, scope: FactsScope) -> list[LaneCount]:
        decided = select(_verdicts.c.document_id).distinct().subquery()
        documents = (
            _runs_of(scope)
            .outerjoin(decided, decided.c.document_id == _documents.c.id)
            .add_columns(
                _documents.c.lane.label("lane"),
                decided.c.document_id.is_not(None).label("decided"),
            )
            .subquery()
        )
        rows = await self._tx.read(
            select(
                documents.c.first_lane,
                documents.c.lane,
                documents.c.decided,
                func.count().label("documents"),
            ).group_by(documents.c.first_lane, documents.c.lane, documents.c.decided)
        )
        return [
            LaneCount(
                first_lane=Lane(row.first_lane),
                lane=None if row.lane is None else Lane(row.lane),
                decided=bool(row.decided),
                count=row.documents,
            )
            for row in rows
        ]

    async def lanes_by_period(
        self, scope: FactsScope, starts: Sequence[datetime]
    ) -> list[dict[Lane, int]]:
        periods: list[dict[Lane, int]] = [{} for _ in starts]
        if not starts:
            return periods
        bounds = [require_utc(start, "start") for start in starts]
        # The latest start the stop is not before: the cases in descending order.
        period = case(
            *(
                (_runs.c.stopped_at >= start, literal(index))
                for index, start in reversed(list(enumerate(bounds)))
            ),
            else_=None,
        )
        documents = _runs_of(scope).add_columns(period.label("period")).subquery()
        rows = await self._tx.read(
            select(documents.c.period, documents.c.first_lane, func.count().label("documents"))
            .where(documents.c.period.is_not(None))
            .group_by(documents.c.period, documents.c.first_lane)
        )
        for row in rows:
            periods[row.period][Lane(row.first_lane)] = row.documents
        return periods

    async def run_times(self, scope: FactsScope) -> RunTimes:
        query = _runs_of(scope).add_columns(_runs.c.started_at, _runs.c.stopped_at, _runs.c.steps)
        durations: list[int] = []
        work: list[int] = []
        steps: dict[str, list[int]] = {}
        for row in await self._tx.read(query):
            durations.append((row.stopped_at - row.started_at) // _MICROSECOND)
            work.append(sum(row.steps.values()))
            for node, micros in row.steps.items():
                if node in steps:
                    steps[node].append(micros)
                else:
                    steps[node] = [micros]
        return RunTimes(
            durations=durations,
            work=work,
            steps={_NODES[node]: values for node, values in steps.items() if node in _NODES},
        )

    async def verdict_counts(self, scope: FactsScope) -> dict[tuple[str, Verdict], int]:
        verdicts = _verdicts_of(scope).add_columns(_verdicts.c.verdict).subquery()
        rows = await self._tx.read(
            select(verdicts.c.field, verdicts.c.verdict, func.count().label("verdicts")).group_by(
                verdicts.c.field, verdicts.c.verdict
            )
        )
        return {(row.field, Verdict(row.verdict)): row.verdicts for row in rows}

    async def signal_counts(self, scope: FactsScope) -> dict[tuple[str, Node], SignalCount]:
        verdicts = _verdicts_of(scope).add_columns(*_SIGNALS.values()).subquery()
        columns = []
        for signal in _SIGNALS:
            column = verdicts.c[signal.value]
            columns.append(_count(column.is_(True)).label(f"{signal.value}_hits"))
            columns.append(_count(column.is_(False)).label(f"{signal.value}_misses"))
        rows = await self._tx.read(select(verdicts.c.field, *columns).group_by(verdicts.c.field))
        counts: dict[tuple[str, Node], SignalCount] = {}
        for row in rows:
            for signal in _SIGNALS:
                hits, misses = (
                    row._mapping[f"{signal.value}_hits"],
                    row._mapping[f"{signal.value}_misses"],
                )
                if hits or misses:
                    counts[row.field, signal] = SignalCount(hits=hits, misses=misses)
        return counts


def _runs_of(scope: FactsScope) -> Select[Any]:
    """The first runs of the documents of `scope` whose first lane is known, with that lane."""
    query = (
        select(_documents.c.first_lane.label("first_lane"))
        .select_from(_runs.join(_documents, _documents.c.id == _runs.c.document_id))
        .where(_documents.c.first_lane.is_not(None))
    )
    if scope.channels is not None:
        query = query.where(_documents.c.channel.in_([channel.value for channel in scope.channels]))
    if scope.since is not None:
        query = query.where(_runs.c.stopped_at >= require_utc(scope.since, "since"))
    return query


def _verdicts_of(scope: FactsScope) -> Select[Any]:
    """The verdicts of the documents of `scope`, by when they were decided, with their field."""
    query = select(_verdicts.c.field.label("field")).select_from(
        _verdicts.join(_documents, _documents.c.id == _verdicts.c.document_id)
    )
    if scope.channels is not None:
        query = query.where(_documents.c.channel.in_([channel.value for channel in scope.channels]))
    if scope.since is not None:
        query = query.where(_verdicts.c.decided_at >= require_utc(scope.since, "since"))
    return query


def _count(condition: ColumnElement[bool]) -> ColumnElement[int]:
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def _micros(step: timedelta) -> int:
    return step // _MICROSECOND


def _steps(data: dict[str, int]) -> dict[Node, timedelta]:
    return {Node(node): timedelta(microseconds=micros) for node, micros in data.items()}
