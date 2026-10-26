"""Series and the documents expected next (`.idea/bezuege.md`, decisions 10 to 12; issue #145
PR 12): documents of one contact and type, and of one contract or customer number where they
show one, that come at a steady interval. Derived, never stored.

A series has at least three documents with a document date. The interval is the median of
the gaps between them, as a calendar step where it is one (a week, a month, a quarter, half a
year, a year), else in days: such a rhythm needs four documents, is at most `MAX_DAYS` long and
is kept exactly. Each document is so many steps after the one before (a gap of two steps is one
missed document, no deviation); one within the same step (a one-off of the contact) is set
aside. The spread is how far a document came off its step (at least `MIN_SPREAD` days; in a
longer history the worst step aside); a spread over a third of the step (a fifth for three
documents or a rhythm of days) is no series, and neither are many missed steps or one-offs.
The next document is expected one step after the last; it is overdue once the spread is over,
and the series ended after two missed dates. Two documents of one day or of one period (a
correction and its original) count once."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from itertools import pairwise
from statistics import median

from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import ContactId, DocumentId, DocumentTypeId
from lekto.core.domain.periods import Period, PeriodKind

MIN_DOCUMENTS = 3
MIN_DAYS_DOCUMENTS = 4
"""A rhythm of days that is no calendar step needs a fourth document: three random dates often
look steady."""
MAX_DAYS = 60
"""The longest rhythm of days that is no calendar step (every four or six weeks): a longer one
is a calendar step or chance."""
LONG = 5
"""From this many steps on, the worst step does not set the spread (one late document)."""
MIN_SPREAD = 2
"""Days a document may come off its step without being late: payslips of the last working day
move over a weekend."""
SOON = timedelta(days=30)
"""Expected within this: in the next 30 days."""


class Cadence(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    HALF_YEARLY = "half_yearly"
    YEARLY = "yearly"
    DAYS = "days"  # a steady number of days that is no calendar step


_MONTHS = {Cadence.MONTHLY: 1, Cadence.QUARTERLY: 3, Cadence.HALF_YEARLY: 6, Cadence.YEARLY: 12}
_RANGES = (
    (Cadence.WEEKLY, 6, 8),
    (Cadence.MONTHLY, 26, 35),
    (Cadence.QUARTERLY, 80, 100),
    (Cadence.HALF_YEARLY, 170, 195),
    (Cadence.YEARLY, 350, 380),
)
_STEP_DAYS = {
    Cadence.WEEKLY: 7.0,
    Cadence.MONTHLY: 30.44,
    Cadence.QUARTERLY: 91.31,
    Cadence.HALF_YEARLY: 182.62,
    Cadence.YEARLY: 365.25,
}
"""The mean length of a calendar step, to count how many steps lie between two documents."""
_PERIOD_STEP = {
    PeriodKind.MONTH: Cadence.MONTHLY,
    PeriodKind.QUARTER: Cadence.QUARTERLY,
    PeriodKind.YEAR: Cadence.YEARLY,
}


class SeriesState(StrEnum):
    OVERDUE = "overdue"  # the expected date and its spread are over
    SOON = "soon"  # expected within the next 30 days
    LATER = "later"
    ENDED = "ended"  # two expected dates missed


@dataclass(frozen=True)
class SeriesKey:
    """What the documents of a series share: contact and type, and the contract or customer
    number where they show one (`number`: kind and normalised value)."""

    contact_id: ContactId
    document_type_id: DocumentTypeId
    number: tuple[IdentifierKind, str] | None = None


@dataclass(frozen=True)
class Dated:
    """A document of a series as it counts: its date, and its period (the first value of a
    field of type period) where it has one."""

    id: DocumentId
    document_date: date
    period: Period | None = None


@dataclass(frozen=True)
class Series:
    key: SeriesKey
    documents: tuple[Dated, ...]  # oldest first, one per day or period
    cadence: Cadence
    interval: int  # days: the median gap
    spread: int  # days
    next_date: date
    next_period: Period | None  # the period the next document is for, where they carry one
    month_end: bool = False  # (nearly) every document on the last day of its month: the next too

    @property
    def last(self) -> Dated:
        return self.documents[-1]

    def state(self, today: date) -> SeriesState:
        """Where the next document stands on `today`."""
        tolerance = timedelta(days=self.spread)
        if today > step(self.next_date, self.cadence, self.interval, self.month_end) + tolerance:
            return SeriesState.ENDED
        if today > self.next_date + tolerance:
            return SeriesState.OVERDUE
        if self.next_date - today <= SOON:
            return SeriesState.SOON
        return SeriesState.LATER


def series_of(key: SeriesKey, documents: Sequence[Dated]) -> Series | None:
    """The series the documents make, or None: too few, or no steady interval."""
    kept = _once(documents)
    if len(kept) < MIN_DOCUMENTS:
        return None
    gaps = [(b.document_date - a.document_date).days for a, b in pairwise(kept)]
    interval = round(median(gaps))
    if interval <= 0:
        return None
    cadence = next((name for name, low, high in _RANGES if low <= interval <= high), Cadence.DAYS)
    if cadence is Cadence.DAYS and (len(kept) < MIN_DAYS_DOCUMENTS or interval > MAX_DAYS):
        return None
    ends = sum(_last_of_month(item.document_date) for item in kept)
    month_end = cadence in _MONTHS and ends * 5 >= len(kept) * 4
    length = _STEP_DAYS.get(cadence, interval)
    members: list[Dated] = [kept[0]]
    deviations: list[tuple[int, int]] = []
    aside = missed = 0
    plan = kept[0].document_date  # where the rhythm puts the last member
    for item in kept[1:]:
        steps = round((item.document_date - members[-1].document_date).days / length)
        if steps == 0:
            aside += 1  # a one-off within the step
            continue
        missed += steps - 1
        # Off its step from the one before, or from the rhythm: one late document is one
        # deviation, not two.
        actual = _advance(members[-1].document_date, steps, cadence, interval, month_end)
        planned = _advance(plan, steps, cadence, interval, month_end)
        off_actual = abs((item.document_date - actual).days)
        off_plan = abs((item.document_date - planned).days)
        deviations.append((min(off_actual, off_plan), max(off_actual, off_plan)))
        plan = planned if off_plan <= off_actual else actual
        members.append(item)
    if len(members) < MIN_DOCUMENTS or aside * 5 > len(kept) or missed * 4 > len(members):
        return None
    if cadence is Cadence.DAYS and (aside or missed):
        return None  # a rhythm of days that is no calendar step has to be kept exactly
    # A short history has to be steady by both measures; a long one by the kinder.
    long = len(members) >= LONG
    worst = sorted(kind if long else strict for kind, strict in deviations)
    spread = max(MIN_SPREAD, worst[-2] if long else worst[-1])
    strict = cadence is Cadence.DAYS or len(members) == MIN_DOCUMENTS
    if spread * (5 if strict else 3) > length:
        return None
    last = members[-1]
    return Series(
        key=key,
        documents=tuple(members),
        cadence=cadence,
        interval=interval,
        spread=spread,
        next_date=step(last.document_date, cadence, interval, month_end),
        next_period=_next_period(last.period, cadence),
        month_end=month_end,
    )


def step(day: date, cadence: Cadence, interval: int, month_end: bool = False) -> date:
    """`day` one step of the cadence later: for a calendar step of months the same day of the
    month (or the month's last), with `month_end` the last day of the month."""
    months = _MONTHS.get(cadence)
    if months is None:
        return day + timedelta(days=7 if cadence is Cadence.WEEKLY else interval)
    later = _plus_months(day, months)
    return _plus_months(later.replace(day=1), 1) - timedelta(days=1) if month_end else later


def _advance(day: date, steps: int, cadence: Cadence, interval: int, month_end: bool) -> date:
    for _ in range(steps):
        day = step(day, cadence, interval, month_end)
    return day


def _last_of_month(day: date) -> bool:
    return (day + timedelta(days=1)).month != day.month


def _plus_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    following = date(year + month // 12, month % 12 + 1, 1)
    return date(year, month, min(day.day, (following - timedelta(days=1)).day))


def _once(documents: Sequence[Dated]) -> list[Dated]:
    """Oldest first, one per day and one per period (the first: a correction later in the
    same period does not make a step of its own)."""
    kept: list[Dated] = []
    days: set[date] = set()
    periods: set[Period] = set()
    for item in sorted(documents, key=lambda item: (item.document_date, item.id)):
        if item.document_date in days or (item.period is not None and item.period in periods):
            continue
        days.add(item.document_date)
        if item.period is not None:
            periods.add(item.period)
        kept.append(item)
    return kept


def _next_period(period: Period | None, cadence: Cadence) -> Period | None:
    """The period after `period` where the series steps by its kind (a monthly series of
    monthly periods)."""
    if period is None or _PERIOD_STEP.get(period.kind) is not cadence:
        return None
    start = _plus_months(period.start, _MONTHS[cadence])
    return Period(start, _plus_months(start, _MONTHS[cadence]) - timedelta(days=1))
