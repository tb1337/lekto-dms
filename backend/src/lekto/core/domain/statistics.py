"""Middle values of durations and counts for the page "System": the median and the percentile
by nearest rank (the value below which the share lies, one of the values itself), so that a few
outliers (a model that timed out for hours) do not move them as they move a mean."""

import math
from collections.abc import Sequence
from datetime import timedelta


def percentile[T: (int, float, timedelta)](values: Sequence[T], share: float) -> T | None:
    """The value at `share` (0 < share ≤ 1) of `values` by nearest rank; None without values."""
    return percentiles(values, (share,))[0]


def percentiles[T: (int, float, timedelta)](
    values: Sequence[T], shares: Sequence[float]
) -> list[T | None]:
    """The values at each of `shares` (as `percentile`), sorting `values` once."""
    if not all(0 < share <= 1 for share in shares):
        raise ValueError("share must lie in (0, 1]")
    if not values:
        return [None for _ in shares]
    ordered = sorted(values)
    return [ordered[max(0, math.ceil(share * len(ordered)) - 1)] for share in shares]


def median[T: (int, float, timedelta)](values: Sequence[T]) -> T | None:
    """The middle value of `values` (the lower one of an even count); None without values."""
    return percentile(values, 0.5)
