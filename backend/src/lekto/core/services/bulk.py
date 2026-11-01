"""Changing many documents at once (`domain.bulk`): the person's selection, resolved when they
start, and a background job that works through it.

- Who: anyone, on the documents they may edit; the others are skipped with the reason. With
  `all_users` (admins only) the selection covers every user's documents.
- The selection: ids named one by one (a page or a few, at most `MAX_IDS`), or every document
  a filter finds (at most `MAX_DOCUMENTS`: more is refused), or with words every hit of the
  search (the index reaches at most `MAX_HITS`; more are not taken).
- Each document goes through the service a person uses on one (`DocumentService`,
  `PipelineService`), in a transaction of its own: rights, events, change rules and decisions
  hold as by hand. A document that is as the action wants it already counts as unchanged and
  is left alone (a change would confirm it); one being processed is skipped, except to delete
  it. An error on one document does not stop the others. After `BATCH` documents the job hands
  the worker back and continues in a new job.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from lekto.core.domain.bulk import (
    MAX_DOCUMENTS,
    MAX_IDS,
    BulkAction,
    BulkKind,
    BulkOperation,
)
from lekto.core.domain.documents import Document, DocumentChanges
from lekto.core.domain.errors import (
    AuthenticationError,
    ConcurrencyError,
    DomainError,
    NotFoundError,
    SearchUnavailableError,
    ValidationError,
)
from lekto.core.domain.identity import ViaToken
from lekto.core.domain.ids import BulkOperationId, DocumentId, UserId
from lekto.core.domain.jobs import Job
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.pipeline import Lane
from lekto.core.domain.reasons import Reason, ReasonCode, because
from lekto.core.ports.clock import Clock
from lekto.core.ports.repository import PAGE_LIMIT, DocumentFilter
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_actor
from lekto.core.services._jobs import LEASE, JobRunner, lost
from lekto.core.services.documents import DocumentService
from lekto.core.services.pipeline import PipelineService
from lekto.core.services.search import SearchService

log = logging.getLogger(__name__)

BULK_JOB = "documents.bulk"
"""Job kind of a bulk operation; payload: operation id."""
BATCH = 25
"""Documents per job; the next job continues."""


@dataclass(frozen=True)
class Selection:
    """The documents an action is for: `ids`, or (None) every document `filter` finds, with
    `text` every hit of the search; with `all_users` (admins only) any user's."""

    ids: tuple[DocumentId, ...] | None = None
    filter: DocumentFilter = field(default_factory=DocumentFilter)
    text: str | None = None
    all_users: bool = False


class BulkService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        documents: DocumentService,
        pipeline: PipelineService,
        search: SearchService | None = None,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._documents = documents
        self._pipeline = pipeline
        self._search = search
        self._jobs = JobRunner(uow, clock)

    job_kinds = (BULK_JOB,)

    async def start(
        self,
        actor: UserId,
        selection: Selection,
        action: BulkAction,
        *,
        via: ViaToken | None = None,
    ) -> BulkOperation:
        """Resolve the selection and queue the action on its documents (through the API token
        `via`, which each change carries). ValidationError for
        an empty selection, too many ids or more than `MAX_DOCUMENTS` documents of a filter;
        NotFoundError for a tag, contact, type, topic or space the action names that does not
        exist (told once here, not with every document); PermissionDeniedError for
        `all_users` without being an admin; SearchUnavailableError for words without a search
        index."""
        documents = await self._resolve(actor, selection)
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            await _check_action(uow, action)
            now = self._clock.now()
            operation = BulkOperation.create(
                user_id=user.id, action=action, documents=documents, now=now, via=via
            )
            await uow.bulk_operations.add(operation)
            await _enqueue(uow, operation.id, now)
            await uow.commit()
        return operation

    async def get(self, actor: UserId, id: BulkOperationId) -> BulkOperation:
        """For the user who started it and for admins."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            operation = await uow.bulk_operations.find(id)
        if operation is None or not (operation.user_id == actor or user.is_active_admin):
            raise NotFoundError("bulk operation", id)
        return operation

    async def _resolve(self, actor: UserId, selection: Selection) -> tuple[DocumentId, ...]:
        if selection.ids is not None:
            if len(selection.ids) > MAX_IDS:
                raise ValidationError(because(ReasonCode.BULK_TOO_MANY, max=MAX_IDS))
            return tuple(dict.fromkeys(selection.ids))
        if selection.text is not None:
            return await self._hits(actor, selection)
        total = await self._documents.count(actor, selection.filter, all_users=selection.all_users)
        if total > MAX_DOCUMENTS:
            raise ValidationError(because(ReasonCode.BULK_TOO_MANY, max=MAX_DOCUMENTS))
        found: dict[DocumentId, None] = {}
        after: DocumentId | None = None
        while True:
            page = await self._documents.query(
                actor,
                selection.filter,
                after=after,
                limit=PAGE_LIMIT,
                all_users=selection.all_users,
            )
            found.update((item.document.id, None) for item in page)
            if len(page) < PAGE_LIMIT or len(found) >= MAX_DOCUMENTS:
                return tuple(found)[:MAX_DOCUMENTS]
            after = page[-1].document.id

    async def _hits(self, actor: UserId, selection: Selection) -> tuple[DocumentId, ...]:
        """Every hit of the search, as far as the index reaches (`MAX_HITS`)."""
        if self._search is None:
            raise SearchUnavailableError("the installation has no search index")
        assert selection.text is not None
        return await self._search.hits(
            actor, selection.text, selection.filter, all_users=selection.all_users
        )

    # --- worker ----------------------------------------------------------------------------------

    async def run_next_job(self) -> bool:
        """Claim and run a due bulk job. Returns False if none was due."""
        return await self._jobs.run_next([BULK_JOB], LEASE, self._attempt)

    async def _attempt(self, job: Job) -> None:
        try:
            await self._run(job)
        except ConcurrencyError:
            lost(job)
        except Exception as error:
            log.exception("bulk operation failed", extra={"job_id": str(job.id)})
            await self._abort(job, error)

    async def _abort(self, job: Job, error: Exception) -> None:
        """An unexpected error: end the operation, so it does not run again and again."""
        try:
            async with self._uow() as uow:
                await uow.jobs.fail(
                    job, now=self._clock.now(), error=f"{type(error).__name__}: {error}"
                )
                operation = await uow.bulk_operations.find(_operation_id(job))
                if operation is not None and not operation.finished:
                    operation.finish(self._clock.now(), error="stopped by an internal error")
                    await uow.bulk_operations.update(operation)
                await uow.commit()
        except (ConcurrencyError, KeyError, ValueError):
            log.warning("could not end a failed bulk operation", extra={"job_id": str(job.id)})

    async def _run(self, job: Job) -> None:
        try:
            id = _operation_id(job)
        except (KeyError, ValueError) as error:
            await self._jobs.invalid(job, error)
            return
        for _ in range(BATCH):
            if await self._next_document(id):
                await self._jobs.end(job)
                return
        await self._jobs.end(job, also=lambda uow: _enqueue(uow, id, self._clock.now()))

    async def _next_document(self, id: BulkOperationId) -> bool:
        """Act on the next document of the operation; True if it is finished."""
        async with self._uow() as uow:
            operation = await uow.bulk_operations.find(id)
            if operation is None or operation.finished:
                return True
            if not operation.remaining:
                operation.finish(self._clock.now())
                await uow.bulk_operations.update(operation)
                await uow.commit()
                return True
        document = operation.remaining[0]
        try:
            outcome = await self._act(operation, document)
        except AuthenticationError:
            outcome = None  # the person was deactivated: the rest stops
        except ConcurrencyError:
            outcome = because(ReasonCode.SKIP_CHANGED_MEANWHILE)
        except DomainError as error:
            outcome = error.reason
        async with self._uow() as uow:
            operation = await uow.bulk_operations.get(id)
            if outcome is None:
                operation.finish(self._clock.now(), error="the user is no longer active")
            elif outcome is True:
                operation.record_changed()
            elif outcome is False:
                operation.record_unchanged()
            else:
                operation.record_skipped(document, outcome)
            await uow.bulk_operations.update(operation)
            await uow.commit()
        return outcome is None

    async def _act(self, operation: BulkOperation, id: DocumentId) -> bool | Reason:
        """Do the operation's action to the document as its person would by hand: True if it
        changed, False if it was as the action wants it already, else the reason it was
        skipped. Raises the errors of the services."""
        actor, action, via = operation.user_id, operation.action, operation.via
        try:
            view = await self._documents.view(actor, id)
        except NotFoundError:
            return because(ReasonCode.SKIP_NOT_AVAILABLE)
        document = view.document
        if not view.access.can_edit:
            return because(ReasonCode.NO_WRITE_ACCESS_TO_DOCUMENT, id=str(id))
        if document.lane is None and action.kind is not BulkKind.DELETE:
            return because(ReasonCode.BEING_PROCESSED, id=str(id))
        if _already(action, document):
            return False
        match action.kind:
            case BulkKind.MOVE:
                assert action.space is not None
                await self._documents.move(actor, id, action.space, via=via)
            case BulkKind.CONFIRM:
                await self._pipeline.confirm(actor, id, DocumentChanges(), via=via)
            case BulkKind.REPROCESS:
                assert action.node is not None
                await self._pipeline.reprocess_from(actor, id, action.node)
            case BulkKind.DELETE:
                await self._documents.delete(actor, id)
            case _:
                changes = _changes(action, document)
                await self._documents.change_metadata(actor, id, changes, via=via)
        return True


def _already(action: BulkAction, document: Document) -> bool:
    """Whether `document` is as `action` wants it (nothing to do)."""
    match action.kind:
        case BulkKind.CHANGE_TAGS:
            return (
                action.add <= frozenset(document.tag_ids) and not action.remove & document.tag_ids
            )
        case BulkKind.SET_CONTACT:
            return document.contact_id == action.contact
        case BulkKind.SET_DOCUMENT_TYPE:
            return document.document_type_id == action.document_type
        case BulkKind.SET_TOPIC:
            return document.topic_id == action.topic
        case BulkKind.MOVE:
            return document.space_id == action.space
        case BulkKind.CONFIRM:
            return document.lane is Lane.GREEN
        case _:
            return False


def _changes(action: BulkAction, document: Document) -> DocumentChanges:
    match action.kind:
        case BulkKind.CHANGE_TAGS:
            return DocumentChanges(
                tag_ids=(frozenset(document.tag_ids) | action.add) - action.remove
            )
        case BulkKind.SET_CONTACT:
            return DocumentChanges(contact_id=action.contact)
        case BulkKind.SET_DOCUMENT_TYPE:
            return DocumentChanges(document_type_id=action.document_type)
        case BulkKind.SET_TOPIC:
            return DocumentChanges(topic_id=action.topic)
        case _:
            raise AssertionError(f"no metadata change: {action.kind}")


async def _check_action(uow: UnitOfWork, action: BulkAction) -> None:
    """NotFoundError for what the action names that does not exist."""
    for tag in sorted(action.add | action.remove):
        await uow.tags.get(tag)
    if action.topic is not None:
        await uow.tags.get(action.topic)
    if action.contact is not None:
        await uow.contacts.get(action.contact)
    if action.document_type is not None:
        await uow.document_types.get(action.document_type)
    if action.space is not None:
        await uow.spaces.get(action.space)


def _operation_id(job: Job) -> BulkOperationId:
    return BulkOperationId(UUID(str(job.payload["operation_id"])))


async def _enqueue(uow: UnitOfWork, id: BulkOperationId, now: datetime) -> None:
    payload: dict[str, JsonValue] = {"operation_id": str(id)}
    await uow.jobs.enqueue(BULK_JOB, payload, run_at=now, dedup_key=f"{BULK_JOB}:{id}")
