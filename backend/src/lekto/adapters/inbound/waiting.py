"""Waiting for work instead of polling for it: the worker's job loops and the event dispatch
of worker and API (`dispatch_events`).

A loop that finds nothing asks when something is due next (`JobQueue.next_due`,
`EventBus.next_due`) and waits until then, or until a signal says that a commit queued
something (`Wakeup`), whichever comes first. Signals can be lost, so the wait ends after
`SAFETY_NET` at the latest and the loop looks again. Where signals from other processes do
not arrive (SQLite; Postgres while the listening connection is down) the loop polls instead,
starting at its poll interval and waiting longer after every idle round, at most
`IDLE_BACKOFF_MAX`; a round that finds work starts over.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable
from datetime import timedelta

from lekto.adapters.inbound.backoff import backoff
from lekto.core.ports.event_bus import EventBus
from lekto.core.ports.wakeup import Signal

log = logging.getLogger(__name__)

SAFETY_NET = timedelta(seconds=60)
"""The longest wait for a signal; after it the loop looks for work in any case."""
IDLE_BACKOFF_MAX = timedelta(seconds=5)
"""The longest wait between two polls while no signal reaches the loop."""


class Idle:
    """How a loop waits while it has nothing to do."""

    def __init__(self, signal: Signal, poll_interval: timedelta, stopping: asyncio.Event) -> None:
        self._signal = signal
        self._poll = poll_interval
        self._stopping = stopping
        self._rounds = 0  # idle rounds in a row

    def found(self) -> None:
        """The loop found work: the next idle wait starts short again."""
        self._rounds = 0

    async def wait(self, *, due_in: timedelta | None) -> None:
        """Wait for a signal, for `due_in` (until something is due; None: nothing is), or
        until the loop should look again; at once if the worker stops."""
        if self._signal.live:
            limit = SAFETY_NET
        else:
            limit = backoff(self._poll, self._rounds, limit=IDLE_BACKOFF_MAX)
        self._rounds += 1
        timeout = limit if due_in is None else max(min(limit, due_in), timedelta(0))
        await unless_stopped(self._stopping, self._signal.wait(timeout))


async def unless_stopped[T](stopping: asyncio.Event, awaitable: Awaitable[T]) -> T | None:
    """Await `awaitable`, or stop waiting (and cancel it) once `stopping` is set: then None."""
    task = asyncio.ensure_future(awaitable)
    stop = asyncio.ensure_future(stopping.wait())
    try:
        await asyncio.wait({task, stop}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for pending in (task, stop):
            if not pending.done():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pending
    return task.result() if task.done() and not task.cancelled() else None


async def sleep_unless_stopped(stopping: asyncio.Event, duration: timedelta) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stopping.wait(), timeout=duration.total_seconds())


async def dispatch_events(
    bus: EventBus, signal: Signal, interval: timedelta, stopping: asyncio.Event
) -> None:
    """Deliver outbox events to this process's subscribers until `stopping` is set: when a
    commit signals events, when a failed delivery is due again, and at the safety net.
    After an error the loop waits `interval`, doubling up to `backoff.MAX_BACKOFF`."""
    idle = Idle(signal, interval, stopping)
    failures = 0
    while not stopping.is_set():
        try:
            due_in = await bus.due_in()
            if due_in is not None and due_in <= timedelta(0):
                idle.found()
                while not stopping.is_set() and await bus.dispatch() > 0:
                    pass
                continue
        except Exception:
            failures += 1
            log.exception("event dispatch failed", extra={"failures": failures})
            await sleep_unless_stopped(stopping, backoff(interval, failures))
            continue
        failures = 0
        await idle.wait(due_in=due_in)
