"""Applying a rule to existing documents, on request: a preview, then a background job.

- Who, on what: a user rule by its owner or an admin, on the documents of the rule's owner; a
  global rule by anyone, on the documents they may write to (an admin: every document, Tobi,
  08.10.2026). Documents the caller may not write to appear neither one by one nor as a count;
  documents in processing are left out.
- The preview evaluates the rule's current version on each document (its state, not a change)
  and lists the documents it would change, with conflicts: a field that has another value.
- The application pins one version. A background job works through the selected documents, one
  transaction each, checks the rights again, takes the rule's value where the person accepted
  the conflict, skips other conflicts, and logs every document. A forced review does not act
  (it would change who sees a document). After `BATCH` documents the job hands the worker back
  and continues in a new job, so processing and indexing do not wait.
"""

import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from papiq.core.domain.documents import Document
from papiq.core.domain.errors import (
    ConcurrencyError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from papiq.core.domain.ids import DocumentId, RuleApplicationId, RuleId, UserId
from papiq.core.domain.jobs import Job
from papiq.core.domain.json_value import JsonValue
from papiq.core.domain.permissions import can_write_document
from papiq.core.domain.pipeline import (
    ACTOR,
    RULES_APPLY,
    TRIGGER,
    TRIGGER_APPLY,
    Lane,
    Node,
)
from papiq.core.domain.rule_planner import Effect, Mode, Note, NoteKind
from papiq.core.domain.rules import Rule, RuleApplication, RuleScope
from papiq.core.domain.users import User
from papiq.core.ports.clock import Clock
from papiq.core.ports.object_store import ObjectStore
from papiq.core.ports.patterns import PatternMatcher
from papiq.core.ports.repository import PAGE_SIZE, DocumentFilter, DocumentPosition
from papiq.core.ports.templates import TemplateRenderer
from papiq.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from papiq.core.services._access import field_definitions, load_actor
from papiq.core.services._jobs import LEASE, JobRunner, lost
from papiq.core.services.rules.management import visible_rule
from papiq.core.services.rules.running import (
    PatternBudget,
    Prepared,
    RuleRun,
    apply_plan,
    checked_rules,
    entry_beside,
    prepare,
    provenance,
    run_rules,
)

log = logging.getLogger(__name__)

APPLY_JOB = "rules.apply"
"""Job kind of a rule application; payload: application id."""
BATCH = 25
"""Documents per job; the next job continues."""
SCAN = 200
"""Documents a preview page looks at, at most."""
PREVIEW_BUDGET = 20.0
"""Seconds the patterns of a preview page may take together; the page ends early then."""
_WITH_LANE = DocumentFilter(lanes=frozenset({Lane.GREEN, Lane.YELLOW, Lane.RED}))


@dataclass(frozen=True)
class PreviewItem:
    """A document the rule would change: the changes, and conflicts (not applied unless
    accepted) and other actions that would not act."""

    document: Document
    effects: tuple[Effect, ...]
    conflicts: tuple[Note, ...]
    notes: tuple[Note, ...]


@dataclass(frozen=True)
class ApplyPreview:
    rule: Rule
    items: tuple[PreviewItem, ...]
    next_cursor: DocumentId | None


class RuleApplicationService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        store: ObjectStore,
        matcher: PatternMatcher,
        templates: TemplateRenderer,
        *,
        max_text: int,
        max_documents: int,
        pipeline_version: str,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._store = store
        self._matcher = matcher
        self._templates = templates
        self._max_text = max_text
        self._max_documents = max_documents
        self._version = pipeline_version
        self._jobs = JobRunner(uow, clock)

    # --- preview ---------------------------------------------------------------------------------

    async def preview(
        self,
        actor: UserId,
        id: RuleId,
        *,
        before: DocumentId | None = None,
        limit: int = PAGE_SIZE,
    ) -> ApplyPreview:
        """The documents the rule's current version would change, newest first, from the page
        ending at `before` on. A page looks at `SCAN` documents at most: it may hold fewer than
        `limit` items while `next_cursor` says there are more to look at."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            rule = await _applicable_rule(uow, user, id)
            if user.is_active_admin:
                documents = await uow.documents.query(
                    _WITH_LANE, after=_position(before), limit=SCAN
                )
            else:
                documents = await uow.documents.query_visible(
                    actor, _WITH_LANE, after=_position(before), limit=SCAN
                )
        items: list[PreviewItem] = []
        next_cursor = documents[-1].id if len(documents) == SCAN else None
        budget = PatternBudget(PREVIEW_BUDGET)
        last: DocumentId | None = None
        for document in documents:
            if len(items) == limit:
                next_cursor = items[-1].document.id
                break
            if budget.exhausted and last is not None:
                next_cursor = last
                break
            last = document.id
            async with self._uow() as uow:
                if not await _candidate(uow, user, rule, document):
                    continue
            prepared = await prepare(
                self._store, self._matcher, [rule], document, max_text=self._max_text, budget=budget
            )
            async with self._uow() as uow:
                current = await uow.documents.find(document.id)
                if current is None or not await _candidate(uow, user, rule, current):
                    continue
                run = await self._evaluate(uow, rule, current, prepared, accept=False)
            if run is None:
                continue
            report = run.plan.reports[0]
            conflicts = tuple(note for note in report.notes if note.kind is NoteKind.CONFLICT)
            others = tuple(note for note in report.notes if note.kind is not NoteKind.CONFLICT)
            if report.applied or conflicts:
                items.append(PreviewItem(current, tuple(report.applied), conflicts, others))
        return ApplyPreview(rule, tuple(items), next_cursor)

    # --- applying --------------------------------------------------------------------------------

    async def start(
        self,
        actor: UserId,
        id: RuleId,
        *,
        version: int,
        documents: Sequence[DocumentId],
        accept_conflicts: Collection[DocumentId] = (),
    ) -> RuleApplication:
        """Apply `version` of the rule to the selected documents in the background."""
        if len(documents) > self._max_documents:
            raise ValidationError(f"select at most {self._max_documents} documents")
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            rule = await _applicable_rule(uow, user, id)
            await uow.rules.get_version(rule.id, version)
            application = RuleApplication.create(
                rule_id=rule.id,
                rule_version=version,
                user_id=user.id,
                documents=tuple(documents),
                accept_conflicts=frozenset(accept_conflicts),
                now=self._clock.now(),
            )
            await uow.rule_applications.add(application)
            await _enqueue(uow, application.id, self._clock.now())
            await uow.commit()
        return application

    async def get(self, actor: UserId, id: RuleApplicationId) -> RuleApplication:
        """For the user who started it and for admins."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            application = await uow.rule_applications.find(id)
        if application is None or not (application.user_id == actor or user.is_active_admin):
            raise NotFoundError("rule application", id)
        return application

    # --- worker ----------------------------------------------------------------------------------

    async def run_next_job(self) -> bool:
        """Claim and run a due application job. Returns False if none was due."""
        return await self._jobs.run_next([APPLY_JOB], LEASE, self._attempt)

    async def _attempt(self, job: Job) -> None:
        try:
            await self._run(job)
        except ConcurrencyError:
            lost(job)
        except Exception as error:
            log.exception("rule application failed", extra={"job_id": str(job.id)})
            await self._abort(job, error)

    async def _abort(self, job: Job, error: Exception) -> None:
        """An unexpected error: end the application, so it does not run again and again."""
        try:
            async with self._uow() as uow:
                await uow.jobs.fail(job, error=f"{type(error).__name__}: {error}")
                application = await uow.rule_applications.find(
                    RuleApplicationId(UUID(str(job.payload.get("application_id"))))
                )
                if application is not None and application.finished_at is None:
                    application.finish(self._clock.now(), error="stopped by an internal error")
                    await uow.rule_applications.update(application)
                await uow.commit()
        except (ConcurrencyError, ValueError):
            log.warning("could not end a failed rule application", extra={"job_id": str(job.id)})

    async def _run(self, job: Job) -> None:
        try:
            id = RuleApplicationId(UUID(str(job.payload["application_id"])))
        except (KeyError, ValueError) as error:
            await self._jobs.invalid(job, error)
            return
        for _ in range(BATCH):
            done = await self._next_document(id)
            if done:
                async with self._uow() as uow:
                    await uow.jobs.complete(job)
                    await uow.commit()
                return
        async with self._uow() as uow:
            await uow.jobs.complete(job)
            await _enqueue(uow, id, self._clock.now())
            await uow.commit()

    async def _next_document(self, id: RuleApplicationId) -> bool:
        """Apply the rule to the next document of the application; True if it is finished."""
        async with self._uow() as uow:
            application = await uow.rule_applications.find(id)
            if application is None or application.finished_at is not None:
                return True
            if not application.remaining:
                application.finish(self._clock.now())
                await uow.rule_applications.update(application)
                await uow.commit()
                return True
            document = await uow.documents.find(application.remaining[0])
            rule = await uow.rules.find(application.rule_id)
            user = await uow.users.find(application.user_id)
            if rule is None or rule.deleted_at is not None or user is None or not user.active:
                application.finish(self._clock.now(), error="the rule or its user is gone")
                await uow.rule_applications.update(application)
                await uow.commit()
                return True
            rule = replace(
                rule, current=await uow.rules.get_version(rule.id, application.rule_version)
            )
        prepared = Prepared()
        if document is not None:
            prepared = await prepare(
                self._store, self._matcher, [rule], document, max_text=self._max_text
            )
        try:
            async with self._uow() as uow:
                application = await uow.rule_applications.get(id)
                await self._apply_one(uow, user, rule, prepared, application)
                await uow.rule_applications.update(application)
                await uow.commit()
        except ConcurrencyError:
            # The document changed meanwhile (or another worker took the application over;
            # then this fails again and the claim is lost).
            async with self._uow() as uow:
                application = await uow.rule_applications.get(id)
                application.record_skipped(
                    application.remaining[0], "changed meanwhile; not applied"
                )
                await uow.rule_applications.update(application)
                await uow.commit()
        return False

    async def _apply_one(
        self,
        uow: UnitOfWork,
        user: User,
        rule: Rule,
        prepared: Prepared,
        application: RuleApplication,
    ) -> None:
        """Apply the rule to the next document of `application` and record what it did."""
        id = application.remaining[0]
        document = await uow.documents.find(id)
        if document is None or not await _candidate(uow, user, rule, document):
            application.record_skipped(id, "not available")
            return
        run = await self._evaluate(
            uow, rule, document, prepared, accept=id in application.accept_conflicts
        )
        if run is None or not run.plan.effects:
            application.record_unchanged()
            return
        now = self._clock.now()
        definitions = await field_definitions(uow)
        problem = apply_plan(document, run.plan, definitions, now)
        if problem is not None:
            application.record_skipped(id, problem)
            return
        await uow.processing_log.append(
            entry_beside(
                document,
                node=Node.APPLY_RULES,
                model_version=RULES_APPLY,
                input={
                    TRIGGER: TRIGGER_APPLY,
                    ACTOR: str(user.id),
                    "application_id": str(application.id),
                    "rules": checked_rules([rule]),
                },
                output=run.output(),
                version=self._version,
                now=now,
            )
        )
        await uow.documents.update(document)
        await uow.outbox.add(document.pull_events())
        application.record_applied()

    async def _evaluate(
        self,
        uow: UnitOfWork,
        rule: Rule,
        document: Document,
        prepared: Prepared,
        *,
        accept: bool,
    ) -> RuleRun | None:
        """The rule on the document; None if it does not hold."""
        owner = await uow.users.get(document.owner_id)
        definitions = await field_definitions(uow)
        run = await run_rules(
            uow,
            self._matcher,
            self._templates,
            mode=Mode.RETROACTIVE,
            document=document,
            owner=owner,
            rules=[rule],
            prepared=prepared,
            origin=provenance(await uow.processing_log.list_for(document.id), document),
            definitions=definitions,
            accept_conflicts=accept,
        )
        return run if run.plan.reports else None


async def _applicable_rule(uow: UnitOfWork, user: User, id: RuleId) -> Rule:
    """A user rule its owner or an admin applies; a global rule anyone applies."""
    rule = await visible_rule(uow, user, id)
    if rule.deleted_at is not None:
        raise NotFoundError("rule", id)
    if rule.scope is RuleScope.USER and not (rule.owner_id == user.id or user.is_active_admin):
        raise PermissionDeniedError("only the owner and admins apply a user rule")
    return rule


async def _candidate(uow: UnitOfWork, user: User, rule: Rule, document: Document) -> bool:
    """The caller may write to the document, it is not being processed, and a user rule's
    document is its owner's."""
    if document.lane is None:
        return False
    if rule.scope is RuleScope.USER and document.owner_id != rule.owner_id:
        return False
    space = await uow.spaces.get(document.space_id)
    return can_write_document(user, document, space)


async def _enqueue(uow: UnitOfWork, id: RuleApplicationId, now: datetime) -> None:
    payload: dict[str, JsonValue] = {"application_id": str(id)}
    await uow.jobs.enqueue(APPLY_JOB, payload, run_at=now, dedup_key=f"{APPLY_JOB}:{id}")


def _position(before: DocumentId | None) -> DocumentPosition | None:
    return DocumentPosition.after(before)
