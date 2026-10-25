"""Median and percentile by nearest rank: one of the values, unmoved by a far outlier."""

from datetime import timedelta

import pytest

from lekto.core.domain.statistics import median, percentile, percentiles


def test_the_median_is_the_middle_value_the_lower_of_an_even_count() -> None:
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([4.0, 1.0, 3.0, 2.0]) == 2.0
    assert median([5.0]) == 5.0
    assert median([]) is None


def test_the_percentile_takes_the_value_at_its_rank() -> None:
    values = [float(n) for n in range(1, 11)]
    assert percentile(values, 0.9) == 9.0
    assert percentile(values, 1.0) == 10.0
    assert percentile(values, 0.01) == 1.0
    assert percentile([timedelta(seconds=s) for s in (1, 2, 3600)], 0.5) == timedelta(seconds=2)


def test_an_outlier_moves_only_the_top_ranks() -> None:
    values = [1.0] * 9 + [10_000.0]
    assert (median(values), percentile(values, 0.9)) == (1.0, 1.0)


@pytest.mark.parametrize("share", [0.0, -0.1, 1.5])
def test_a_share_outside_the_range_is_refused(share: float) -> None:
    with pytest.raises(ValueError):
        percentile([1.0], share)


def test_percentiles_take_each_share_of_one_sorting() -> None:
    values = [10, 3, 7, 1, 5]
    assert percentiles(values, (0.5, 0.9, 1.0)) == [5, 10, 10]
    assert percentiles([], (0.5, 0.9)) == [None, None]
    with pytest.raises(ValueError):
        percentiles(values, (0.5, 0.0))
