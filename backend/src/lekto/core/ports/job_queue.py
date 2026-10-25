from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from typing import Protocol

from lekto.core.domain.ids import JobId
from lekto.core.domain.jobs import FinishedJob, Job, JobOverview, JobState
from lekto.core.domain.json_value import JsonObject, JsonValue


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

    async def complete(self, job: Job, *, now: datetime, result: JsonObject | None = None) -> None:
        """The job is done (`finished_at` = `now`); `result` says what it did, if anything."""
        ...

    async def reschedule(self, job: Job, *, run_at: datetime, error: str) -> None:
        """Release the job to run again at `run_at`, e.g. after a failed attempt."""
        ...

    async def release(self, job: Job, *, run_at: datetime, error: str) -> None:
        """Give the job back unfinished, e.g. because the worker stops: it runs again at
        `run_at`. The claim still counts in `attempts`, but also in `releases`, so `Job.tries`
        leaves it out."""
        ...

    async def fail(self, job: Job, *, now: datetime, error: str) -> None:
        """Give the job up (`finished_at` = `now`); it will not run again unless `retry`."""
        ...

    async def retry(self, job: JobId, *, now: datetime) -> Job:
        """Queue a failed job again, due at `now`, as if it were new: no attempts, no claim,
        no times; its last error stays. NotFoundError if it does not exist, ConflictError if it
        did not fail or another queued or running job has its dedup key."""
        ...

    async def get(self, job: JobId) -> Job:
        """NotFoundError if the job does not exist."""
        ...

    async def overview(self, *, now: datetime) -> JobOverview:
        """How many jobs of each kind stand in each state at `now` (kinds and states without
        jobs left out), and when a worker last claimed one."""
        ...

    async def find(
        self,
        *,
        now: datetime,
        states: Collection[JobState],
        kind: str | None = None,
        offset: int = 0,
        limit: int,
    ) -> list[Job]:
        """The jobs in `states` at `now` (of `kind`): running ones first, longest running
        first; then due and planned ones by when they are due; then failed and done ones,
        latest finished first. Ties by id."""
        ...

    async def finished(
        self, *, since: datetime, kinds: Collection[str] | None = None, limit: int | None = None
    ) -> list[FinishedJob]:
        """The done jobs (of `kinds`) that finished at `since` or later, with their times, the
        earliest finished first; with `limit`, only the latest that many of them. Jobs from
        before revision 0041 have none and are left out."""
        ...

    async def purge(self, *, before: datetime) -> int:
        """Remove done and failed jobs that were due before `before`; returns how many. Queued
        and running jobs stay."""
        ...
