"""A report kept for a short while: what the page "System" shows is counted over many rows and
asked for by every open page, so a count that is at most a minute old is answered again
instead of counted again. One cache per process; with several API processes, each counts."""

from collections.abc import Awaitable, Callable, Hashable
from datetime import datetime, timedelta
from typing import cast

from lekto.core.ports.clock import Clock

KEPT = timedelta(minutes=1)
"""How long a report is kept before it is counted again."""


class Kept:
    def __init__(self, clock: Clock, period: timedelta = KEPT) -> None:
        self._clock = clock
        self._period = period
        self._kept: dict[Hashable, tuple[datetime, object]] = {}

    async def get[T](self, key: Hashable, count: Callable[[], Awaitable[T]]) -> T:
        """The report under `key` counted within the period, else counted now and kept.
        Reports that fell out of the period are forgotten with every count."""
        now = self._clock.now()
        kept = self._kept.get(key)
        if kept is not None and now - kept[0] < self._period:
            return cast(T, kept[1])
        report = await count()
        self._kept = {k: v for k, v in self._kept.items() if now - v[0] < self._period}
        self._kept[key] = (now, report)
        return report
