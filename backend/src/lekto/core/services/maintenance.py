"""Housekeeping as jobs.

- The recurring cleanup removes finished jobs, delivered events, ended sessions, stale counts
  of failed sign-ins, old webhook deliveries, the previous secrets of webhooks whose grace
  period is over, and what only the inbox's done needs once it is older than `DONE_PERIOD`.
- `documents.remove_files`, queued with the deletion of a document, removes its derivatives
  and its original, unless another document (of any owner) has the same file. Deleting the
  original and storing it for a new upload lock the original's key (`UnitOfWork.lock`), so an
  upload of the same file at that moment never ends up without its original.

The cleanup is a job in the job queue under a fixed dedup key, so with several workers only one
of them runs it at a time. After each run it schedules the next one, in the same transaction
that completes the current run.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from lekto.core.domain.documents import Sha256
from lekto.core.domain.errors import ConcurrencyError, ValidationError
from lekto.core.domain.identity import ACCOUNT_THROTTLE, SOURCE_THROTTLE
from lekto.core.domain.ids import DocumentId
from lekto.core.domain.inbox import DONE_PERIOD
from lekto.core.domain.jobs import Job, RetryPolicy
from lekto.core.domain.json_value import JsonObject, as_int
from lekto.core.ports.clock import Clock
from lekto.core.ports.event_bus import EventBus
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._jobs import LEASE, JobRunner, document_payload, lost, payload_document
from lekto.core.services.objects import derivative_keys, original_key

log = logging.getLogger(__name__)

CLEANUP_JOB = "maintenance.cleanup"
REMOVE_FILES_JOB = "documents.remove_files"
"""Payload: `RemoveFiles`."""


@dataclass(frozen=True)
class RemoveFiles:
    """The payload of a `REMOVE_FILES_JOB`: the files of a deleted document."""

    document_id: DocumentId
    sha256: Sha256
    page_count: int | None

    def to_json(self) -> JsonObject:
        return document_payload(self.document_id) | {
            "sha256": self.sha256.hex,
            "page_count": self.page_count,
        }

    @classmethod
    def from_json(cls, payload: JsonObject) -> "RemoveFiles":
        """KeyError, ValueError or ValidationError for a payload that is none."""
        pages = payload.get("page_count")
        if pages is not None and as_int(pages) is None:
            raise ValueError(f"page_count {pages!r}")
        return cls(payload_document(payload), Sha256(str(payload["sha256"])), as_int(pages))


# Removing the files of a deleted document: five attempts, waiting a minute, doubling.
_REMOVE_RETRY = RetryPolicy(max_attempts=5, delay=timedelta(minutes=1))

# Failed sign-ins older than this count no more (see the throttle windows).
_FAILURE_RETENTION = max(ACCOUNT_THROTTLE.window, SOURCE_THROTTLE.window)


class MaintenanceService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        event_bus: EventBus,
        *,
        interval: timedelta,
        retention: timedelta,
        session_idle: timedelta,
        object_store: ObjectStore | None = None,
    ) -> None:
        """Every `interval`, remove finished jobs and delivered events older than
        `retention`, sessions that expired or were idle for `session_idle`, and counts of
        failed sign-ins that no longer matter."""
        self._uow = uow
        self._clock = clock
        self._bus = event_bus
        self._interval = interval
        self._retention = retention
        self._session_idle = session_idle
        self._store = object_store
        self._jobs = JobRunner(uow, clock)

    @property
    def interval(self) -> timedelta:
        """The time between two cleanups."""
        return self._interval

    @property
    def retention(self) -> timedelta:
        """How long finished jobs and delivered events are kept."""
        return self._retention

    async def schedule(self) -> None:
        """Make sure a cleanup is queued; due at once unless one is queued already."""
        async with self._uow() as uow:
            await uow.jobs.enqueue(CLEANUP_JOB, {}, run_at=self._clock.now(), dedup_key=CLEANUP_JOB)
            await uow.commit()

    async def run_next_job(self) -> bool:
        """Run a due housekeeping job. Returns False if none was due."""
        return await self._jobs.run_next([CLEANUP_JOB, REMOVE_FILES_JOB], LEASE, self._run)

    async def _run(self, job: Job) -> None:
        if job.kind == REMOVE_FILES_JOB:
            await self._remove_files(job)
        else:
            await self._cleanup(job)

    async def _remove_files(self, job: Job) -> None:
        try:
            files = RemoveFiles.from_json(job.payload)
        except (KeyError, ValueError, ValidationError) as error:
            await self._jobs.invalid(job, error)
            return
        assert self._store is not None, "removing files needs the object store"
        document, sha256, pages = files.document_id, files.sha256, files.page_count
        original = original_key(sha256)
        try:
            for key in derivative_keys(document, pages):
                await self._store.delete(key)
            async with self._uow() as uow:
                await uow.lock(original)
                shared = await uow.documents.exists(sha256=sha256)
                if not shared:
                    await self._store.delete(original)
                await uow.jobs.complete(job, now=self._clock.now())
                await uow.commit()
        except ConcurrencyError:
            lost(job)
            return
        except Exception as error:
            log.warning(
                "removing files failed", extra={"document_id": str(document)}, exc_info=True
            )
            run_at = _REMOVE_RETRY.next_run(job.tries, self._clock.now())
            await self._jobs.again(job, repr(error), run_at)
            return
        log.info(
            "files of a deleted document removed",
            extra={"document_id": str(document), "original_removed": not shared},
        )

    async def _cleanup(self, job: Job) -> None:
        now = self._clock.now()
        before = now - self._retention
        next_run = now + self._interval
        try:
            events = await self._bus.purge(before=before)
            async with self._uow() as uow:
                jobs = await uow.jobs.purge(before=before)
                sessions = await uow.sessions.purge(now=now, idle_before=now - self._session_idle)
                failures = await uow.login_failures.purge(before=now - _FAILURE_RETENTION)
                deliveries = await uow.webhooks.purge_deliveries(before=before)
                secrets = await _drop_expired_secrets(uow, now)
                inbox = await uow.inbox.purge(before=now - DONE_PERIOD)
                await uow.jobs.complete(job, now=now)
                await uow.jobs.enqueue(CLEANUP_JOB, {}, run_at=next_run, dedup_key=CLEANUP_JOB)
                await uow.commit()
        except ConcurrencyError:
            lost(job)
            return
        except Exception as error:
            log.exception("cleanup failed")
            await self._jobs.again(job, repr(error), next_run)
            return
        log.info(
            "cleanup done",
            extra={
                "jobs_removed": jobs,
                "events_removed": events,
                "sessions_removed": sessions,
                "login_failures_removed": failures,
                "webhook_deliveries_removed": deliveries,
                "webhook_secrets_dropped": secrets,
                "inbox_marks_removed": inbox,
            },
        )


async def _drop_expired_secrets(uow: UnitOfWork, now: datetime) -> int:
    """A renewed webhook secret's predecessor signs until the grace period ends; after that it
    is removed from the database (webhooks are few, so they are simply read)."""
    dropped = 0
    for webhook in await uow.webhooks.list_all():
        if webhook.drop_expired_secret(now):
            webhook.updated_at = now
            await uow.webhooks.update(webhook)
            dropped += 1
    return dropped
