"""In-process signals: a MemoryDatabase tells its wakeups what every commit queued."""

import asyncio
import contextlib
from collections.abc import Collection
from datetime import timedelta

from lekto.adapters.outbound.memory.database import MemoryDatabase
from lekto.core.ports.wakeup import Channel


class MemorySignal:
    """A subscription: a flag that a signal set, cleared by the wait that saw it."""

    def __init__(self, channel: Channel, kinds: Collection[str] | None, live: bool) -> None:
        self.channel = channel
        self.kinds = None if kinds is None else frozenset(kinds)
        self.live = live
        self._event = asyncio.Event()

    def raise_for(self, channel: Channel, kind: str | None) -> None:
        if channel is self.channel and (self.kinds is None or kind in self.kinds):
            self._event.set()

    def raise_now(self) -> None:
        self._event.set()

    async def wait(self, timeout: timedelta) -> bool:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._event.wait(), timeout=timeout.total_seconds())
        if not self._event.is_set():
            return False
        self._event.clear()
        return True


class MemoryWakeup:
    """Signals of one in-memory database. Every process has its own database, so its signals
    reach every receiver there is: the subscriptions are `live`."""

    def __init__(self, database: MemoryDatabase) -> None:
        self._signals: list[MemorySignal] = []
        self._closed = False
        database.listeners.append(self._signal)

    def subscribe(self, channel: Channel, *, kinds: Collection[str] | None = None) -> MemorySignal:
        if self._closed:
            raise RuntimeError("the wakeup is closed")
        signal = MemorySignal(channel, kinds, live=True)
        self._signals.append(signal)
        return signal

    async def aclose(self) -> None:
        self._closed = True
        self._signals = []

    def _signal(self, channel: Channel, kind: str | None) -> None:
        for signal in self._signals:
            signal.raise_for(channel, kind)
