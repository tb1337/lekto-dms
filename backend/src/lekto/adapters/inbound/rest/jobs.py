"""`/jobs`: the background jobs, for the page "System"."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from lekto.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.params import ADMINS_ONLY
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.jobs import (
    JobDurationsOut,
    JobOut,
    JobPageOut,
    JobsSummaryOut,
)
from lekto.core.domain.ids import JobId
from lekto.core.domain.jobs import OPEN_STATES, JobState
from lekto.core.services.jobs import PAGE_LIMIT

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=PROTECTED)

WHO = (
    "Every user sees the jobs; a job names a document only to those who may read it, and its "
    "error only to admins."
)


@router.get(
    "/summary",
    summary="Jobs by kind and state",
    description=(
        "How many jobs of each kind are running, due, planned, failed and done (failed and "
        "done ones within the retention period, `LEKTO_RETENTION`), and when a worker last "
        "claimed one. Cheap enough to ask every few seconds."
    ),
    response_model=JobsSummaryOut,
    responses=problem_responses(401),
)
async def summary(user: CurrentUser, context: Context) -> JobsSummaryOut:
    return JobsSummaryOut.of(await context.jobs.summary(user))


@router.get(
    "",
    summary="List jobs",
    description=(
        "The jobs in the given states (without `state`: the open ones, running, due and "
        "planned), of one kind if given: running ones first, longest running first; then due "
        "and planned ones by when they are due; then failed and done ones, latest first. " + WHO
    ),
    response_model=JobPageOut,
    responses=problem_responses(401, 422),
)
async def list_jobs(
    user: CurrentUser,
    context: Context,
    state: Annotated[list[JobState] | None, Query(description="Repeat for several.")] = None,
    kind: Annotated[str | None, Query(max_length=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=PAGE_LIMIT)] = 50,
) -> JobPageOut:
    page = await context.jobs.list(
        user,
        states=frozenset(state) if state else OPEN_STATES,
        kind=kind,
        offset=offset,
        limit=limit,
    )
    return JobPageOut.of(page, offset)


@router.get(
    "/durations",
    summary="How long jobs wait and run",
    description=(
        "For each kind, how long its jobs done within the retention period waited (from due "
        "to started) and ran (from started to done): median and 90th percentile. Jobs from "
        "before the jobs kept their times are left out."
    ),
    response_model=JobDurationsOut,
    responses=problem_responses(401),
)
async def durations(user: CurrentUser, context: Context) -> JobDurationsOut:
    return JobDurationsOut.of(await context.jobs.durations(user))


@router.post(
    "/{id}/retry",
    summary="Try a failed job again",
    description=(
        ADMINS_ONLY + " Queues the failed job again, due now, without its attempts; its last "
        "error stays until it runs. 409 if it did not fail, if the same work is queued or "
        "running already, or for a failed processing step: that one is repeated at its "
        "document (`POST /documents/{id}/retry`)."
    ),
    response_model=JobOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def retry(id: UUID, user: CurrentUser, context: Context) -> JobOut:
    return JobOut.of(await context.jobs.retry(user, JobId(id)))
