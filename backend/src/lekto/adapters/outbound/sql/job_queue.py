"""Job queue on the `jobs` table.

Claiming is one statement: `UPDATE jobs ... WHERE id = (SELECT the most overdue due job)`.
On Postgres the subquery locks the row with `FOR UPDATE SKIP LOCKED`, so concurrent workers
take different jobs without waiting. On SQLite the statement runs under the write lock taken by
`BEGIN IMMEDIATE`, so a second worker waits until the first commits and then sees the job taken.

Finishing a job checks the claim in the same statement (`status = 'running'` and the attempt
count of the claim): only the current claim can complete, reschedule or fail it.

Deduplication uses a unique index on `dedup_key` over queued and running jobs only;
`INSERT ... ON CONFLICT DO NOTHING` adds nothing while such a job exists. The index predicate
in ON CONFLICT is literal SQL (see `_ACTIVE`).

The overview counts by kind and state in one `GROUP BY`; the state of a queued job (due or
planned) is a `CASE` on `run_at`. The list orders by the state, then by the time that matters
for it (`_ORDER`).
"""

from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Row,
    and_,
    case,
    delete,
    func,
    insert,
    or_,
    select,
    text,
    update,
)

from lekto.adapters.outbound.sql import tables as t
from lekto.adapters.outbound.sql.transaction import Transaction
from lekto.core.domain.errors import ConcurrencyError, ConflictError, NotFoundError
from lekto.core.domain.ids import JobId, new_id
from lekto.core.domain.jobs import FinishedJob, Job, JobCount, JobOverview, JobState, JobStatus
from lekto.core.domain.json_value import JsonObject, JsonValue
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.validation import require_utc

_jobs = t.jobs

# The predicate of the partial dedup index, as literal SQL: Postgres matches the index of
# ON CONFLICT against it, which fails for bind parameters once a prepared statement is
# planned generically (from its sixth run on).
_ACTIVE = text("status IN (" + ", ".join(f"'{status}'" for status in t.ACTIVE_JOB_STATUSES) + ")")


class SqlJobQueue:
    def __init__(self, transaction: Transaction) -> None:
        self._tx = transaction

    async def enqueue(
        self,
        kind: str,
        payload: Mapping[str, JsonValue],
        *,
        run_at: datetime,
        dedup_key: str | None = None,
        coalesce_key: str | None = None,
    ) -> JobId | None:
        id = JobId(new_id())
        values = {
            "id": id,
            "kind": kind,
            "payload": dict(payload),
            "dedup_key": dedup_key,
            "coalesce_key": coalesce_key,
            "status": JobStatus.QUEUED.value,
            "attempts": 0,
            "releases": 0,
            "run_at": require_utc(run_at, "run_at"),
        }
        if dedup_key is None and coalesce_key is None:
            await self._tx.write(insert(_jobs).values(values))
            return id
        if dedup_key is not None and coalesce_key is not None:
            raise ValueError("a job has a dedup key or a coalesce key, not both")
        statement = self._tx.database.insert(_jobs).values(values)
        if dedup_key is not None:
            statement = statement.on_conflict_do_nothing(
                index_elements=[_jobs.c.dedup_key], index_where=_ACTIVE
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=[_jobs.c.coalesce_key])
        result = await self._tx.write(statement.returning(_jobs.c.id))
        return id if result.first() is not None else None

    async def claim(
        self, *, now: datetime, lease: timedelta, kinds: Collection[str] | None = None
    ) -> Job | None:
        due = or_(
            and_(_jobs.c.status == JobStatus.QUEUED.value, _jobs.c.run_at <= now),
            and_(_jobs.c.status == JobStatus.RUNNING.value, _jobs.c.locked_until <= now),
        )
        if kinds is not None:
            due = and_(due, _jobs.c.kind.in_(list(kinds)))
        candidate = (
            select(_jobs.c.id)
            .where(due)
            .order_by(_jobs.c.run_at, _jobs.c.id)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        result = await self._tx.write(
            update(_jobs)
            .where(_jobs.c.id == candidate)
            .values(
                status=JobStatus.RUNNING.value,
                attempts=_jobs.c.attempts + 1,
                locked_until=require_utc(now, "now") + lease,
                coalesce_key=None,
                started_at=now,
            )
            .returning(*_jobs.c)
        )
        row = result.first()
        return None if row is None else _job(row)

    async def extend(self, job: Job, *, until: datetime) -> None:
        await self._held(job, locked_until=require_utc(until, "until"))

    async def complete(self, job: Job, *, now: datetime, result: JsonObject | None = None) -> None:
        await self._finish(
            job,
            status=JobStatus.DONE,
            finished_at=require_utc(now, "now"),
            result=None if result is None else dict(result),
        )

    async def reschedule(self, job: Job, *, run_at: datetime, error: str) -> None:
        await self._finish(
            job, status=JobStatus.QUEUED, run_at=require_utc(run_at, "run_at"), last_error=error
        )

    async def release(self, job: Job, *, run_at: datetime, error: str) -> None:
        await self._finish(
            job,
            status=JobStatus.QUEUED,
            run_at=require_utc(run_at, "run_at"),
            last_error=error,
            releases=_jobs.c.releases + 1,
        )

    async def fail(self, job: Job, *, now: datetime, error: str) -> None:
        await self._finish(
            job, status=JobStatus.FAILED, finished_at=require_utc(now, "now"), last_error=error
        )

    async def retry(self, job: JobId, *, now: datetime) -> Job:
        current = await self.get(job)
        if current.status is not JobStatus.FAILED:
            raise ConflictError(because(ReasonCode.JOB_NOT_FAILED))
        if current.dedup_key is not None:
            taken = await self._tx.read(
                select(_jobs.c.id).where(
                    _jobs.c.dedup_key == current.dedup_key,
                    _jobs.c.status.in_(t.ACTIVE_JOB_STATUSES),
                )
            )
            if taken.first() is not None:
                raise ConflictError(because(ReasonCode.JOB_ALREADY_QUEUED))
        result = await self._tx.write(
            update(_jobs)
            .where(_jobs.c.id == job, _jobs.c.status == JobStatus.FAILED.value)
            .values(
                status=JobStatus.QUEUED.value,
                run_at=require_utc(now, "now"),
                attempts=0,
                releases=0,
                locked_until=None,
                started_at=None,
                finished_at=None,
                result=None,
            )
            .returning(*_jobs.c)
        )
        row = result.first()
        if row is None:  # retried or removed meanwhile
            raise ConflictError(because(ReasonCode.JOB_NOT_FAILED))
        return _job(row)

    async def get(self, job: JobId) -> Job:
        row = (await self._tx.read(select(_jobs).where(_jobs.c.id == job))).first()
        if row is None:
            raise NotFoundError("job", job)
        return _job(row)

    async def overview(self, *, now: datetime) -> JobOverview:
        # A subquery: Postgres would see two different expressions in the select list and in
        # GROUP BY, each with its own parameter for `now`.
        states = select(_jobs.c.kind, _state(require_utc(now, "now")).label("state")).subquery()
        counts = await self._tx.read(
            select(states.c.kind, states.c.state, func.count().label("jobs"))
            .group_by(states.c.kind, states.c.state)
            .order_by(states.c.kind, states.c.state)
        )
        last = await self._tx.read(select(func.max(_jobs.c.started_at)))
        return JobOverview(
            counts=tuple(JobCount(row.kind, JobState(row.state), row.jobs) for row in counts),
            last_started=last.scalar(),
        )

    async def find(
        self,
        *,
        now: datetime,
        states: Collection[JobState],
        kind: str | None = None,
        offset: int = 0,
        limit: int,
    ) -> list[Job]:
        state = _state(require_utc(now, "now"))
        query = select(_jobs).where(state.in_([item.value for item in states]))
        if kind is not None:
            query = query.where(_jobs.c.kind == kind)
        rows = await self._tx.read(query.order_by(*_order(state)).offset(offset).limit(limit))
        return [_job(row) for row in rows]

    async def finished(
        self, *, since: datetime, kinds: Collection[str] | None = None
    ) -> list[FinishedJob]:
        query = select(
            _jobs.c.kind, _jobs.c.run_at, _jobs.c.started_at, _jobs.c.finished_at, _jobs.c.result
        ).where(
            _jobs.c.status == JobStatus.DONE.value,
            _jobs.c.finished_at >= require_utc(since, "since"),
            _jobs.c.started_at.is_not(None),
        )
        if kinds is not None:
            query = query.where(_jobs.c.kind.in_(list(kinds)))
        rows = await self._tx.read(query.order_by(_jobs.c.finished_at, _jobs.c.id))
        return [
            FinishedJob(
                kind=row.kind,
                run_at=row.run_at,
                started_at=row.started_at,
                finished_at=row.finished_at,
                result=row.result,
            )
            for row in rows
        ]

    async def purge(self, *, before: datetime) -> int:
        result = await self._tx.write(
            delete(_jobs).where(
                _jobs.c.status.in_([JobStatus.DONE.value, JobStatus.FAILED.value]),
                _jobs.c.run_at < require_utc(before, "before"),
            )
        )
        return int(result.rowcount)

    async def _finish(self, job: Job, *, status: JobStatus, **values: Any) -> None:
        await self._held(job, status=status.value, locked_until=None, **values)

    async def _held(self, job: Job, **values: Any) -> None:
        """Change the job while it runs under the claim `job`."""
        result = await self._tx.write(
            update(_jobs)
            .where(
                _jobs.c.id == job.id,
                _jobs.c.status == JobStatus.RUNNING.value,
                _jobs.c.attempts == job.attempts,
            )
            .values(**values)
        )
        if result.rowcount == 0:
            await self.get(job.id)  # NotFoundError if it does not exist
            raise ConcurrencyError(f"job {job.id} is no longer held by this claim")


def _state(now: datetime) -> ColumnElement[str]:
    """The `JobState` of a row at `now`."""
    return case(
        (
            _jobs.c.status == JobStatus.QUEUED.value,
            case((_jobs.c.run_at <= now, JobState.DUE.value), else_=JobState.PLANNED.value),
        ),
        else_=_jobs.c.status,
    )


def _order(state: ColumnElement[str]) -> list[ColumnElement[Any]]:
    """Running, due, planned, failed and done jobs in this order; within each, by the time that
    matters (`JobQueue.find`)."""
    rank = case(
        {
            JobState.RUNNING.value: 0,
            JobState.DUE.value: 1,
            JobState.PLANNED.value: 2,
            JobState.FAILED.value: 3,
            JobState.DONE.value: 4,
        },
        value=state,
    )
    running = case((_jobs.c.status == JobStatus.RUNNING.value, _jobs.c.started_at))
    queued = case((_jobs.c.status == JobStatus.QUEUED.value, _jobs.c.run_at))
    finished = case((_jobs.c.status.in_(_FINISHED), _jobs.c.finished_at))
    return [
        rank,
        running.asc().nulls_last(),
        queued.asc(),
        finished.desc().nulls_last(),
        _jobs.c.id,
    ]


_FINISHED = [JobStatus.DONE.value, JobStatus.FAILED.value]


def _job(row: Row[Any]) -> Job:
    return Job(
        id=JobId(row.id),
        kind=row.kind,
        payload=row.payload,
        dedup_key=row.dedup_key,
        status=JobStatus(row.status),
        attempts=row.attempts,
        run_at=row.run_at,
        locked_until=row.locked_until,
        last_error=row.last_error,
        releases=row.releases,
        coalesce_key=row.coalesce_key,
        started_at=row.started_at,
        finished_at=row.finished_at,
        result=row.result,
    )
