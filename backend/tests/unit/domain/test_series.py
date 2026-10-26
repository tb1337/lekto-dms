"""Series and the next document (#145 PR 12, `domain.series`)."""

from datetime import date

from lekto.core.domain.ids import ContactId, DocumentId, DocumentTypeId, new_id
from lekto.core.domain.periods import Period
from lekto.core.domain.series import Cadence, Dated, SeriesKey, SeriesState, series_of

KEY = SeriesKey(ContactId(new_id()), DocumentTypeId(new_id()))


def dated(*days: date, periods: tuple[Period | None, ...] = ()) -> list[Dated]:
    return [
        Dated(DocumentId(new_id()), day, periods[index] if index < len(periods) else None)
        for index, day in enumerate(days)
    ]


def test_payslips_at_the_end_of_each_month() -> None:
    series = series_of(KEY, dated(date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30)))
    assert series is not None
    assert (series.cadence, series.next_date, series.spread) == (
        Cadence.MONTHLY,
        date(2026, 10, 31),
        2,
    )
    assert series.state(date(2026, 9, 15)) is SeriesState.LATER
    assert series.state(date(2026, 10, 20)) is SeriesState.SOON
    assert series.state(date(2026, 11, 2)) is SeriesState.SOON  # within its spread
    assert series.state(date(2026, 11, 3)) is SeriesState.OVERDUE
    assert series.state(date(2026, 12, 3)) is SeriesState.ENDED  # two dates missed


def test_the_spread_is_how_far_a_document_came_off_its_step() -> None:
    series = series_of(
        KEY, dated(date(2026, 1, 15), date(2026, 2, 20), date(2026, 3, 15), date(2026, 4, 15))
    )
    assert series is not None
    assert (series.cadence, series.spread, series.next_date) == (
        Cadence.MONTHLY,
        5,
        date(2026, 5, 15),
    )


def test_two_documents_or_scattered_ones_are_no_series() -> None:
    assert series_of(KEY, dated(date(2026, 1, 5), date(2026, 2, 5))) is None
    assert series_of(KEY, dated(date(2026, 1, 5), date(2026, 1, 20), date(2026, 3, 30))) is None


def test_a_yearly_series_and_one_in_days() -> None:
    yearly = series_of(KEY, dated(date(2024, 3, 1), date(2025, 3, 3), date(2026, 3, 2)))
    assert yearly is not None
    assert (yearly.cadence, yearly.next_date) == (Cadence.YEARLY, date(2027, 3, 2))
    fortnights = (date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 29))
    assert series_of(KEY, dated(*fortnights)) is None  # three dates in days: not yet
    days = series_of(KEY, dated(*fortnights, date(2026, 2, 12)))
    assert days is not None
    assert (days.cadence, days.interval, days.next_date) == (Cadence.DAYS, 14, date(2026, 2, 26))


def test_a_correction_counts_once_and_the_next_period_follows() -> None:
    months = (Period.month(2026, 7), Period.month(2026, 8), Period.month(2026, 8))
    series = series_of(
        KEY,
        dated(date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 10), periods=months)
        + dated(date(2026, 9, 30), periods=(Period.month(2026, 9),)),
    )
    assert series is not None
    assert len(series.documents) == 3  # the correction of August of 10 September aside
    assert series.next_period == Period.month(2026, 10)


def months(*pairs: tuple[int, int], day: int = 15) -> list[date]:
    return [date(year, month, day) for year, month in pairs]


def test_a_missed_month_a_one_off_or_a_late_one_keep_the_series() -> None:
    """From the review of #159: one irregular document does not end a long series."""
    regular = [(2025, month) for month in range(1, 13)] + [(2026, month) for month in range(1, 10)]
    missed = [pair for pair in regular if pair != (2025, 7)]
    series = series_of(KEY, dated(*months(*missed)))
    assert series is not None and series.next_date == date(2026, 10, 15)
    one_off = [*months(*regular), date(2025, 7, 22)]
    series = series_of(KEY, dated(*one_off))
    assert series is not None and len(series.documents) == len(regular)
    late = months(*regular)
    late[5] = date(2025, 6, 26)
    series = series_of(KEY, dated(*late))
    assert series is not None and series.spread == 2
    yearly = series_of(KEY, dated(*(date(year, 3, 1) for year in (2019, 2020, 2021, 2023, 2024))))
    assert yearly is not None and yearly.next_date == date(2025, 3, 1)


def test_three_scattered_dates_are_no_series() -> None:
    """Three random dates in days, or a long and a short gap, make none."""
    assert series_of(KEY, dated(date(2025, 11, 2), date(2026, 3, 1), date(2026, 8, 20))) is None
    assert series_of(KEY, dated(date(2026, 1, 15), date(2026, 2, 10), date(2026, 3, 18))) is None
