"""Background jobs: retryable units of work, e.g. one pipeline node for one document."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from papiq.core.domain.ids import JobId
from papiq.core.domain.json_value import JsonObject


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"  # claimed by a worker until `locked_until`
    DONE = "done"
    FAILED = "failed"  # given up

    @property
    def is_active(self) -> bool:
        return self in {JobStatus.QUEUED, JobStatus.RUNNING}


@dataclass(frozen=True, kw_only=True)
class Job:
    """A snapshot of a job as stored by the job queue.

    `dedup_key`: while a job with this key is queued or running, enqueueing another one with the
    same key does nothing.
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

    @property
    def tries(self) -> int:
        """Claims that counted: the attempts without the released ones."""
        return self.attempts - self.releases


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
