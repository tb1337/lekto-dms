"""The worker service on in-memory adapters: runs jobs, delivers events, stops cleanly."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from lekto.adapters.inbound.worker import Worker
from lekto.adapters.outbound.memory import MemoryEventBus, MemorySearchIndex
from lekto.adapters.outbound.memory.unit_of_work import MemoryJobQueue
from lekto.composition.container import Container, Services, build_memory_container
from lekto.composition.container import build_services as build_all_services
from lekto.core.domain.documents import Document
from lekto.core.domain.events import DocumentReceived, DomainEvent, LaneChanged
from lekto.core.domain.ids import JobId
from lekto.core.domain.jobs import Job, JobStatus
from lekto.core.domain.pipeline import Lane, Node, NodeResult
from lekto.core.domain.users import Role, User
from lekto.core.services._jobs import NODE_JOB
from lekto.core.services.indexing import SUBSCRIBER
from lekto.core.services.maintenance import CLEANUP_JOB, REMOVE_FILES_JOB
from tests import builders
from tests.api import until
from tests.builders import DEFAULT_SETTINGS, SAMPLES, incoming

FAST = timedelta(milliseconds=10)


def worker(
    container: Container,
    services: Services,
    *,
    shutdown_timeout: timedelta = timedelta(seconds=5),
    **extra: Any,
) -> Worker:
    """A worker that polls often; `extra` are further arguments (`indexing`, `master_data`)."""
    return Worker(
        pipeline=services.pipeline,
        maintenance=services.maintenance,
        event_bus=container.event_bus,
        unit_of_work=container.unit_of_work,
        clock=container.clock,
        wakeup=container.wakeup,
        concurrency=2,
        poll_interval=FAST,
        dispatch_interval=FAST,
        shutdown_timeout=shutdown_timeout,
        webhook_concurrency=DEFAULT_SETTINGS.webhook_concurrency,
        **extra,
    )


@asynccontextmanager
async def running(service: Worker) -> AsyncIterator[asyncio.Task[None]]:
    task = asyncio.create_task(service.run())
    try:
        yield task
    finally:
        service.stop()
        await asyncio.wait_for(task, timeout=10)


async def owner(container: Container) -> User:
    return await builders.seed_user(container.unit_of_work)


async def lane(services: Services, user: User, document: Document) -> Lane | None:
    return (await services.documents.get(user.id, document.id)).lane


class Slow:
    def __init__(self, seconds: float | None) -> None:
        self.seconds = seconds
        self.started = asyncio.Event()

    async def run(self, document: Document) -> NodeResult:
        self.started.set()
        if self.seconds is None:
            await asyncio.Event().wait()
        await asyncio.sleep(self.seconds or 0)
        return builders.OK


def build_services(container: Container) -> Services:
    services = build_all_services(container)
    builders.skip_classification(services.pipeline)
    return services


def with_ocr(services: Services, executor: Slow) -> Services:
    pipeline = services.pipeline
    pipeline.replace_executor(Node.OCR, executor)
    return replace(services, pipeline=pipeline)


async def test_documents_are_processed_and_events_delivered() -> None:
    container = build_memory_container()
    services = build_services(container)
    received: list[DomainEvent] = []

    async def record(event: DomainEvent) -> None:
        received.append(event)

    container.event_bus.subscribe("test", record)
    user = await owner(container)
    async with running(worker(container, services)):
        document = await services.pipeline.receive(
            user.id, incoming((SAMPLES / "scan.pdf").read_bytes()), filename="a.pdf"
        )
        await until(lambda: received and received[-1].type == LaneChanged.type)
    assert await lane(services, user, document) is Lane.GREEN
    assert received[0].type == DocumentReceived.type


async def test_documents_reach_the_search_index() -> None:
    container = build_memory_container()
    services = build_services(container)
    index = container.search_index
    assert isinstance(index, MemorySearchIndex) and services.indexing is not None
    container.event_bus.subscribe(SUBSCRIBER, services.indexing.on_event)
    user = await owner(container)
    async with running(worker(container, services, indexing=services.indexing)):
        document = await services.pipeline.receive(
            user.id, incoming((SAMPLES / "scan.pdf").read_bytes()), filename="invoice.pdf"
        )
        await until(lambda: index.documents.get(document.id) is not None)
        await until(lambda: index.documents[document.id].lane_value == "green")
    assert index.documents[document.id].filename == "invoice.pdf"
    async with container.unit_of_work() as uow:  # the reconciliation is scheduled as well
        job = await uow.jobs.claim(now=container.clock.now() + timedelta(days=1), lease=FAST)
    assert job is not None


async def test_the_pipeline_goes_before_the_index(monkeypatch: pytest.MonkeyPatch) -> None:
    container = build_memory_container()
    services = build_services(container)
    assert services.indexing is not None
    calls: list[str] = []

    def jobs(name: str, count: int) -> Callable[[], Awaitable[bool]]:
        async def run_next_job() -> bool:
            nonlocal count
            if not count:
                return False
            count -= 1
            calls.append(name)
            return True

        return run_next_job

    monkeypatch.setattr(services.pipeline, "run_next_job", jobs("pipeline", 3))
    monkeypatch.setattr(services.indexing, "run_next_job", jobs("index", 3))
    async with running(worker(container, services, indexing=services.indexing)):
        await until(lambda: len(calls) == 6)
    assert calls == ["pipeline"] * 3 + ["index"] * 3


async def test_a_moved_tag_is_normalised_at_its_documents() -> None:
    container = build_memory_container()
    services = build_services(container)
    user = await owner(container)
    admin = await builders.seed_user(container.unit_of_work, role=Role.ADMIN)
    master = services.master_data
    insurance = await master.create_tag(admin.id, "Insurance")
    health = await master.create_tag(admin.id, "Health")
    async with container.unit_of_work() as uow:
        space = await uow.spaces.get_personal(user.id)
        document = builders.run_pipeline(builders.document(user, space))
        document.tag_ids = {insurance.id, health.id}
        await uow.documents.add(document)
        await uow.commit()
    async with running(worker(container, services, master_data=master)):
        await master.change_tag(admin.id, health.id, parent_id=insurance.id)

        async def moved() -> bool:
            return (await services.documents.get(user.id, document.id)).tag_ids == {health.id}

        await until(moved, every=0.01, what="the tag of the document moved")


async def test_the_cleanup_is_scheduled_at_start() -> None:
    container = build_memory_container()
    services = build_services(container)

    async def next_job() -> Job | None:
        """The job due first, claimed without a commit: it stays queued."""
        async with container.unit_of_work() as uow:
            return await uow.jobs.claim(now=container.clock.now() + timedelta(days=1), lease=FAST)

    async with running(worker(container, services)):
        await until(next_job, what="a job is queued")
    job = await next_job()
    assert job is not None and job.kind == CLEANUP_JOB


async def test_stop_lets_running_jobs_finish() -> None:
    container = build_memory_container()
    node = Slow(0.2)
    services = with_ocr(build_services(container), node)
    user = await owner(container)
    document = await services.pipeline.receive(
        user.id, incoming((SAMPLES / "scan.pdf").read_bytes()), filename="a.pdf"
    )
    async with running(worker(container, services)):
        await node.started.wait()
    log = await services.documents.processing_log(user.id, document.id)
    nodes = [entry.node for entry in log]
    assert Node.OCR in nodes and Node.PARSE not in nodes  # nothing new after stop
    assert set(nodes) <= {Node.RECEIVE, Node.OCR, Node.PAGES}


async def test_jobs_still_running_after_the_timeout_are_released() -> None:
    container = build_memory_container()
    node = Slow(None)
    services = with_ocr(build_services(container), node)
    user = await owner(container)
    await services.pipeline.receive(
        user.id, incoming((SAMPLES / "scan.pdf").read_bytes()), filename="a.pdf"
    )
    async with running(worker(container, services, shutdown_timeout=FAST)):
        await node.started.wait()
    async with container.unit_of_work() as uow:
        job = await uow.jobs.claim(now=container.clock.now(), lease=FAST, kinds=[NODE_JOB])
    assert job is not None
    assert (job.attempts, job.last_error) == (2, "interrupted: the worker stopped")


async def test_a_failing_loop_keeps_running(monkeypatch: pytest.MonkeyPatch) -> None:
    container = build_memory_container()
    services = build_services(container)
    user = await owner(container)
    await services.pipeline.receive(
        user.id, incoming((SAMPLES / "scan.pdf").read_bytes()), filename="a.pdf"
    )
    container.event_bus.subscribe("test", _ignore)  # without a subscriber nothing is due
    calls = 0
    original = MemoryEventBus.dispatch

    async def flaky(self: MemoryEventBus, *, limit: int = 100) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("database gone")
        return await original(self, limit=limit)

    monkeypatch.setattr(MemoryEventBus, "dispatch", flaky)
    async with running(worker(container, services)):
        await until(lambda: calls >= 2)


async def _ignore(event: DomainEvent) -> None:
    pass


async def enqueue_removal(container: Container, run_at: timedelta) -> JobId:
    """A `documents.remove_files` job with an empty payload: the maintenance fails it as
    invalid as soon as it runs, which is what these tests look for."""
    async with container.unit_of_work() as uow:
        job = await uow.jobs.enqueue(REMOVE_FILES_JOB, {}, run_at=container.clock.now() + run_at)
        await uow.commit()
    assert job is not None
    return job


async def status(container: Container, job: JobId) -> JobStatus:
    async with container.unit_of_work() as uow:
        return (await uow.jobs.get(job)).status


async def finished(container: Container, job: JobId) -> bool:
    return (await status(container, job)) is JobStatus.FAILED


def counting_claims(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    claims = [0]
    original = MemoryJobQueue.claim

    async def claim(self: MemoryJobQueue, **kwargs: Any) -> Job | None:
        claims[0] += 1
        return await original(self, **kwargs)

    monkeypatch.setattr(MemoryJobQueue, "claim", claim)
    return claims


async def test_a_job_due_later_runs_on_time_without_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = build_memory_container()
    claims = counting_claims(monkeypatch)
    async with running(worker(container, build_services(container))):
        await asyncio.sleep(0.1)  # the cleanup of the start is done
        job = await enqueue_removal(container, timedelta(milliseconds=300))
        await asyncio.sleep(0.2)
        assert await status(container, job) is JobStatus.QUEUED, "not before it is due"
        await until(lambda: finished(container, job), timeout=2)
        before = claims[0]
        await asyncio.sleep(0.3)
        assert claims[0] == before, "an idle worker claims nothing"
    # Two rounds of two loops, each up to two claims per service in the chain: far fewer than
    # polling every 10 ms for 600 ms would make.
    assert claims[0] < 20


async def test_an_expired_lease_is_taken_up_again() -> None:
    container = build_memory_container()
    job = await enqueue_removal(container, timedelta(0))
    async with container.unit_of_work() as uow:
        claimed = await uow.jobs.claim(now=container.clock.now(), lease=timedelta(milliseconds=300))
        await uow.commit()
    assert claimed is not None and claimed.id == job
    async with running(worker(container, build_services(container))):
        await asyncio.sleep(0.1)
        assert await status(container, job) is JobStatus.RUNNING, "held by its lease"
        await until(lambda: finished(container, job), timeout=3)
    async with container.unit_of_work() as uow:
        assert (await uow.jobs.get(job)).attempts == 2


async def test_a_due_job_nobody_claims_is_not_polled_at_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Not expected to happen; if it does, the coordinator must not spin."""
    container = build_memory_container()
    await enqueue_removal(container, timedelta(0))
    claims = counting_claims(monkeypatch)
    looks = 0
    original = MemoryJobQueue.next_due

    async def next_due(self: MemoryJobQueue, **kwargs: Any) -> Any:
        nonlocal looks
        looks += 1
        return await original(self, **kwargs)

    async def nothing(self: MemoryJobQueue, **kwargs: Any) -> None:
        claims[0] += 1
        return None

    monkeypatch.setattr(MemoryJobQueue, "next_due", next_due)
    monkeypatch.setattr(MemoryJobQueue, "claim", nothing)
    async with running(worker(container, build_services(container))):
        await asyncio.sleep(0.3)
    assert looks <= 40, "looked again after the poll interval, not at once"
    assert "due jobs were not claimed" in caplog.text


async def test_stop_while_waiting_returns_at_once() -> None:
    container = build_memory_container()
    service = worker(container, build_services(container))
    task = asyncio.create_task(service.run())
    await asyncio.sleep(0.2)  # the cleanup of the start is done; the loops wait
    service.stop()
    await asyncio.wait_for(task, timeout=0.5)


async def test_stop_before_start_returns_at_once() -> None:
    container = build_memory_container()
    service = worker(container, build_services(container))
    service.stop()
    await asyncio.wait_for(service.run(), timeout=2)
