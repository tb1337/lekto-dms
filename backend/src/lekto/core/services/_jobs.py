"""The frame of every service's background jobs: claim, end, repeat, give back.

A service keeps what its jobs do; `JobRunner` does the rest the same way for all. A job claimed
is given back at once when the worker stops (the interrupted claim does not count as an
attempt); a job whose claim was lost (its lease ran out and another worker took it) is logged
and changes nothing; an attempt that failed runs again when a `RetryPolicy` says.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Self
from uuid import UUID

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import ConcurrencyError
from lekto.core.domain.ids import DocumentId, JobId
from lekto.core.domain.jobs import Job, JobStatus
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.pipeline import Node
from lekto.core.ports.clock import Clock
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory

log = logging.getLogger(__name__)

LEASE = timedelta(minutes=10)
"""Lease of a job that takes seconds to minutes; one that may take longer has its own."""
STOPPED = "interrupted: the worker stopped"
"""The error a job given back when the worker stops carries."""
STORE_ATTEMPTS = 10
STORE_BACKOFF = 0.02
"""Storing a result again while a row changed meanwhile: at most `STORE_ATTEMPTS` times, waiting
up to `STORE_BACKOFF` seconds times the attempt, at random (workers finishing side by side)."""

type Step = Callable[[UnitOfWork], Awaitable[None]]
"""More to do in the commit that ends a job."""


NODE_JOB = "pipeline.node"
"""Job kind of a pipeline node; payload: `NodeJob`."""


@dataclass(frozen=True)
class NodeJob:
    """The payload of a job that runs a node of a document in a processing run."""

    document_id: DocumentId
    node: Node
    run: int

    def to_json(self) -> JsonObject:
        return document_payload(self.document_id) | {"node": self.node.value, "run": self.run}

    @classmethod
    def from_json(cls, payload: JsonObject) -> Self:
        """KeyError, TypeError or ValueError for a payload that is none."""
        run = payload["run"]
        if not isinstance(run, int):
            raise ValueError(f"invalid node job payload {payload!r}")
        return cls(payload_document(payload), Node(str(payload["node"])), run)


async def enqueue_nodes(
    uow: UnitOfWork, document: Document, nodes: Iterable[Node], now: datetime
) -> list[JobId]:
    """One job per node, due now, in the document's current run."""
    run = document.processing.run
    jobs = []
    for node in nodes:
        job = await uow.jobs.enqueue(
            NODE_JOB,
            NodeJob(document.id, node, run).to_json(),
            run_at=now,
            dedup_key=f"{document.id}:{run}:{node.value}",
        )
        if job is not None:
            jobs.append(job)
    return jobs


def document_payload(id: DocumentId) -> JsonObject:
    """The payload of a job about one document."""
    return {"document_id": str(id)}


def payload_document(payload: JsonObject) -> DocumentId:
    """The document of a `document_payload`; KeyError or ValueError for a payload that is
    none."""
    return DocumentId(UUID(str(payload["document_id"])))


class JobRunner:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def run_next(
        self, kinds: Sequence[str], lease: timedelta, handle: Callable[[Job], Awaitable[None]]
    ) -> bool:
        """Claim the most overdue job of `kinds` for `lease` and let `handle` run it; False if
        none was due. If the caller is cancelled meanwhile (the worker stops), the job is given
        back to run again at once."""
        async with self._uow() as uow:
            job = await uow.jobs.claim(now=self._clock.now(), lease=lease, kinds=list(kinds))
            await uow.commit()
        if job is None:
            return False
        try:
            await handle(job)
        except asyncio.CancelledError:
            await asyncio.shield(self.release(job))
            raise
        return True

    async def end(self, job: Job, *, error: str | None = None, also: Step | None = None) -> None:
        """Complete the job, or fail it with `error`; `also` adds to the same commit."""
        try:
            async with self._uow() as uow:
                if error is None:
                    await uow.jobs.complete(job)
                else:
                    await uow.jobs.fail(job, error=error)
                if also is not None:
                    await also(uow)
                await uow.commit()
        except ConcurrencyError:
            lost(job)

    async def invalid(self, job: Job, error: Exception) -> None:
        """Fail a job whose payload cannot be read: it would fail every time."""
        log.error(
            "invalid job", extra={"job_id": str(job.id), "kind": job.kind, "error": str(error)}
        )
        await self.end(job, error=f"invalid payload: {error}")

    async def again(
        self, job: Job, error: str, run_at: datetime | None, *, also: Step | None = None
    ) -> None:
        """Run the job again at `run_at` after a failed attempt, or (None) give it up, failed
        with `error`; `also` adds to the same commit."""
        if run_at is None:
            log.error(
                "job given up", extra={"job_id": str(job.id), "kind": job.kind, "error": error}
            )
        try:
            async with self._uow() as uow:
                if run_at is None:
                    await uow.jobs.fail(job, error=error)
                else:
                    await uow.jobs.reschedule(job, run_at=run_at, error=error)
                if also is not None:
                    await also(uow)
                await uow.commit()
        except ConcurrencyError:
            lost(job)

    async def release(self, job: Job) -> None:
        """Give an interrupted job back to run again at once. Nothing to do if it was ended or
        lost its claim meanwhile."""
        try:
            async with self._uow() as uow:
                await uow.jobs.release(job, run_at=self._clock.now(), error=STOPPED)
                await uow.commit()
        except ConcurrencyError:
            pass
        except Exception:
            log.warning(
                "could not release an interrupted job", extra={"job_id": str(job.id)}, exc_info=True
            )

    async def still_claimed(self, job: Job) -> bool:
        async with self._uow() as uow:
            current = await uow.jobs.get(job.id)
        return current.status is JobStatus.RUNNING and current.attempts == job.attempts

    async def storing(self, job: Job, store: Callable[[], Awaitable[None]]) -> None:
        """Store what a job did with `store`, again while a row changed meanwhile, unless the
        job's claim was lost: then another worker owns the job and nothing is stored."""
        for attempt in range(1, STORE_ATTEMPTS + 1):
            try:
                await store()
                return
            except ConcurrencyError:
                if not await self.still_claimed(job):
                    lost(job)
                    return
                if attempt == STORE_ATTEMPTS:
                    raise
                await _backoff(attempt)


def lost(job: Job) -> None:
    log.warning("lost the claim of a job", extra={"job_id": str(job.id), "kind": job.kind})


async def retrying[T](
    step: Callable[[], Awaitable[T]], *, attempts: int, backoff: bool = False
) -> T:
    """`step` again while a row changed meanwhile (ConcurrencyError), at most `attempts`
    times; then the error goes on. `backoff`: wait a little before the next time."""
    for attempt in range(1, attempts + 1):
        try:
            return await step()
        except ConcurrencyError:
            if attempt == attempts:
                raise
            log.info("a row changed meanwhile; trying again", extra={"attempt": attempt})
            if backoff:
                await _backoff(attempt)
    raise AssertionError("unreachable")


async def _backoff(attempt: int) -> None:
    await asyncio.sleep(random.uniform(0, STORE_BACKOFF * attempt))
