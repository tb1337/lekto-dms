"""The background jobs on the page "System": how many of each kind stand in each state, the jobs
themselves, how long the jobs done lately waited and ran, and a failed job queued again.

Every user sees them; what a job names is shown as far as they may see it: a document only if
they may read it ("a document" otherwise, counted but not named), a job's last error only to
admins (it may hold file names or text). Only admins queue a failed job again; a failed
processing step is tried again at its document (`PipelineService.retry`), whose processing
goes on from there.
"""

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import ConflictError
from lekto.core.domain.ids import ContactId, DocumentId, JobId, SpaceId, UserId
from lekto.core.domain.jobs import FinishedJob, Job, JobState
from lekto.core.domain.permissions import can_read_document
from lekto.core.domain.pipeline import Node
from lekto.core.domain.reasons import Action, ReasonCode, because
from lekto.core.domain.spaces import Space
from lekto.core.domain.statistics import median, percentile
from lekto.core.domain.users import User
from lekto.core.ports.clock import Clock
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_actor, require_admin
from lekto.core.services._kept import Kept
from lekto.core.services.pipeline import NODE_JOB

PAGE_LIMIT = 100
SAMPLE = 2000
"""The done jobs of a kind the durations are read from: the latest ones. A migration leaves
more than a million done jobs within the retention; reading them all for every open page
took seconds and the memory of a worker."""


class RetryWay(StrEnum):
    """How an admin tries a failed job again: the job itself, or (a processing step) its
    document."""

    JOB = "job"
    DOCUMENT = "document"


@dataclass(frozen=True)
class KindSummary:
    """The jobs of a kind by state."""

    kind: str
    running: int = 0
    due: int = 0
    planned: int = 0
    failed: int = 0
    done: int = 0

    def count(self, states: Collection[JobState]) -> int:
        return sum(getattr(self, state.value) for state in states)


@dataclass(frozen=True)
class JobsSummary:
    """The jobs by kind (kinds without jobs left out), when a worker last claimed one, the time
    the counts are of, and since when done and failed jobs are kept (the retention period)."""

    kinds: tuple[KindSummary, ...]
    last_started: datetime | None
    now: datetime
    kept_since: datetime


@dataclass(frozen=True)
class DocumentRef:
    id: DocumentId
    title: str


@dataclass(frozen=True)
class JobView:
    """A job as its viewer may see it: `document` if it names one they may read,
    `document_hidden` if it names one they may not (or one that is gone); `error` for admins
    only; `retry` how an admin tries it again, for a failed job."""

    job: Job
    state: JobState
    document: DocumentRef | None = None
    document_hidden: bool = False
    node: Node | None = None
    contact: str | None = None
    error: str | None = None
    retry: RetryWay | None = None


@dataclass(frozen=True)
class JobsPage:
    jobs: tuple[JobView, ...]
    total: int


@dataclass(frozen=True)
class KindDurations:
    """How long the done jobs of a kind waited (from due to started) and ran (from started to
    done), as median and 90th percentile."""

    kind: str
    count: int
    wait_median: timedelta
    wait_p90: timedelta
    run_median: timedelta
    run_p90: timedelta


@dataclass(frozen=True)
class JobDurations:
    kinds: tuple[KindDurations, ...]
    since: datetime


def durations_of(kind: str, jobs: Collection[FinishedJob]) -> KindDurations | None:
    """The durations of `jobs` (all of `kind`); None without any."""
    waits = [max(timedelta(0), job.started_at - job.run_at) for job in jobs]
    runs = [max(timedelta(0), job.finished_at - job.started_at) for job in jobs]
    wait_median, wait_p90 = median(waits), percentile(waits, 0.9)
    run_median, run_p90 = median(runs), percentile(runs, 0.9)
    if wait_median is None or wait_p90 is None or run_median is None or run_p90 is None:
        return None
    return KindDurations(kind, len(runs), wait_median, wait_p90, run_median, run_p90)


class JobsService:
    def __init__(
        self, uow: UnitOfWorkFactory, clock: Clock, *, retention: timedelta, sample: int = SAMPLE
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._retention = retention
        self._sample = sample
        self._kept = Kept(clock)

    async def summary(self, actor: UserId) -> JobsSummary:
        now = self._clock.now()
        async with self._uow() as uow:
            await load_actor(uow, actor)
            overview = await uow.jobs.overview(now=now)
        counts: dict[str, dict[str, int]] = defaultdict(dict)
        for item in overview.counts:
            counts[item.kind][item.state.value] = item.count
        kinds = tuple(KindSummary(kind, **states) for kind, states in sorted(counts.items()))
        return JobsSummary(kinds, overview.last_started, now, now - self._retention)

    async def list(
        self,
        actor: UserId,
        *,
        states: Collection[JobState],
        kind: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> JobsPage:
        """The jobs in `states` (of `kind`) in the order of `JobQueue.find`, and how many there
        are in all."""
        now = self._clock.now()
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            overview = await uow.jobs.overview(now=now)
            jobs = await uow.jobs.find(
                now=now, states=states, kind=kind, offset=offset, limit=min(limit, PAGE_LIMIT)
            )
            views = await _Viewer(uow, user).views(jobs, now)
        total = sum(
            item.count
            for item in overview.counts
            if item.state in states and (kind is None or item.kind == kind)
        )
        return JobsPage(tuple(views), total)

    async def durations(self, actor: UserId) -> JobDurations:
        """How long the jobs done within the retention period waited and ran, by kind: from
        the latest `sample` done jobs of each kind, counted at most once a minute."""
        async with self._uow() as uow:
            await load_actor(uow, actor)

        async def count() -> JobDurations:
            now = self._clock.now()
            since = now - self._retention
            async with self._uow() as uow:
                overview = await uow.jobs.overview(now=now)
                kinds = sorted(
                    {item.kind for item in overview.counts if item.state is JobState.DONE}
                )
                found = [
                    durations_of(
                        kind,
                        await uow.jobs.finished(since=since, kinds=[kind], limit=self._sample),
                    )
                    for kind in kinds
                ]
            return JobDurations(tuple(item for item in found if item is not None), since)

        return await self._kept.get("durations", count)

    async def retry(self, actor: UserId, id: JobId) -> JobView:
        """Admins only: queue the failed job again (`JobQueue.retry`). A failed processing step
        is tried again at its document instead (ConflictError)."""
        now = self._clock.now()
        async with self._uow() as uow:
            user = await require_admin(uow, actor, Action.RETRY_JOBS)
            job = await uow.jobs.get(id)
            if job.kind == NODE_JOB:
                raise ConflictError(because(ReasonCode.JOB_RETRY_IN_DOCUMENT))
            retried = await uow.jobs.retry(id, now=now)
            await uow.commit()
            [view] = await _Viewer(uow, user).views([retried], now)
        return view


class _Viewer:
    """What `user` may see of jobs, with the documents, spaces and contacts read once each."""

    def __init__(self, uow: UnitOfWork, user: User) -> None:
        self._uow = uow
        self._user = user
        self._documents: dict[DocumentId, Document | None] = {}
        self._spaces: dict[SpaceId, Space] = {}
        self._contacts: dict[ContactId, str | None] = {}

    async def views(self, jobs: Collection[Job], now: datetime) -> list[JobView]:
        return [await self._view(job, now) for job in jobs]

    async def _view(self, job: Job, now: datetime) -> JobView:
        state = job.state(now)
        admin = self._user.is_active_admin
        document, hidden = None, False
        if (document_id := _uuid(job.payload.get("document_id"))) is not None:
            document = await self._readable(DocumentId(document_id))
            hidden = document is None
        contact = None
        if (contact_id := _uuid(job.payload.get("contact_id"))) is not None:
            contact = await self._contact(ContactId(contact_id))
        retry = None
        if admin and state is JobState.FAILED:
            retry = RetryWay.DOCUMENT if job.kind == NODE_JOB else RetryWay.JOB
            if retry is RetryWay.DOCUMENT and document is None:
                retry = None
        return JobView(
            job=job,
            state=state,
            document=document,
            document_hidden=hidden,
            node=_node(job.payload.get("node")),
            contact=contact,
            error=job.last_error if admin else None,
            retry=retry,
        )

    async def _readable(self, id: DocumentId) -> DocumentRef | None:
        if id not in self._documents:
            self._documents[id] = await self._uow.documents.find(id)
        document = self._documents[id]
        if document is None:
            return None
        if document.space_id not in self._spaces:
            self._spaces[document.space_id] = await self._uow.spaces.get(document.space_id)
        if not can_read_document(self._user, document, self._spaces[document.space_id]):
            return None
        return DocumentRef(document.id, document.title)

    async def _contact(self, id: ContactId) -> str | None:
        if id not in self._contacts:
            contact = await self._uow.contacts.find(id)
            self._contacts[id] = None if contact is None else contact.name
        return self._contacts[id]


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _node(value: object) -> Node | None:
    try:
        return Node(str(value)) if isinstance(value, str) else None
    except ValueError:
        return None
