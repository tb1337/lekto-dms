"""Contract of `Wakeup`: what a commit signals, and nothing before it."""

from datetime import timedelta
from typing import Protocol

import pytest

from lekto.core.domain.ids import JobId
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from lekto.core.ports.wakeup import Channel, Signal, Wakeup
from tests.builders import NOW
from tests.contracts.event_bus import received

SOON = timedelta(seconds=5)
"""Long enough for a signal across a connection; a test waits this long only when it fails."""
NOT = timedelta(milliseconds=50)
"""A wait that should time out."""


class WakeupFactory(Protocol):
    """Creates a wakeup on the same database as `uow_factory`."""

    def __call__(self) -> Wakeup: ...


async def enqueue(
    uow_factory: UnitOfWorkFactory, kind: str = "test", *, commit: bool = True
) -> JobId | None:
    async with uow_factory() as uow:
        job = await uow.jobs.enqueue(kind, {}, run_at=NOW)
        if commit:
            await uow.commit()
    return job


class WakeupContract:
    """Needs the fixtures `uow_factory` and `wakeup_factory`."""

    @pytest.fixture
    async def wakeup(self, wakeup_factory: WakeupFactory) -> Wakeup:
        return wakeup_factory()

    async def ready(self, wakeup: Wakeup, signal: Signal) -> None:
        """Wait until signals reach `signal`: an adapter that connects first overrides this.
        A signal raised meanwhile (e.g. once the adapter connected) is consumed."""
        await signal.wait(NOT)

    async def test_an_enqueued_job_signals_after_commit(
        self, uow_factory: UnitOfWorkFactory, wakeup: Wakeup
    ) -> None:
        signal = wakeup.subscribe(Channel.JOBS)
        await self.ready(wakeup, signal)
        assert not await signal.wait(NOT)
        await enqueue(uow_factory)
        assert await signal.wait(SOON)
        assert not await signal.wait(NOT)
        await wakeup.aclose()

    async def test_nothing_is_signalled_before_the_commit(
        self, uow_factory: UnitOfWorkFactory, wakeup: Wakeup
    ) -> None:
        signal = wakeup.subscribe(Channel.JOBS)
        await self.ready(wakeup, signal)
        async with uow_factory() as uow:
            await uow.jobs.enqueue("test", {}, run_at=NOW)
            await uow.outbox.add([received()])
            assert not await signal.wait(NOT)
            await uow.commit()
        assert await signal.wait(SOON)
        await wakeup.aclose()

    async def test_a_rollback_signals_nothing(
        self, uow_factory: UnitOfWorkFactory, wakeup: Wakeup
    ) -> None:
        jobs = wakeup.subscribe(Channel.JOBS)
        events = wakeup.subscribe(Channel.EVENTS)
        await self.ready(wakeup, jobs)
        await self.ready(wakeup, events)
        async with uow_factory() as uow:
            await uow.jobs.enqueue("test", {}, run_at=NOW)
            await uow.outbox.add([received()])
            await uow.rollback()
        await enqueue(uow_factory, commit=False)
        assert not await jobs.wait(NOT)
        assert not await events.wait(NOT)
        await wakeup.aclose()

    async def test_jobs_signal_their_kinds(
        self, uow_factory: UnitOfWorkFactory, wakeup: Wakeup
    ) -> None:
        mine = wakeup.subscribe(Channel.JOBS, kinds=["a", "b"])
        others = wakeup.subscribe(Channel.JOBS, kinds=["c"])
        every = wakeup.subscribe(Channel.JOBS)
        await self.ready(wakeup, mine)
        await self.ready(wakeup, others)
        await self.ready(wakeup, every)
        await enqueue(uow_factory, "b")
        assert await mine.wait(SOON)
        assert await every.wait(SOON)
        assert not await others.wait(NOT)
        await wakeup.aclose()

    async def test_events_signal_their_channel_only(
        self, uow_factory: UnitOfWorkFactory, wakeup: Wakeup
    ) -> None:
        jobs = wakeup.subscribe(Channel.JOBS)
        events = wakeup.subscribe(Channel.EVENTS)
        await self.ready(wakeup, jobs)
        await self.ready(wakeup, events)
        async with uow_factory() as uow:
            await uow.outbox.add([received()])
            await uow.commit()
        assert await events.wait(SOON)
        assert not await jobs.wait(NOT)
        await wakeup.aclose()

    async def test_a_job_queued_again_signals(
        self, uow_factory: UnitOfWorkFactory, wakeup: Wakeup
    ) -> None:
        signal = wakeup.subscribe(Channel.JOBS, kinds=["test"])
        await self.ready(wakeup, signal)
        await enqueue(uow_factory)
        assert await signal.wait(SOON)
        async with uow_factory() as uow:
            job = await uow.jobs.claim(now=NOW, lease=timedelta(minutes=1))
            await uow.commit()
        assert job is not None
        assert not await signal.wait(NOT), "a claim is no signal"
        async with uow_factory() as uow:
            await uow.jobs.reschedule(job, run_at=NOW + timedelta(hours=1), error="later")
            await uow.commit()
        assert await signal.wait(SOON), "a rescheduled job signals"
        async with uow_factory() as uow:
            job = await uow.jobs.claim(now=NOW + timedelta(hours=1), lease=timedelta(minutes=1))
            await uow.commit()
        assert job is not None
        async with uow_factory() as uow:
            await uow.jobs.release(job, run_at=NOW, error="stopped")
            await uow.commit()
        assert await signal.wait(SOON), "a released job signals"
        async with uow_factory() as uow:
            job = await uow.jobs.claim(now=NOW + timedelta(hours=1), lease=timedelta(minutes=1))
            assert job is not None
            await uow.jobs.fail(job, now=NOW, error="broken")
            await uow.commit()
        assert not await signal.wait(NOT), "a failed job is no signal"
        async with uow_factory() as uow:
            await uow.jobs.retry(job.id, now=NOW)
            await uow.commit()
        assert await signal.wait(SOON), "a retried job signals"
        await wakeup.aclose()

    async def test_signals_between_waits_count_once(
        self, uow_factory: UnitOfWorkFactory, wakeup: Wakeup
    ) -> None:
        signal = wakeup.subscribe(Channel.JOBS)
        await self.ready(wakeup, signal)
        await enqueue(uow_factory)
        await enqueue(uow_factory)
        assert await signal.wait(SOON)
        # At most one more: the two commits may have arrived as two signals, never as three.
        await signal.wait(NOT)
        assert not await signal.wait(NOT)
        await wakeup.aclose()

    async def test_a_closed_wakeup_takes_no_subscriptions(self, wakeup: Wakeup) -> None:
        await wakeup.aclose()
        with pytest.raises(RuntimeError):
            wakeup.subscribe(Channel.JOBS)
