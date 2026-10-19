"""How long a loop waits after errors (the worker's loops, the API's event dispatch): the
interval, doubling with every failure in a row, at most `MAX_BACKOFF`."""

from datetime import timedelta

MAX_BACKOFF = timedelta(seconds=30)


def backoff(interval: timedelta, failures: int) -> timedelta:
    return min(interval * (1 << min(failures, 10)), MAX_BACKOFF)
