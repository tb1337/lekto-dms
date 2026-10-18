"""The cleanup job removes old finished jobs, delivered events, ended sessions, stale counts
of failed sign-ins and what only the inbox's done needs, and schedules itself."""

import asyncio
from datetime import datetime, timedelta

import pytest

from papiq.adapters.outbound.memory import MemoryEventBus
from papiq.core.domain.errors import AuthenticationError
from papiq.core.domain.ids import DocumentId, EventId, new_id
from papiq.core.domain.inbox import DONE_PERIOD, Confirmation
from papiq.core.domain.jobs import JobStatus
from papiq.core.domain.webhooks import DeliveryOutcome, WebhookDelivery
from papiq.core.services.maintenance import CLEANUP_JOB, REMOVE_FILES_JOB, MaintenanceService
from papiq.core.services.objects import derivative_keys, original_key
from tests import builders
from tests.builders import PASSWORD, incoming
from tests.unit.services.support import World

INTERVAL = timedelta(hours=1)
RETENTION = timedelta(days=7)


def maintenance(world: World, bus: MemoryEventBus | None = None) -> MaintenanceService:
    return MaintenanceService(
        world.uow,
        world.clock,
        bus or MemoryEventBus(world.database, clock=world.clock, retry=builders.EVENT_RETRY),
        interval=INTERVAL,
        retention=RETENTION,
        session_idle=builders.DEFAULT_SETTINGS.session_idle_timeout,
        object_store=world.object_store,
    )


def cleanup_jobs(world: World) -> list[JobStatus]:
    return [job.status for job in world.database.jobs.values() if job.kind == CLEANUP_JOB]


async def test_schedule_queues_one_cleanup(world: World) -> None:
    service = maintenance(world)
    await service.schedule()
    await service.schedule()
    assert cleanup_jobs(world) == [JobStatus.QUEUED]


async def test_cleanup_runs_and_schedules_the_next_one(world: World) -> None:
    service = maintenance(world)
    owner = await world.user()
    await world.pipeline().receive(owner.id, incoming(b"%PDF-1"), filename="a.pdf")
    await world.drain()
    step_jobs = len(world.database.jobs)

    await service.schedule()
    world.clock.advance(RETENTION)  # the node jobs are not older than the retention yet
    assert await service.run_next_job()
    assert len(world.database.jobs) == step_jobs + 2
    assert sorted(cleanup_jobs(world)) == [JobStatus.DONE, JobStatus.QUEUED]
    assert not await service.run_next_job()  # the next one is due in an hour

    world.clock.advance(INTERVAL)
    assert await service.run_next_job()
    assert sorted(cleanup_jobs(world)) == [JobStatus.DONE, JobStatus.QUEUED]  # old run removed
    assert len(world.database.jobs) == 2


async def test_delivered_events_are_purged(world: World) -> None:
    bus = MemoryEventBus(world.database, clock=world.clock, retry=builders.EVENT_RETRY)
    received: list[object] = []

    async def handler(event: object) -> None:
        received.append(event)

    bus.subscribe("test", handler)
    owner = await world.user()
    await world.pipeline().receive(owner.id, incoming(b"%PDF-1"), filename="a.pdf")
    await bus.dispatch()
    service = maintenance(world, bus)
    await service.schedule()
    world.clock.set(max(world.database.recorded_at.values()) + RETENTION + timedelta(seconds=1))
    assert await service.run_next_job()
    assert len(world.database.purged) == len(received) == 2


async def test_a_failed_cleanup_is_tried_again_later(world: World) -> None:
    class BrokenBus(MemoryEventBus):
        async def purge(self, *, before: datetime) -> int:
            raise OSError("disk full")

    service = maintenance(world, BrokenBus(world.database, retry=builders.EVENT_RETRY))
    await service.schedule()
    assert await service.run_next_job()
    (job,) = world.database.jobs.values()
    assert (job.status, job.run_at, job.last_error) == (
        JobStatus.QUEUED,
        world.clock.now() + INTERVAL,
        "OSError('disk full')",
    )


async def test_cleanup_removes_ended_sessions_and_old_failures(world: World) -> None:
    service = maintenance(world)
    await world.account("alice")
    signed_in = await world.auth.login("alice", PASSWORD)
    with pytest.raises(AuthenticationError):
        await world.auth.login("alice", "wrong password!")
    await service.schedule()
    world.clock.advance(timedelta(days=1, minutes=1))  # session idle, failure past its window
    assert await service.run_next_job()
    async with world.uow() as uow:
        assert await uow.sessions.find_by_token(signed_in.session.token_hash) is None
        assert await uow.login_failures.find("account:alice") is None


async def test_deleting_a_document_removes_its_files(world: World) -> None:
    service = maintenance(world)
    alice, bob = await world.user(), await world.user()
    shared_file, own_file = b"%PDF-1.7 same", b"%PDF-1.7 alice only"
    kept = await world.pipeline().receive(alice.id, incoming(shared_file), filename="a.pdf")
    gone = await world.pipeline().receive(alice.id, incoming(own_file), filename="b.pdf")
    other = await world.pipeline().receive(bob.id, incoming(shared_file), filename="c.pdf")
    await world.drain()
    for document in (kept, gone):
        for key in derivative_keys(document.id, 2):
            await world.object_store.put(key, b"x", content_type="x")
    async with world.uow() as uow:
        for document in (kept, gone):
            stored = await uow.documents.get(document.id)
            stored.set_page_count(2, world.clock.now())
            await uow.documents.update(stored)
        await uow.commit()

    await world.documents.delete(alice.id, gone.id)
    await world.documents.delete(alice.id, kept.id)
    assert await service.run_next_job() and await service.run_next_job()
    assert not await service.run_next_job()

    for document in (kept, gone):
        for key in derivative_keys(document.id, 2):
            assert not await world.object_store.exists(key)
    assert not await world.object_store.exists(original_key(gone.sha256))
    assert await world.object_store.exists(original_key(other.sha256))  # Bob still has it
    assert [j.status for j in world.database.jobs.values() if j.kind == REMOVE_FILES_JOB] == [
        JobStatus.DONE,
        JobStatus.DONE,
    ]


async def test_removing_files_is_retried(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    service = maintenance(world)
    owner = await world.user()
    document = await world.pipeline().receive(owner.id, incoming(b"%PDF-1.7 x"), filename="x.pdf")
    await world.drain()
    await world.documents.delete(owner.id, document.id)

    async def broken(key: str) -> None:
        raise OSError("storage unreachable")

    monkeypatch.setattr(world.object_store, "delete", broken)
    assert await service.run_next_job()
    [job] = [j for j in world.database.jobs.values() if j.kind == REMOVE_FILES_JOB]
    assert job.status is JobStatus.QUEUED and job.last_error is not None
    monkeypatch.undo()
    world.clock.advance(timedelta(minutes=1))
    assert await service.run_next_job()
    assert not await world.object_store.exists(original_key(document.sha256))


async def test_cleanup_removes_old_webhook_deliveries(world: World) -> None:
    service = maintenance(world)
    user = await world.user()
    hook = (
        await world.webhooks.create(user.id, name="x", url="http://x.lan/hook", event_types=["*"])
    ).webhook

    def delivery(at: timedelta) -> WebhookDelivery:
        return WebhookDelivery.record(
            webhook_id=hook.id,
            event_id=EventId(new_id()),
            event_type="document.filed",
            document_id=DocumentId(new_id()),
            attempt=1,
            started_at=world.clock.now() + at,
            duration_ms=5,
            outcome=DeliveryOutcome.DELIVERED,
            status_code=200,
        )

    old, recent = delivery(-RETENTION - timedelta(hours=1)), delivery(-RETENTION / 2)
    async with world.uow() as uow:
        await uow.webhooks.add_delivery(old)
        await uow.webhooks.add_delivery(recent)
        await uow.commit()
    await service.schedule()
    assert await service.run_next_job()
    async with world.uow() as uow:
        assert [d.id for d in await uow.webhooks.deliveries(hook.id)] == [recent.id]


async def test_cleanup_drops_previous_webhook_secrets_after_the_grace_period(world: World) -> None:
    service = maintenance(world)
    user = await world.user()
    grace = timedelta(hours=24)
    first = (
        await world.webhooks.create(user.id, name="a", url="http://x.lan/a", event_types=["*"])
    ).webhook
    second = (
        await world.webhooks.create(user.id, name="b", url="http://x.lan/b", event_types=["*"])
    ).webhook
    await world.webhooks.renew_secret(user.id, first.id)
    world.clock.advance(grace / 2)
    await world.webhooks.renew_secret(user.id, second.id)
    world.clock.advance(grace / 2)  # the first grace period is over, the second half-way
    await service.schedule()
    assert await service.run_next_job()
    first, second = (
        await world.webhooks.get(user.id, first.id),
        await world.webhooks.get(user.id, second.id),
    )
    assert first.previous_secret is None and first.previous_valid_until is None
    assert second.previous_secret is not None
    assert first.updated_at == world.clock.now()


async def test_cleanup_removes_what_only_done_needs_after_its_period(world: World) -> None:
    """Who confirmed a document is kept for the inbox's done, 14 days; a seen mark as long as
    it tells that the document is not new."""
    service = maintenance(world)
    owner = await world.user()
    space = await world.default_space(owner)
    confirmed, seen = builders.processed(owner, space), builders.processed(owner, space)
    confirmed.new_at = None
    async with world.uow() as uow:
        for document in (confirmed, seen):
            await uow.documents.add(document)
        await uow.inbox.record_confirmation(confirmed.id, Confirmation(owner.id, world.clock.now()))
        await uow.inbox.mark_seen(owner.id, seen.id, world.clock.now())
        await uow.inbox.mark_seen(owner.id, confirmed.id, world.clock.now())  # tells nothing
        await uow.commit()
    world.clock.advance(DONE_PERIOD)
    await service.schedule()
    assert await service.run_next_job()
    assert world.database.confirmations == {confirmed.id: Confirmation(owner.id, builders.NOW)}
    world.clock.advance(INTERVAL)
    assert await service.run_next_job()
    assert world.database.confirmations == {}
    assert world.database.seen == {(owner.id, seen.id): builders.NOW}


async def test_a_cancelled_cleanup_gives_its_job_back_at_once(world: World) -> None:
    started = asyncio.Event()

    class SlowBus(MemoryEventBus):
        async def purge(self, *, before: datetime) -> int:
            started.set()
            await asyncio.Event().wait()  # until cancelled
            return 0

    service = maintenance(world, SlowBus(world.database, retry=builders.EVENT_RETRY))
    await service.schedule()
    task = asyncio.create_task(service.run_next_job())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    (job,) = world.database.jobs.values()
    assert (job.status, job.tries, job.last_error) == (
        JobStatus.QUEUED,
        0,
        "interrupted: the worker stopped",
    )
