"""Periods: spans of days, both ends included, such as the month a time sheet is about."""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Self

from papiq.core.domain.errors import ValidationError


class PeriodKind(StrEnum):
    """What a period is, by its ends: one day, a calendar week (Monday to Sunday), a month, a
    quarter, a year, or any other span."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"
    SPAN = "span"


@dataclass(frozen=True)
class Period:
    """A span of days, both ends included: `Period(date(2026, 9, 1), date(2026, 9, 30))` is
    September 2026, a day has `start == end`. What it is (`kind`) follows from its ends."""

    start: date
    end: date

    def __post_init__(self) -> None:
        for end in (self.start, self.end):
            if not isinstance(end, date) or isinstance(end, datetime):
                raise ValidationError(f"a period's ends must be dates, got {end!r}")
        if self.end < self.start:
            raise ValidationError(f"a period cannot end before it starts: {self}")

    def __str__(self) -> str:
        return f"{self.start.isoformat()}/{self.end.isoformat()}"

    @classmethod
    def day(cls, day: date) -> Self:
        return cls(day, day)

    @classmethod
    def week(cls, year: int, week: int) -> Self:
        """Calendar week `week` of `year` (ISO 8601: Monday to Sunday)."""
        start = date.fromisocalendar(year, week, 1)
        return cls(start, start + timedelta(days=6))

    @classmethod
    def month(cls, year: int, month: int) -> Self:
        return cls(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]))

    @classmethod
    def quarter(cls, year: int, quarter: int) -> Self:
        if not 1 <= quarter <= 4:
            raise ValidationError(f"no quarter {quarter}")
        last = quarter * 3
        return cls(date(year, last - 2, 1), date(year, last, calendar.monthrange(year, last)[1]))

    @classmethod
    def year(cls, year: int) -> Self:
        return cls(date(year, 1, 1), date(year, 12, 31))

    @property
    def kind(self) -> PeriodKind:
        start, end = self.start, self.end
        if start == end:
            return PeriodKind.DAY
        if start.isoweekday() == 1 and end == start + timedelta(days=6):
            return PeriodKind.WEEK
        if start.day == 1 and end.year == start.year:
            if end == Period.month(start.year, start.month).end:
                return PeriodKind.MONTH
            if start.month % 3 == 1 and end == Period.quarter(start.year, start.month // 3 + 1).end:
                return PeriodKind.QUARTER
            if start.month == 1 and end == date(start.year, 12, 31):
                return PeriodKind.YEAR
        return PeriodKind.SPAN

    def overlaps(self, other: "Period") -> bool:
        return self.start <= other.end and other.start <= self.end
