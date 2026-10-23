from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from typing import Protocol

from lekto.core.domain.ids import JobId
from lekto.core.domain.jobs import Job
from lekto.core.domain.json_value import JsonValue


class JobQueue(Protocol):
    """Retryable background jobs. Part of the unit of work: a job is enqueued in the same
    transaction as the state change that causes it and only exists after commit.

    Claiming is a transaction of its own: claim, commit, then do the work, then complete or
    reschedule in a new unit of work. A claimed job whose lease runs out can be claimed again.

    First adapter: job table in the database (M2).
    """

    async def enqueue(
        self,
        kind: str,
        payload: Mapping[str, JsonValue],
        *,
        run_at: datetime,
        dedup_key: str | None = None,
        coalesce_key: str | None = None,
    ) -> JobId | None:
        """Add a job, due at `run_at`. Returns None, and adds nothing, if a queued or running
        job with the same `dedup_key` exists, or a queued one with the same `coalesce_key`
        (claiming a job clears its `coalesce_key`: see `Job`). A job has at most one of the two
        keys (ValueError)."""
        ...

    async def claim(
        self, *, now: datetime, lease: timedelta, kinds: Collection[str] | None = None
    ) -> Job | None:
        """Lock the most overdue job for `lease`: a queued job with `run_at <= now`, or a running
        job whose lease has expired. Counts the attempt. None if no job is due."""
        ...

    # `extend`, `complete`, `reschedule`, `release` and `fail` take the claimed job as returned
    # by `claim`. They raise ConcurrencyError if the job is no longer running under that claim,
    # e.g. because the lease ran out and another worker claimed it: only the current claim may
    # hold or finish a job.

    async def extend(self, job: Job, *, until: datetime) -> None:
        """Hold the job until `until` instead of the end of its lease: for work that turns out
        to take longer than the lease it was claimed with."""
        ...

    async def complete(self, job: Job) -> None: ...

    async def reschedule(self, job: Job, *, run_at: datetime, error: str) -> None:
        """Release the job to run again at `run_at`, e.g. after a failed attempt."""
        ...

    async def release(self, job: Job, *, run_at: datetime, error: str) -> None:
        """Give the job back unfinished, e.g. because the worker stops: it runs again at
        `run_at`. The claim still counts in `attempts`, but also in `releases`, so `Job.tries`
        leaves it out."""
        ...

    async def fail(self, job: Job, *, error: str) -> None:
        """Give the job up; it will not run again."""
        ...

    async def get(self, job: JobId) -> Job:
        """NotFoundError if the job does not exist."""
        ...

    async def purge(self, *, before: datetime) -> int:
        """Remove done and failed jobs that were due before `before`; returns how many. Queued
        and running jobs stay."""
        ...
