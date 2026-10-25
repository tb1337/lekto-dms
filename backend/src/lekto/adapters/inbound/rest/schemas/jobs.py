"""The background jobs: counts by kind and state, the jobs themselves, their durations."""

from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, Field

from lekto.core.domain.jobs import JobState
from lekto.core.domain.pipeline import Node
from lekto.core.services.jobs import (
    JobDurations,
    JobsPage,
    JobsSummary,
    JobView,
    KindDurations,
    KindSummary,
    RetryWay,
)

KIND = Field(
    description="What the job does, as Lekto names it internally (`pipeline.node`, "
    "`search.index`, `webhooks.deliver`, ...); new kinds may come.",
    examples=["pipeline.node"],
)


class KindSummaryOut(BaseModel):
    kind: str = KIND
    running: int = Field(description="Claimed by a worker now.")
    due: int = Field(description="Queued, their time has come: waiting for a worker.")
    planned: int = Field(description="Queued for later: a repetition or a recurring job.")
    failed: int = Field(description="Given up, within the retention period.")
    done: int = Field(description="Done, within the retention period.")

    @classmethod
    def of(cls, summary: KindSummary) -> "KindSummaryOut":
        return cls(
            kind=summary.kind,
            running=summary.running,
            due=summary.due,
            planned=summary.planned,
            failed=summary.failed,
            done=summary.done,
        )


class JobsSummaryOut(BaseModel):
    kinds: list[KindSummaryOut] = Field(description="By kind; kinds without jobs left out.")
    last_started_at: datetime | None = Field(
        description="When a worker last claimed a job; null if none did since the jobs keep "
        "their times. Long ago while jobs are due: no worker runs."
    )
    now: datetime = Field(description="The server's time the counts are of.")
    kept_since: datetime = Field(
        description="Done and failed jobs are kept from then on (the retention period); older "
        "ones are removed."
    )

    @classmethod
    def of(cls, summary: JobsSummary) -> "JobsSummaryOut":
        return cls(
            kinds=[KindSummaryOut.of(item) for item in summary.kinds],
            last_started_at=summary.last_started,
            now=summary.now,
            kept_since=summary.kept_since,
        )


class JobDocumentOut(BaseModel):
    id: UUID
    title: str


class JobOut(BaseModel):
    id: UUID
    kind: str = KIND
    state: JobState
    attempts: int = Field(
        description="Attempts that counted, the current one included; claims given back "
        "because a worker stopped are left out."
    )
    run_at: datetime = Field(description="When it is or was due.")
    started_at: datetime | None = Field(
        description="When its latest attempt began; null before the first."
    )
    finished_at: datetime | None = Field(description="When it was done or given up.")
    document: JobDocumentOut | None = Field(
        description="The document it works on, if the caller may read it."
    )
    document_hidden: bool = Field(
        description="It works on a document the caller may not read (or one deleted since)."
    )
    node: Node | None = Field(description="The processing step it runs, for `pipeline.node`.")
    contact: str | None = Field(description="The name of the contact it works on.")
    error: str | None = Field(
        description="Why its last attempt failed, as the worker wrote it (English, for "
        "admins; null for other users)."
    )
    retry: RetryWay | None = Field(
        description="For an admin and a failed job: `job` to queue it again "
        "(`POST /jobs/{id}/retry`), `document` to repeat the failed step at its document "
        "(`POST /documents/{id}/retry`); null otherwise."
    )

    @classmethod
    def of(cls, view: JobView) -> "JobOut":
        job = view.job
        return cls(
            id=job.id,
            kind=job.kind,
            state=view.state,
            attempts=job.tries,
            run_at=job.run_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            document=(
                None
                if view.document is None
                else JobDocumentOut(id=view.document.id, title=view.document.title)
            ),
            document_hidden=view.document_hidden,
            node=view.node,
            contact=view.contact,
            error=view.error,
            retry=view.retry,
        )


class JobPageOut(BaseModel):
    items: list[JobOut]
    total: int = Field(description="How many jobs match in all.")
    next_offset: int | None = Field(
        description="Pass as `offset` for the next page; null on the last page."
    )

    @classmethod
    def of(cls, page: JobsPage, offset: int) -> "JobPageOut":
        end = offset + len(page.jobs)
        return cls(
            items=[JobOut.of(view) for view in page.jobs],
            total=page.total,
            next_offset=end if page.jobs and end < page.total else None,
        )


def _ms(value: timedelta) -> float:
    return round(value.total_seconds() * 1000, 1)


class KindDurationsOut(BaseModel):
    kind: str = KIND
    count: int = Field(description="Jobs done within the retention period.")
    wait_median_ms: float = Field(description="From due to started, median.")
    wait_p90_ms: float = Field(description="From due to started, 90th percentile.")
    run_median_ms: float = Field(description="From started to done, median.")
    run_p90_ms: float = Field(description="From started to done, 90th percentile.")

    @classmethod
    def of(cls, durations: KindDurations) -> "KindDurationsOut":
        return cls(
            kind=durations.kind,
            count=durations.count,
            wait_median_ms=_ms(durations.wait_median),
            wait_p90_ms=_ms(durations.wait_p90),
            run_median_ms=_ms(durations.run_median),
            run_p90_ms=_ms(durations.run_p90),
        )


class JobDurationsOut(BaseModel):
    kinds: list[KindDurationsOut] = Field(description="By kind; kinds without done jobs left out.")
    since: datetime = Field(description="The jobs done from then on count.")

    @classmethod
    def of(cls, durations: JobDurations) -> "JobDurationsOut":
        return cls(
            kinds=[KindDurationsOut.of(item) for item in durations.kinds], since=durations.since
        )
