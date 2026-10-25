"""Applying a rule to existing documents, on request: a preview, then a background job.

- Who, on what: a space rule by the editors of its space or an admin, on the documents in its
  space; a global rule by anyone, on the documents they may edit (an admin: every document,
  Tobi, 08.10.2026). Documents the caller may not edit appear neither one by one nor as a
  count; documents in processing are left out.
- The preview evaluates the rule's current version on each document (its state, not a change)
  and lists the documents it would change, with conflicts: a field that has another value. It
  plays the rule as applying does, with the chain of the spaces it files the document into
  (`ChangeRules.after_arrival`), in a unit of work it never commits: each document shows the
  steps and where it ends up; with conflicts also how that goes when they are accepted.
- The application pins one version. A background job works through the selected documents, one
  transaction each, checks the rights again, takes the rule's value where the person accepted
  the conflict, skips other conflicts, and logs every document. A forced review does not act
  (it would change who sees a document). After `BATCH` documents the job hands the worker back
  and continues in a new job, so processing and indexing do not wait.
"""

import copy
import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import (
    ConcurrencyError,
    InvalidTransitionError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from lekto.core.domain.ids import DocumentId, RuleApplicationId, RuleId, SpaceId, UserId
from lekto.core.domain.jobs import Job
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.permissions import can_edit_document, space_role
from lekto.core.domain.pipeline import (
    ACTOR,
    RULES_APPLY,
    TRIGGER,
    TRIGGER_APPLY,
    Lane,
    Node,
)
from lekto.core.domain.reasons import Reason, ReasonCode, because, reasons_to_json
from lekto.core.domain.rule_planner import Effect, Mode, Note, NoteKind
from lekto.core.domain.rules import (
    Rule,
    RuleApplication,
    RuleDefinition,
    RuleScope,
    SetSpace,
    Trigger,
)
from lekto.core.domain.users import User
from lekto.core.ports.clock import Clock
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.patterns import PatternMatcher
from lekto.core.ports.repository import PAGE_SIZE, DocumentFilter, DocumentPosition
from lekto.core.ports.templates import TemplateRenderer
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import field_definitions, load_actor
from lekto.core.services._jobs import LEASE, JobRunner, lost
from lekto.core.services.rules.changes import ArrivalStep, ChangeRules
from lekto.core.services.rules.management import visible_rule
from lekto.core.services.rules.running import (
    SENDS,
    SENDS_REFUSED,
    PatternBudget,
    Prepared,
    RuleRun,
    Send,
    apply_plan,
    checked_rules,
    deliverable,
    entry_beside,
    prepare,
    provenance,
    queue_sends,
    reachable_rules,
)
from lekto.core.services.rules.steps import run_rules

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
class Outcome:
    """Where applying the rule leaves a document: the steps of the spaces it enters on the way
    (`ChangeRules.after_arrival`) and the space it ends up in."""

    space_id: SpaceId
    chain: tuple[ArrivalStep, ...]


@dataclass(frozen=True)
class PreviewItem:
    """A document the rule would change or send about: the changes, and conflicts (not applied
    unless accepted) and other actions that would not act; the outcome of applying it, and with
    conflicts the outcome when they are accepted. `sends`: the requests it would send through
    webhooks, `refused` why others would not go."""

    document: Document
    effects: tuple[Effect, ...]
    conflicts: tuple[Note, ...]
    notes: tuple[Note, ...]
    outcome: Outcome
    accepted: Outcome | None = None
    sends: tuple[Send, ...] = ()
    refused: tuple[Reason, ...] = ()


@dataclass(frozen=True)
class _Played:
    """The rule played on a document (`RuleApplicationService._play`): its run, why its change
    did not apply, and the chain after it."""

    run: RuleRun
    problem: Reason | None
    chain: tuple[ArrivalStep, ...]
    sends: tuple[Send, ...] = ()
    refused: tuple[Reason, ...] = ()


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
        # A document a rule files into another space runs that space's rules (as on arrival).
        self._arrival = ChangeRules(
            store, matcher, templates, max_text=max_text, pipeline_version=pipeline_version
        )

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
            following = await _following(uow, rule)
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
                self._store,
                self._matcher,
                [rule, *following],
                document,
                max_text=self._max_text,
                budget=budget,
            )
            item = await self._preview_one(user, rule, document.id, prepared)
            if item is not None:
                items.append(item)
        return ApplyPreview(rule, tuple(items), next_cursor)

    async def _preview_one(
        self, user: User, rule: Rule, id: DocumentId, prepared: Prepared
    ) -> PreviewItem | None:
        """The rule played on the document as applying plays it, in a unit of work that is
        never committed; None if it would change nothing."""
        async with self._uow() as uow:
            current = await uow.documents.find(id)
            if current is None or not await _candidate(uow, user, rule, current):
                return None
            shown = copy.deepcopy(current)
            played = await self._play(uow, user, rule, current, prepared, accept=False)
            outcome = Outcome(current.space_id, () if played is None else played.chain)
        if played is None:
            return None
        report = played.run.plan.reports[0]
        conflicts = tuple(note for note in report.notes if note.kind is NoteKind.CONFLICT)
        others = tuple(note for note in report.notes if note.kind is not NoteKind.CONFLICT)
        if not (report.applied or conflicts or played.sends or played.refused):
            return None
        accepted: Outcome | None = None
        if conflicts:
            async with self._uow() as uow:
                current = await uow.documents.find(id)
                if current is not None:
                    other = await self._play(uow, user, rule, current, prepared, accept=True)
                    accepted = Outcome(current.space_id, () if other is None else other.chain)
        return PreviewItem(
            shown,
            tuple(report.applied),
            conflicts,
            others,
            outcome,
            accepted,
            played.sends,
            played.refused,
        )

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
            _not_asking((await uow.rules.get_version(rule.id, version)).definition)
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
            following = await _following(uow, rule)
        prepared = Prepared()
        if document is not None:
            prepared = await prepare(
                self._store, self._matcher, [rule, *following], document, max_text=self._max_text
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
                    application.remaining[0], because(ReasonCode.SKIP_CHANGED_MEANWHILE)
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
            application.record_skipped(id, because(ReasonCode.SKIP_NOT_AVAILABLE))
            return
        played = await self._play(
            uow,
            user,
            rule,
            document,
            prepared,
            accept=id in application.accept_conflicts,
            application=application.id,
        )
        if played is None or not (played.run.plan.effects or played.sends):
            application.record_unchanged()
            return
        if played.problem is not None:
            application.record_skipped(id, played.problem)
            return
        await uow.documents.update(document)
        await uow.outbox.add(document.pull_events())
        application.record_applied()

    async def _play(
        self,
        uow: UnitOfWork,
        user: User,
        rule: Rule,
        document: Document,
        prepared: Prepared,
        *,
        accept: bool,
        application: RuleApplicationId | None = None,
    ) -> _Played | None:
        """Apply the rule to `document` in `uow`, with its log entry and the chain of the
        spaces it files the document into: what applying does and the preview plays (in a unit
        it does not commit). None if the rule does not hold."""
        run = await self._evaluate(uow, user, rule, document, prepared, accept=accept)
        if run is None:
            return None
        if not run.plan.effects and not run.sends:
            return _Played(run, None, ())
        now = self._clock.now()
        definitions = await field_definitions(uow)
        source = await uow.spaces.get(document.space_id)
        problem = await apply_plan(uow, document, run.plan, definitions, now)
        if problem is not None:
            return _Played(run, problem, ())
        sends, refused = await deliverable(uow, run.sends, document)
        await queue_sends(uow, sends, document, now)
        output = run.output()
        if sends:
            output[SENDS] = [send.to_json() for send in sends]
        if refused:
            output[SENDS_REFUSED] = reasons_to_json(refused)
        input: dict[str, JsonValue] = {
            TRIGGER: TRIGGER_APPLY,
            ACTOR: str(user.id),
            "rules": checked_rules([rule]),
        }
        if application is not None:
            input["application_id"] = str(application)
        await uow.processing_log.append(
            entry_beside(
                document,
                node=Node.APPLY_RULES,
                model_version=RULES_APPLY,
                input=input,
                output=output,
                version=self._version,
                now=now,
            )
        )
        chain: list[ArrivalStep] = []
        if document.space_id != source.id:
            chain = await self._arrival.after_arrival(
                uow,
                document=document,
                source=source,
                prepared=prepared,
                definitions=definitions,
                now=now,
                by_person=False,
                applier=user,
            )
        return _Played(run, None, tuple(chain), tuple(sends), tuple(refused))

    async def _evaluate(
        self,
        uow: UnitOfWork,
        user: User,
        rule: Rule,
        document: Document,
        prepared: Prepared,
        *,
        accept: bool,
    ) -> RuleRun | None:
        """The rule on the document; None if it does not hold."""
        definitions = await field_definitions(uow)
        run = await run_rules(
            uow,
            self._matcher,
            self._templates,
            mode=Mode.RETROACTIVE,
            document=document,
            rules=[rule],
            prepared=prepared,
            origin=provenance(await uow.processing_log.list_for(document.id), document),
            definitions=definitions,
            accept_conflicts=accept,
            applier=user.id,
        )
        return run if run.plan.reports else None


async def _applicable_rule(uow: UnitOfWork, user: User, id: RuleId) -> Rule:
    """A space rule the editors of its space or an admin apply; a global rule anyone
    applies."""
    rule = await visible_rule(uow, user, id)
    if rule.deleted_at is not None:
        raise NotFoundError("rule", id)
    _not_asking(rule.definition)
    if rule.space_id is not None:
        space = await uow.spaces.find(rule.space_id)
        role = None if space is None else space_role(user, space)
        if role is None or not role.can_edit:
            raise PermissionDeniedError(because(ReasonCode.SPACE_RULE_APPLY))
    return rule


def _not_asking(definition: RuleDefinition) -> None:
    """A rule whose steps ask a webhook runs on arrival only (Tobi, 25.10.2026):
    InvalidTransitionError."""
    if definition.asks:
        raise InvalidTransitionError(because(ReasonCode.RULE_ASKS_ON_ARRIVAL, rule=definition.name))


async def _following(uow: UnitOfWork, rule: Rule) -> list[Rule]:
    """The rules of the spaces the rule may file a document into, and of the spaces those file
    it into: they run after it (`ChangeRules.after_arrival`), so their patterns are prepared
    with it."""
    found: dict[RuleId, Rule] = {}
    for action in rule.definition.actions:
        if isinstance(action, SetSpace):
            for item in await reachable_rules(
                uow, action.space_id, Trigger.INGEST, include_global=False
            ):
                found.setdefault(item.id, item)
    return list(found.values())


async def _candidate(uow: UnitOfWork, user: User, rule: Rule, document: Document) -> bool:
    """The caller may edit the document, it is not being processed, and a space rule's
    document lies in its space."""
    if document.lane is None:
        return False
    if rule.scope is RuleScope.SPACE and document.space_id != rule.space_id:
        return False
    space = await uow.spaces.get(document.space_id)
    return can_edit_document(user, document, space)


async def _enqueue(uow: UnitOfWork, id: RuleApplicationId, now: datetime) -> None:
    payload: dict[str, JsonValue] = {"application_id": str(id)}
    await uow.jobs.enqueue(APPLY_JOB, payload, run_at=now, dedup_key=f"{APPLY_JOB}:{id}")


def _position(before: DocumentId | None) -> DocumentPosition | None:
    return DocumentPosition.after(before)
