"""The worker service: runs background jobs, delivers events and keeps the cleanup scheduled.

- `concurrency` job loops run due jobs (the cleanup when due, tasks whose deadline passed, then
  search indexing, else pipeline nodes, rule applications, normalising tags after a move, logos
  of contacts, and last the classifier's check and training), each until it finds nothing.
- `webhook_concurrency` further loops deliver webhooks, apart from the job loops: a receiver that
  does not answer holds up deliveries, never the pipeline.
- The loops do not poll. For each group a coordinator asks the queue once when the next job of
  the group's kinds is due (`JobQueue.next_due`) and waits until then, or until a commit
  signals a job of those kinds (`Wakeup`), or at most `waiting.SAFETY_NET`; where signals of
  other processes do not arrive (SQLite) it polls, from `poll_interval` up to
  `waiting.IDLE_BACKOFF_MAX`. Once a job is due, every loop of the group runs until it finds
  nothing; then the coordinator looks again. So an idle worker costs the database nothing but
  the safety net, and a job starts as soon as its commit is signalled.
- One loop dispatches the outbox (`EventBus.dispatch`) the same way (`waiting.dispatch_events`).
- After an error, a loop waits longer, doubling up to `backoff.MAX_BACKOFF`, and ends its round;
  the coordinator looks again when the queue says, so a job that keeps failing is not polled.

`stop()` (on SIGTERM) ends the loops after their current job and every wait at once. Jobs still
running after `shutdown_timeout` are cancelled: each service gives its job back to run again at
once.

Each loop runs its units of work one after another, never nested, as SQLite requires.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from lekto.adapters.inbound.backoff import backoff
from lekto.adapters.inbound.waiting import (
    Idle,
    dispatch_events,
    sleep_unless_stopped,
    unless_stopped,
)
from lekto.core.ports.clock import Clock
from lekto.core.ports.event_bus import EventBus
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from lekto.core.ports.wakeup import Channel, Wakeup
from lekto.core.services.bulk import BulkService
from lekto.core.services.classifier import ClassifierService
from lekto.core.services.indexing import IndexingService
from lekto.core.services.logos import LogoService
from lekto.core.services.maintenance import MaintenanceService
from lekto.core.services.master_data import MasterDataService
from lekto.core.services.pipeline import PipelineService
from lekto.core.services.rules.retroactive import RuleApplicationService
from lekto.core.services.tasks.service import TaskService
from lekto.core.services.webhooks import WebhookDeliveryService

log = logging.getLogger(__name__)


@dataclass
class _Member:
    """One loop of a group: told to `go`, `done` once it found nothing more, and whether it
    `worked` on the way."""

    name: str
    go: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    worked: bool = False


@dataclass(frozen=True)
class _Group:
    """Loops that run the same work, woken by one coordinator."""

    name: str
    work: Callable[[], Awaitable[bool]]
    kinds: tuple[str, ...]
    members: tuple[_Member, ...]


class Worker:
    def __init__(
        self,
        *,
        pipeline: PipelineService,
        maintenance: MaintenanceService,
        event_bus: EventBus,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        wakeup: Wakeup,
        concurrency: int,
        poll_interval: timedelta,
        dispatch_interval: timedelta,
        shutdown_timeout: timedelta,
        indexing: IndexingService | None = None,
        rules: RuleApplicationService | None = None,
        bulk: BulkService | None = None,
        webhooks: WebhookDeliveryService | None = None,
        tasks: TaskService | None = None,
        webhook_concurrency: int,
        classifier: ClassifierService | None = None,
        logos: LogoService | None = None,
        master_data: MasterDataService | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._master_data = master_data
        self._logos = logos
        self._classifier = classifier
        self._rules = rules
        self._bulk = bulk
        self._maintenance = maintenance
        self._indexing = indexing
        self._webhooks = webhooks
        self._tasks = tasks
        self._webhook_concurrency = webhook_concurrency
        self._bus = event_bus
        self._uow = unit_of_work
        self._clock = clock
        self._wakeup = wakeup
        self._concurrency = concurrency
        self._poll = poll_interval
        self._dispatch_interval = dispatch_interval
        self._shutdown_timeout = shutdown_timeout
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        """Ask the worker to finish; `run` returns once it has."""
        if not self._stopping.is_set():
            log.info("worker stopping")
        self._stopping.set()

    async def run(self) -> None:
        """Run until `stop()`."""
        log.info("worker started", extra={"concurrency": self._concurrency})
        await self._maintenance.schedule()
        if self._indexing is not None:
            await self._indexing.schedule()
        if self._classifier is not None:
            await self._classifier.schedule()
        groups = [_group("jobs", self._run_job, self._job_kinds(), self._concurrency)]
        if self._webhooks is not None:
            groups.append(
                _group(
                    "webhooks", self._deliver, self._webhooks.job_kinds, self._webhook_concurrency
                )
            )
        events = self._wakeup.subscribe(Channel.EVENTS)
        loops = [
            *(asyncio.create_task(self._coordinate(group)) for group in groups),
            *(
                asyncio.create_task(self._loop(group, member))
                for group in groups
                for member in group.members
            ),
            asyncio.create_task(
                dispatch_events(self._bus, events, self._dispatch_interval, self._stopping)
            ),
        ]
        try:
            await self._stopping.wait()
        finally:
            await self._finish(loops)
        log.info("worker stopped")

    async def _finish(self, loops: Sequence[asyncio.Task[None]]) -> None:
        _, pending = await asyncio.wait(loops, timeout=self._shutdown_timeout.total_seconds())
        if pending:
            log.warning("cancelling running jobs", extra={"count": len(pending)})
            for task in pending:
                task.cancel()
            await asyncio.wait(pending)

    async def _coordinate(self, group: _Group) -> None:
        """Wake the group's loops whenever a job of its kinds is due, and wait in between."""
        signal = self._wakeup.subscribe(Channel.JOBS, kinds=group.kinds)
        idle = Idle(signal, self._poll, self._stopping)
        failures = 0
        while not self._stopping.is_set():
            try:
                due = await self._next_due(group.kinds)
            except Exception:
                failures += 1
                log.exception(
                    "looking for due jobs failed", extra={"loop": group.name, "failures": failures}
                )
                await sleep_unless_stopped(self._stopping, backoff(self._poll, failures))
                continue
            failures = 0
            due_in = None if due is None else due - self._clock.now()
            if due_in is not None and due_in <= timedelta(0):
                for member in group.members:
                    member.done.clear()
                    member.worked = False
                    member.go.set()
                await unless_stopped(
                    self._stopping,
                    asyncio.gather(*(member.done.wait() for member in group.members)),
                )
                if any(member.worked for member in group.members):
                    idle.found()
                    continue
                # Due by the queue, yet no loop took it (not expected): look again in a
                # while rather than at once.
                if not self._stopping.is_set():
                    log.warning("due jobs were not claimed", extra={"loop": group.name})
                    await sleep_unless_stopped(self._stopping, self._poll)
                continue
            await idle.wait(due_in=due_in)

    async def _next_due(self, kinds: Sequence[str]) -> datetime | None:
        async with self._uow() as uow:
            return await uow.jobs.next_due(kinds=kinds)

    async def _loop(self, group: _Group, member: _Member) -> None:
        """Once told to go, call `work` until it has nothing to do or fails; then report done."""
        failures = 0
        while not self._stopping.is_set():
            if await unless_stopped(self._stopping, member.go.wait()) is None:
                break
            member.go.clear()
            try:
                while not self._stopping.is_set():
                    try:
                        busy = await group.work()
                    except Exception:
                        failures += 1
                        log.exception(
                            "worker loop failed", extra={"loop": member.name, "failures": failures}
                        )
                        await sleep_unless_stopped(self._stopping, backoff(self._poll, failures))
                        break
                    failures = 0
                    if not busy:
                        break
                    member.worked = True
            finally:
                member.done.set()

    def _job_kinds(self) -> tuple[str, ...]:
        services = (
            self._maintenance,
            self._tasks,
            self._pipeline,
            self._indexing,
            self._rules,
            self._bulk,
            self._master_data,
            self._logos,
            self._classifier,
        )
        return tuple(
            kind for service in services if service is not None for kind in service.job_kinds
        )

    async def _run_job(self) -> bool:
        # The cleanup first: it is due once per interval and would otherwise wait for a quiet
        # moment, which a long bulk ingest never has. The pipeline before the index: people wait
        # for the processing, while the index may lag (the document lists do not read it), and
        # its jobs coalesce per document while they wait.
        return (
            await self._maintenance.run_next_job()
            or (self._tasks is not None and await self._tasks.run_next_job())
            or await self._pipeline.run_next_job()
            or (self._indexing is not None and await self._indexing.run_next_job())
            or (self._rules is not None and await self._rules.run_next_job())
            or (self._bulk is not None and await self._bulk.run_next_job())
            or (self._master_data is not None and await self._master_data.run_next_job())
            or (self._logos is not None and await self._logos.run_next_job())
            # Training waits for a quiet moment: during a bulk ingest it would be outdated soon.
            or (self._classifier is not None and await self._classifier.run_next_job())
        )

    async def _deliver(self) -> bool:
        return self._webhooks is not None and await self._webhooks.run_next_job()


def _group(
    name: str, work: Callable[[], Awaitable[bool]], kinds: Sequence[str], concurrency: int
) -> _Group:
    members = tuple(_Member(f"{name}-{n}") for n in range(1, concurrency + 1))
    return _Group(name, work, tuple(kinds), members)
