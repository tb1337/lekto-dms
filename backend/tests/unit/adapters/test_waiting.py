"""How a loop waits while it has nothing to do (`waiting.Idle`), and how a wait ends."""

import asyncio
from datetime import timedelta

from lekto.adapters.inbound.waiting import (
    IDLE_BACKOFF_MAX,
    SAFETY_NET,
    Idle,
    unless_stopped,
)

POLL = timedelta(milliseconds=10)


class FakeSignal:
    """Records the timeouts it is asked to wait for; never signals."""

    def __init__(self, live: bool) -> None:
        self.live = live
        self.timeouts: list[timedelta] = []

    async def wait(self, timeout: timedelta) -> bool:
        self.timeouts.append(timeout)
        return False


async def test_without_live_signals_the_wait_doubles_up_to_the_limit() -> None:
    signal = FakeSignal(live=False)
    idle = Idle(signal, POLL, asyncio.Event())
    for _ in range(12):
        await idle.wait(due_in=None)
    assert signal.timeouts[:4] == [POLL, POLL * 2, POLL * 4, POLL * 8]
    assert signal.timeouts[-1] == IDLE_BACKOFF_MAX
    idle.found()
    await idle.wait(due_in=None)
    assert signal.timeouts[-1] == POLL, "after work the wait starts short again"


async def test_with_live_signals_the_wait_is_the_safety_net() -> None:
    signal = FakeSignal(live=True)
    idle = Idle(signal, POLL, asyncio.Event())
    await idle.wait(due_in=None)
    await idle.wait(due_in=None)
    assert signal.timeouts == [SAFETY_NET, SAFETY_NET]


async def test_the_wait_ends_when_something_is_due() -> None:
    live, polling = FakeSignal(live=True), FakeSignal(live=False)
    await Idle(live, POLL, asyncio.Event()).wait(due_in=timedelta(seconds=3))
    await Idle(polling, POLL, asyncio.Event()).wait(due_in=timedelta(milliseconds=3))
    await Idle(live, POLL, asyncio.Event()).wait(due_in=timedelta(seconds=-5))
    assert live.timeouts == [timedelta(seconds=3), timedelta(0)]
    assert polling.timeouts == [timedelta(milliseconds=3)]


async def test_stopping_ends_a_wait_at_once() -> None:
    stopping = asyncio.Event()
    forever = asyncio.Event()
    waiting = asyncio.create_task(unless_stopped(stopping, forever.wait()))
    await asyncio.sleep(0.01)
    assert not waiting.done()
    stopping.set()
    assert await asyncio.wait_for(waiting, timeout=1) is None
    assert await unless_stopped(asyncio.Event(), asyncio.sleep(0, result=42)) == 42
