"""How long a loop waits after errors (the worker's loops, the event dispatch) or while it
finds nothing to do and no signal reaches it (`waiting`): the interval, doubling with every
failure or idle round in a row, at most `limit` (`MAX_BACKOFF` for errors)."""

from datetime import timedelta

MAX_BACKOFF = timedelta(seconds=30)


def backoff(interval: timedelta, failures: int, *, limit: timedelta = MAX_BACKOFF) -> timedelta:
    return min(interval * (1 << min(failures, 10)), limit)
