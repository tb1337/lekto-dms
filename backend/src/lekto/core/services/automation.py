"""The numbers of the page "System" about the automation (Tobi, 24. and 25.10.2026): how the
documents went through their first run, what became of them, how long it took, and how people
judged what the automation set at their first decision on a field, overall and per signal
(`domain.first_runs`). For the channels and the period the viewer chooses (by default the web
and the API, 12 months: migrated documents bring the metadata of the source system); the numbers
are the whole system's, every user sees them, and they name no document.

Counted live in the database (`ProcessingFacts`) and kept for a minute: over a long period with
many documents, reading the times of every first run takes most of a second.
"""

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from enum import StrEnum
from typing import Any

from lekto.core.domain.classification import DOCUMENT_DATE, field_id_of
from lekto.core.domain.documents import Channel
from lekto.core.domain.first_runs import FACTS, JUDGED_FIELDS, RELATIONS, Verdict
from lekto.core.domain.ids import UserId
from lekto.core.domain.pipeline import NODES, Lane, Node
from lekto.core.domain.statistics import percentiles
from lekto.core.ports.clock import Clock
from lekto.core.ports.repository import FactsScope, LaneCount
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from lekto.core.services._access import load_actor
from lekto.core.services._kept import Kept

DEFAULT_CHANNELS = frozenset({Channel.WEB, Channel.API})
HISTORY_MONTHS = 12
"""The months of the history, for the periods that end now; all time goes back to the first."""
ALL_MONTHS = 60
"""How far the history of all time looks back, at most: five years of months is what a chart
still tells apart; the counts of all time are not bounded."""
_MICROSECOND = timedelta(microseconds=1)


class Period(StrEnum):
    """The period the numbers cover, up to now: 30 days, the current month and the eleven
    before it, or all time."""

    DAYS_30 = "30d"
    MONTHS_12 = "12m"
    ALL = "all"


@dataclass(frozen=True)
class Times:
    """Middle values of durations, one per document: median and 90th percentile (by nearest
    rank), over `count` documents; None without any."""

    count: int
    median: timedelta | None
    p90: timedelta | None

    @classmethod
    def of(cls, micros: Sequence[int]) -> "Times":
        median, p90 = percentiles(micros, (0.5, 0.9))
        return cls(len(micros), _time(median), _time(p90))


@dataclass(frozen=True)
class Flow:
    """How many documents whose first run stopped in `first_lane` lie in `lane` now (None:
    being processed again)."""

    first_lane: Lane
    lane: Lane | None
    count: int


@dataclass(frozen=True)
class Month:
    """The documents whose first run stopped in the month from `start` (the viewer's time
    zone), by first lane."""

    start: date
    lanes: Mapping[Lane, int]


@dataclass(frozen=True)
class FieldVerdicts:
    """The verdicts on a field (`field:<id>` with the custom field's `name`): how many of each
    kind; `early` decided before the first run stopped, counted apart (nothing was judged)."""

    field: str
    name: str | None
    counts: Mapping[Verdict, int]
    early: int = 0

    @property
    def decided(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True)
class AutomationReport:
    """The tab "Automation": `lanes` the documents by the lane of their first run; `flow` what
    became of them; `decided` how many of them a person decided a field of, `untouched` the
    green ones nobody decided ("not contradicted", no hit); the history by month; the times of
    the first runs (`duration` up to the first stop, with the waits; `work` the sum of the
    steps; per node in graph order); the verdicts per field, by when they were decided."""

    channels: frozenset[Channel]
    period: Period
    since: datetime | None
    lanes: Mapping[Lane, int]
    flow: tuple[Flow, ...]
    decided: int
    untouched: int
    months: tuple[Month, ...]
    duration: Times
    work: Times
    steps: Mapping[Node, Times]
    fields: tuple[FieldVerdicts, ...]


@dataclass(frozen=True)
class SignalHits:
    """How often `signal` named the value a person decided for `field` (`hits`) or another
    (`misses`); `decided` the decisions on the field (whether the signal named one or not)."""

    field: str
    signal: Node
    hits: int
    misses: int
    decided: int


@dataclass(frozen=True)
class SignalReport:
    """The hit rates of the signals per field, by when the decisions were made."""

    channels: frozenset[Channel]
    period: Period
    since: datetime | None
    signals: tuple[SignalHits, ...]


class AutomationService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock
        self._kept = Kept(clock)

    async def report(
        self,
        actor: UserId,
        *,
        channels: Collection[Channel] = DEFAULT_CHANNELS,
        period: Period = Period.MONTHS_12,
        zone: tzinfo,
    ) -> AutomationReport:
        """The numbers of the tab "Automation"; months in the time zone `zone`."""
        chosen = frozenset(channels)
        await self._actor(actor)

        async def count() -> AutomationReport:
            now = self._clock.now()
            since = _since(period, now, zone)
            scope = FactsScope(channels=chosen, since=since)
            starts = _month_starts(now, zone, ALL_MONTHS if period is Period.ALL else None)
            async with self._uow() as uow:
                lanes = await uow.processing_facts.lane_counts(scope)
                history = await uow.processing_facts.lanes_by_period(
                    FactsScope(channels=chosen, since=None), [_utc(start, zone) for start in starts]
                )
                times = await uow.processing_facts.run_times(scope)
                verdicts = await uow.processing_facts.verdict_counts(scope)
                names = {item.id: item.name for item in await uow.fields.list_all()}
            return AutomationReport(
                channels=chosen,
                period=period,
                since=since,
                lanes=_by_first_lane(lanes),
                flow=_flow(lanes),
                decided=sum(item.count for item in lanes if item.decided),
                untouched=sum(
                    item.count
                    for item in lanes
                    if item.first_lane is Lane.GREEN and not item.decided
                ),
                months=_months(starts, history, trim=period is Period.ALL),
                duration=Times.of(times.durations),
                work=Times.of(times.work),
                steps={node: Times.of(times.steps[node]) for node in NODES if node in times.steps},
                fields=_fields(verdicts, names),
            )

        return await self._kept.get(("report", chosen, period, str(zone)), count)

    async def signals(
        self,
        actor: UserId,
        *,
        channels: Collection[Channel] = DEFAULT_CHANNELS,
        period: Period = Period.MONTHS_12,
        zone: tzinfo,
    ) -> SignalReport:
        """The hit rates of the signals per field. The date has no candidates of the signals;
        the language model alone reads it, so its verdicts are the model's hits: taken over or
        accepted a hit, corrected a miss, added (the model had none) neither."""
        chosen = frozenset(channels)
        await self._actor(actor)

        async def count() -> SignalReport:
            since = _since(period, self._clock.now(), zone)
            scope = FactsScope(channels=chosen, since=since)
            async with self._uow() as uow:
                counts = await uow.processing_facts.signal_counts(scope)
                verdicts = await uow.processing_facts.verdict_counts(scope)
            decided: dict[str, int] = defaultdict(int)
            for (field, verdict), number in verdicts.items():
                if verdict is not Verdict.EARLY:
                    decided[field] += number
            hits = [
                SignalHits(field, signal, item.hits, item.misses, decided[field])
                for (field, signal), item in counts.items()
            ]
            dated = verdicts.get((DOCUMENT_DATE, Verdict.TAKEN), 0) + verdicts.get(
                (DOCUMENT_DATE, Verdict.ACCEPTED), 0
            )
            missed = verdicts.get((DOCUMENT_DATE, Verdict.CORRECTED), 0)
            if dated or missed:
                hits.append(
                    SignalHits(
                        DOCUMENT_DATE, Node.SIGNAL_LLM, dated, missed, decided[DOCUMENT_DATE]
                    )
                )
            hits.sort(key=lambda item: (_field_order(item.field), NODES.index(item.signal)))
            return SignalReport(chosen, period, since, tuple(hits))

        return await self._kept.get(("signals", chosen, period, str(zone)), count)

    async def _actor(self, actor: UserId) -> None:
        async with self._uow() as uow:
            await load_actor(uow, actor)


def _since(period: Period, now: datetime, zone: tzinfo) -> datetime | None:
    match period:
        case Period.DAYS_30:
            return now - timedelta(days=30)
        case Period.MONTHS_12:
            return _utc(_month_starts(now, zone, None)[0], zone)
        case Period.ALL:
            return None


def _month_starts(now: datetime, zone: tzinfo, count: int | None) -> list[date]:
    """The first days of the last `count` months (None: `HISTORY_MONTHS`) up to the current
    one in `zone`, oldest first."""
    today = now.astimezone(zone).date()
    months = []
    year, month = today.year, today.month
    for _ in range(count or HISTORY_MONTHS):
        months.append(date(year, month, 1))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return months[::-1]


def _utc(day: date, zone: tzinfo) -> datetime:
    """Midnight starting `day` in `zone`, in UTC."""
    return datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(UTC)


def _months(
    starts: Sequence[date], history: Sequence[Mapping[Lane, int]], *, trim: bool
) -> tuple[Month, ...]:
    months = [Month(start, dict(lanes)) for start, lanes in zip(starts, history, strict=True)]
    if trim:  # all time: from the first month with documents
        while len(months) > 1 and not any(months[0].lanes.values()):
            months.pop(0)
    return tuple(months)


def _by_first_lane(counts: Sequence[LaneCount]) -> dict[Lane, int]:
    lanes = dict.fromkeys(Lane, 0)
    for item in counts:
        lanes[item.first_lane] += item.count
    return lanes


def _flow(counts: Sequence[LaneCount]) -> tuple[Flow, ...]:
    flows: dict[tuple[Lane, Lane | None], int] = defaultdict(int)
    for item in counts:
        flows[item.first_lane, item.lane] += item.count
    order = list(Lane)
    return tuple(
        Flow(first, lane, count)
        for (first, lane), count in sorted(
            flows.items(),
            key=lambda entry: (
                order.index(entry[0][0]),
                len(order) if entry[0][1] is None else order.index(entry[0][1]),
            ),
        )
    )


def _fields(
    verdicts: Mapping[tuple[str, Verdict], int], names: Mapping[Any, str]
) -> tuple[FieldVerdicts, ...]:
    """The verdicts per field: the fields every document has first, its facts, then the custom
    ones by name; custom fields whose definition is gone are left out."""
    counts: dict[str, dict[Verdict, int]] = defaultdict(dict)
    for (field, verdict), number in verdicts.items():
        counts[field][verdict] = number
    fields = []
    for field, found in counts.items():
        id = field_id_of(field)
        if (id is None and field not in (*JUDGED_FIELDS, FACTS, RELATIONS)) or (
            id is not None and id not in names
        ):
            continue
        early = found.pop(Verdict.EARLY, 0)
        fields.append(FieldVerdicts(field, None if id is None else names[id], found, early))
    fields.sort(key=lambda item: (_field_order(item.field), (item.name or "").casefold()))
    return tuple(fields)


def _field_order(field: str) -> int:
    return JUDGED_FIELDS.index(field) if field in JUDGED_FIELDS else len(JUDGED_FIELDS)


def _time(micros: int | None) -> timedelta | None:
    return None if micros is None else micros * _MICROSECOND
