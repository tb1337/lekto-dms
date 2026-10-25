"""Background jobs: retryable units of work, e.g. one pipeline node for one document."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from lekto.core.domain.ids import JobId
from lekto.core.domain.json_value import JsonObject


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"  # claimed by a worker until `locked_until`
    DONE = "done"
    FAILED = "failed"  # given up

    @property
    def is_active(self) -> bool:
        return self in {JobStatus.QUEUED, JobStatus.RUNNING}


class JobState(StrEnum):
    """Where a job stands for the people looking at it: a queued job is due once its time has
    come, planned before (a repetition, a recurring job)."""

    RUNNING = "running"
    DUE = "due"
    PLANNED = "planned"
    DONE = "done"
    FAILED = "failed"

    @property
    def is_open(self) -> bool:
        return self in OPEN_STATES


OPEN_STATES = frozenset({JobState.RUNNING, JobState.DUE, JobState.PLANNED})


@dataclass(frozen=True, kw_only=True)
class Job:
    """A snapshot of a job as stored by the job queue.

    `dedup_key`: while a job with this key is queued or running, enqueueing another one with the
    same key does nothing.
    `coalesce_key`: while a job with this key is queued, enqueueing another one with the same key
    does nothing; claiming the job clears it, so a change that comes after its work has begun
    queues a new job. For work that reads the current state when it runs (the search index).
    `started_at`: when the latest claim took it; `finished_at`: when it was done or given up;
    `result`: what a done job reports of its work (the search index: how many sections it
    embedded). None in jobs from before revision 0041.
    """

    id: JobId
    kind: str
    payload: JsonObject
    dedup_key: str | None
    status: JobStatus
    attempts: int  # claims so far, including the current one
    run_at: datetime
    locked_until: datetime | None = None
    last_error: str | None = None
    releases: int = 0  # claims given back unfinished (`JobQueue.release`)
    coalesce_key: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: JsonObject | None = None

    @property
    def tries(self) -> int:
        """Claims that counted: the attempts without the released ones."""
        return self.attempts - self.releases

    def state(self, now: datetime) -> JobState:
        match self.status:
            case JobStatus.RUNNING:
                return JobState.RUNNING
            case JobStatus.QUEUED:
                return JobState.DUE if self.run_at <= now else JobState.PLANNED
            case JobStatus.DONE:
                return JobState.DONE
            case JobStatus.FAILED:
                return JobState.FAILED


@dataclass(frozen=True)
class JobCount:
    """How many jobs of a kind stand in a state."""

    kind: str
    state: JobState
    count: int


@dataclass(frozen=True)
class JobOverview:
    """The jobs by kind and state, and when a worker last claimed one (None: never, or only
    before revision 0041)."""

    counts: tuple[JobCount, ...]
    last_started: datetime | None


@dataclass(frozen=True, kw_only=True)
class FinishedJob:
    """A done job's times and result, for its durations: due at `run_at`, started at
    `started_at` (by its last claim), done at `finished_at`."""

    kind: str
    run_at: datetime
    started_at: datetime
    finished_at: datetime
    result: JsonObject | None = None


WORK_LEASE_MARGIN = timedelta(minutes=2)
"""Time a node or indexing job may take beyond the time limits of what it calls (OCR, a model,
the search index): downloading and uploading its files, the preview, the bookkeeping in the
database."""


@dataclass(frozen=True, kw_only=True)
class RetryPolicy:
    """Repeating work whose attempt failed (a job, an event's delivery): at most
    `max_attempts` attempts in total; before attempt n+1 it waits `delay * 2^(n-1)`, at most
    `max_delay` if one is given."""

    max_attempts: int
    delay: timedelta
    max_delay: timedelta | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

    def next_run(self, attempts: int, now: datetime) -> datetime | None:
        """When to try again after `attempts` attempts; None to give up."""
        if attempts >= self.max_attempts:
            return None
        wait = self.delay * (1 << min(max(attempts - 1, 0), 40))
        return now + (wait if self.max_delay is None else min(wait, self.max_delay))
