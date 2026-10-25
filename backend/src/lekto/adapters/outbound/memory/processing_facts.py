"""The in-memory facts of processing: the first runs and verdicts beside the documents of the
unit of work, and the statistics over them, counted as the SQL adapter counts them. Written as
the SQL adapter's inserts are: the first write wins, no version is checked."""

from collections import Counter
from collections.abc import Collection, Iterator, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from lekto.adapters.outbound.memory.database import DOCUMENTS
from lekto.core.domain.documents import Document
from lekto.core.domain.errors import ConflictError
from lekto.core.domain.first_runs import FieldVerdict, FirstRun, Verdict
from lekto.core.domain.ids import DocumentId
from lekto.core.domain.pipeline import Lane, Node
from lekto.core.ports.repository import FactsScope, LaneCount, RunTimes, SignalCount

if TYPE_CHECKING:
    from lekto.adapters.outbound.memory.unit_of_work import MemoryUnitOfWork

type VerdictKey = tuple[DocumentId, str]

MICROSECOND = timedelta(microseconds=1)


class MemoryProcessingFacts:
    def __init__(self, uow: "MemoryUnitOfWork") -> None:
        self._uow = uow

    async def add_first_run(self, run: FirstRun) -> None:
        self._refer(run.document_id)
        if run.document_id not in self._runs():
            self._uow._first_runs[run.document_id] = replace(run, steps=dict(run.steps))

    async def add_verdicts(self, verdicts: Collection[FieldVerdict]) -> None:
        kept = self._verdicts()
        for verdict in verdicts:
            self._refer(verdict.document_id)
            key = (verdict.document_id, verdict.field)
            if key not in kept:
                self._uow._verdicts[key] = replace(verdict, signals=dict(verdict.signals))
                kept[key] = verdict

    async def first_run(self, document: DocumentId) -> FirstRun | None:
        run = self._runs().get(document)
        return None if run is None else replace(run, steps=dict(run.steps))

    async def verdicts(self, document: DocumentId) -> list[FieldVerdict]:
        return [
            replace(verdict, signals=dict(verdict.signals))
            for (id, _), verdict in sorted(self._verdicts().items())
            if id == document
        ]

    async def lane_counts(self, scope: FactsScope) -> list[LaneCount]:
        decided = {id for id, _ in self._verdicts()}
        counts = Counter(
            (document.first_lane, document.lane, document.id in decided)
            for document, _ in self._first_runs(scope)
            if document.first_lane is not None
        )
        return [
            LaneCount(first_lane=first, lane=lane, decided=was_decided, count=count)
            for (first, lane, was_decided), count in counts.items()
        ]

    async def lanes_by_period(
        self, scope: FactsScope, starts: Sequence[datetime]
    ) -> list[dict[Lane, int]]:
        periods: list[dict[Lane, int]] = [{} for _ in starts]
        for document, run in self._first_runs(scope):
            if document.first_lane is None:
                continue
            index = _period(run.stopped_at, starts)
            if index is not None:
                lanes = periods[index]
                lanes[document.first_lane] = lanes.get(document.first_lane, 0) + 1
        return periods

    async def run_times(self, scope: FactsScope) -> RunTimes:
        times = RunTimes(durations=[], work=[], steps={})
        for _, run in self._first_runs(scope):
            times.durations.append(run.duration // MICROSECOND)
            times.work.append(run.work // MICROSECOND)
            for node, step in run.steps.items():
                times.steps.setdefault(node, []).append(step // MICROSECOND)
        return times

    async def verdict_counts(self, scope: FactsScope) -> dict[tuple[str, Verdict], int]:
        return dict(Counter((verdict.field, verdict.verdict) for verdict in self._judged(scope)))

    async def signal_counts(self, scope: FactsScope) -> dict[tuple[str, Node], SignalCount]:
        hits: Counter[tuple[str, Node]] = Counter()
        misses: Counter[tuple[str, Node]] = Counter()
        for verdict in self._judged(scope):
            for signal, hit in verdict.signals.items():
                (hits if hit else misses)[verdict.field, signal] += 1
        return {
            key: SignalCount(hits=hits[key], misses=misses[key]) for key in hits.keys() | misses
        }

    # --- rows -----------------------------------------------------------------------------------

    def _first_runs(self, scope: FactsScope) -> Iterator[tuple[Document, FirstRun]]:
        """The documents of `scope` with their first runs (not copied)."""
        runs = self._runs()
        for document in self._uow._rows(DOCUMENTS):
            run = runs.get(document.id)
            if run is None or not _in(document, scope):
                continue
            if scope.since is not None and run.stopped_at < scope.since:
                continue
            yield document, run

    def _judged(self, scope: FactsScope) -> Iterator[FieldVerdict]:
        """The verdicts of `scope` (not copied)."""
        documents = {document.id: document for document in self._uow._rows(DOCUMENTS)}
        for (id, _), verdict in self._verdicts().items():
            document = documents.get(id)
            if document is None or not _in(document, scope):
                continue
            if scope.since is not None and verdict.decided_at < scope.since:
                continue
            yield verdict

    def _refer(self, document: DocumentId) -> None:
        """ConflictError for a fact of a document that does not exist, as the SQL schema's
        foreign key refuses it."""
        if self._uow._row(DOCUMENTS, document) is None:
            raise ConflictError(f"processing fact of a document that does not exist: {document}")

    def _runs(self) -> dict[DocumentId, FirstRun]:
        """The first runs committed, with this unit's."""
        self._uow._check_open()
        return {**self._uow._db.first_runs, **self._uow._first_runs}

    def _verdicts(self) -> dict[VerdictKey, FieldVerdict]:
        """The verdicts committed, with this unit's."""
        self._uow._check_open()
        return {**self._uow._db.verdicts, **self._uow._verdicts}


def _in(document: Document, scope: FactsScope) -> bool:
    return scope.channels is None or document.channel in scope.channels


def _period(at: datetime, starts: Sequence[datetime]) -> int | None:
    """The index of the period `at` falls in, from each of `starts` to the next."""
    found = None
    for index, start in enumerate(starts):
        if at < start:
            break
        found = index
    return found
