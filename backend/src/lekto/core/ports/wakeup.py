"""Waking a process that waits for work, so that it need not poll the database.

A signal is sent by the unit of work that commits a job becoming queued (`enqueue`,
`reschedule`, `release`, `retry`; channel `JOBS`, with the job's kind) or events added to the
outbox (channel `EVENTS`). It arrives after the commit, never after a rollback. A signal is a
hint, not a guarantee: an adapter may lose one (a connection that broke), so a receiver also
looks at the queue now and then (a safety net) and whenever `Signal.live` is False.
"""

from collections.abc import Collection
from datetime import timedelta
from enum import StrEnum
from typing import Protocol


class Channel(StrEnum):
    JOBS = "jobs"
    EVENTS = "events"


class Signal(Protocol):
    """One receiver's subscription to a channel."""

    @property
    def live(self) -> bool:
        """Whether signals from other processes reach this one at the moment. False: the
        receiver has to poll, e.g. on SQLite (processes share nothing but the file) or while
        the connection that listens is down."""
        ...

    async def wait(self, timeout: timedelta) -> bool:
        """Wait for a signal, at most `timeout`; True if one came, False on timeout. A signal
        that arrived since the previous wait (or since subscribing) counts at once, so nothing
        is missed between waits; several signals meanwhile count as one."""
        ...


class Wakeup(Protocol):
    """Signals of the database this process works on. `aclose` ends listening.

    First adapters: in-process events (memory, SQLite) and `LISTEN/NOTIFY` (Postgres).
    """

    def subscribe(self, channel: Channel, *, kinds: Collection[str] | None = None) -> Signal:
        """Receive the signals of `channel`; on `JOBS` only those of the job `kinds` (None:
        all). The subscription lasts until `aclose`."""
        ...

    async def aclose(self) -> None: ...
