"""A lens: its parts must fit together, a change applies whole or not at all."""

from datetime import date

import pytest

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import FieldId, TagId, UserId, new_id
from lekto.core.domain.lenses import (
    Grouping,
    Lens,
    LensChanges,
    LensFilter,
    LensSort,
    RelativePeriod,
)
from lekto.core.domain.periods import Period
from tests.builders import HOUR, NOW

FIELD = FieldId(new_id())


def lens() -> Lens:
    return Lens.create(owner_id=UserId(new_id()), name="  To pay  ", position=0, now=NOW)


def test_a_new_lens_shows_everything_by_default() -> None:
    made = lens()
    assert made.name == "To pay"
    assert (made.filter, made.query, made.sort, made.grouping) == (
        LensFilter(),
        None,
        None,
        Grouping.NONE,
    )


@pytest.mark.parametrize(
    "changes",
    [
        LensChanges(name=" "),
        LensChanges(card_field_ids=tuple(FieldId(new_id()) for _ in range(4))),
        LensChanges(sort=LensSort.FIELD),  # without the field
        LensChanges(sort_field_id=FIELD),  # without sorting by it
        LensChanges(sort=LensSort.FIELD, sort_field_id=FIELD, query="power"),  # words
        LensChanges(sort=LensSort.RELEVANCE),  # without words
        LensChanges(grouping=Grouping.DUE),  # without a deadline
        LensChanges(query="x" * 501),
    ],
)
def test_parts_that_do_not_fit_are_refused_and_nothing_changes(changes: LensChanges) -> None:
    made = lens()
    with pytest.raises(ValidationError):
        made.change(changes, now=NOW + HOUR)
    assert (made.name, made.sort, made.grouping, made.query) == (
        "To pay",
        None,
        Grouping.NONE,
        None,
    )
    assert made.card_field_ids == () and made.updated_at == NOW


def test_a_change_applies_what_it_sets() -> None:
    made = lens()
    made.change(
        LensChanges(
            sort=LensSort.FIELD_DESC,
            sort_field_id=FIELD,
            grouping=Grouping.DUE,
            due_field_id=FIELD,
            card_field_ids=(FIELD, FIELD),
            query="  ",
        ),
        now=NOW + HOUR,
    )
    assert (made.sort, made.sort_field_id, made.grouping) == (
        LensSort.FIELD_DESC,
        FIELD,
        Grouping.DUE,
    )
    assert made.card_field_ids == (FIELD,)  # once each
    assert made.query is None  # no words
    assert made.updated_at == NOW + HOUR
    made.change(LensChanges(name="Bills"), now=NOW + 2 * HOUR)
    assert made.name == "Bills" and made.sort_field_id == FIELD


def test_a_filter_takes_each_value_once_and_one_kind_of_period() -> None:
    tag = TagId(new_id())
    assert LensFilter(tag_ids=(tag, tag)).tag_ids == (tag,)
    with pytest.raises(ValidationError):
        LensFilter(relative_period=RelativePeriod.THIS_YEAR, date_from=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        LensFilter(date_from=date(2026, 2, 1), date_to=date(2026, 1, 1))
    assert LensFilter(date_from=date(2026, 1, 1)).date_to is None


@pytest.mark.parametrize(
    ("period", "today", "days"),
    [
        (RelativePeriod.THIS_YEAR, date(2026, 11, 1), Period.year(2026)),
        (RelativePeriod.LAST_YEAR, date(2026, 1, 1), Period.year(2025)),
        (RelativePeriod.LAST_12_MONTHS, date(2026, 11, 1), Period(date(2025, 11, 2), date.max)),
        (RelativePeriod.LAST_12_MONTHS, date(2028, 2, 29), Period(date(2027, 3, 1), date.max)),
    ],
)
def test_a_relative_period_as_the_web_ui_reckons_it(
    period: RelativePeriod, today: date, days: Period
) -> None:
    assert period.period(today) == days
