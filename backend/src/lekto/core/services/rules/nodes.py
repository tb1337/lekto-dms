"""The pipeline nodes `apply_rules` and `file`."""

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from lekto.core.domain.classification import (
    CHECKS,
    SPACE,
    FieldCheck,
    checks_from_json,
    field_key,
    node_reasons,
)
from lekto.core.domain.documents import Document
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import FieldDefinition
from lekto.core.domain.ids import FieldId, SpaceId
from lekto.core.domain.json_value import JsonObject, JsonValue, as_list
from lekto.core.domain.pipeline import RULES, TRIGGER, Node, NodeResult, NodeRun, Outcome
from lekto.core.domain.reasons import Reason, ReasonCode, because, reasons_to_json
from lekto.core.domain.rule_planner import Mode
from lekto.core.domain.rules import Rule, Trigger
from lekto.core.domain.sorting import sort_key
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.patterns import PatternMatcher
from lekto.core.ports.templates import TemplateRenderer
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import field_definitions, space_label
from lekto.core.services.inbox import MODEL_NODES, latest_entries
from lekto.core.services.rules.running import (
    SENDS,
    SENDS_REFUSED,
    STEPS_LOG,
    STEPS_REPORTED,
    Chain,
    Prepared,
    Send,
    active_rules,
    apply_plan,
    back_and_forth,
    checked_rules,
    deliverable,
    prepare,
    provenance,
    queue_sends,
    reachable_rules,
    space_rules,
)
from lekto.core.services.rules.steps import TaskBook, run_rules, task_book
from lekto.core.services.tasks.desk import TASKS_LOCK, Ask, TaskDesk
from lekto.core.services.tasks.settling import Delegation


class ApplyRulesNode:
    """Runs the rules with trigger `ingest`: the global ones and those of the document's space.
    If they file the document into another space, that space's rules run next on it, and so
    on: each space a document enters runs its rules, each at most once in the chain; rules
    that would file it back into a space it was in stop the chain, uncertain ("rules move it
    back and forth").

    The text is loaded and the patterns of every rule the chain may meet run here, outside any
    transaction; the rules are evaluated and applied when the result is stored, on the state
    that is stored. Conflicts, refused actions and forced reviews make the node uncertain: the
    document waits in the inbox before it is filed. So does a required field set by hand that
    has no value after the rules (issue #52), and a rule's request through a webhook whose
    owner may not read the document, unless a person decided in this run (it is only reported
    then: no click can grant the right). The requests the rules send go when the document is
    filed (`FileNode`), from the output's `sends`.

    A rule whose steps ask a webhook (`steps`) has the node hand the request to a task and wait
    (`Delegation`): the chain is first walked on a copy of the document; while a rule waits for
    an answer nothing is applied, and the node runs anew whenever one of its tasks ends. Once
    every rule has what it waits for, the chain runs for real, with the answers. A step without
    an answer that says "red" fails the node, and no rule acts."""

    def __init__(
        self,
        uow: UnitOfWorkFactory,
        store: ObjectStore,
        matcher: PatternMatcher,
        templates: TemplateRenderer,
        *,
        max_text: int,
        desk: TaskDesk | None = None,
        link_base: str | None = None,
    ) -> None:
        """`desk`: places the tasks of steps that ask (without, no rule asks); `link_base`
        (`LEKTO_PUBLIC_URL`): the document's link in what a step asks with."""
        self._uow = uow
        self._store = store
        self._matcher = matcher
        self._templates = templates
        self._max_text = max_text
        self._desk = desk
        self._link_base = link_base

    async def run(self, document: Document) -> "RulesResult":
        async with self._uow() as uow:
            rules = await reachable_rules(
                uow, document.space_id, Trigger.INGEST, include_global=True
            )
        prepared = await prepare(
            self._store, self._matcher, rules, document, max_text=self._max_text
        )
        asks = self._desk is not None and any(rule.definition.asks for rule in rules)
        return RulesResult(
            prepared,
            self._matcher,
            self._templates,
            desk=self._desk if asks else None,
            link_base=self._link_base,
        )


@dataclass
class _Chain:
    """What walking the chain of spaces brought: the node's result, or the requests to send
    and whether a rule waits for an answer (nothing is final then), or a failure (red)."""

    result: NodeResult
    asks: list[Ask]
    waiting: bool
    failed: bool

    @property
    def pending(self) -> bool:
        return bool(self.asks) or self.waiting


@dataclass(frozen=True)
class RulesResult:
    prepared: Prepared
    matcher: PatternMatcher
    templates: TemplateRenderer
    desk: TaskDesk | None = None
    link_base: str | None = None

    async def apply(
        self, uow: UnitOfWork, document: Document, now: datetime
    ) -> NodeResult | Delegation:
        log = await uow.processing_log.list_for(document.id)
        if self.desk is None:
            return (await self._chain(uow, document, now, log, None, probe=False)).result
        locked = False
        while True:
            book = await task_book(uow, document, log)
            probe = await self._chain(uow, copy.deepcopy(document), now, log, book, probe=True)
            if probe.failed or not probe.pending:
                break
            if probe.asks:
                if not locked:
                    await uow.lock(TASKS_LOCK)
                    locked = True
                placed = await self.desk.place(
                    uow, document, Node.APPLY_RULES, probe.asks, now, locked=True
                )
                if any(task.status.settled for task in placed):
                    continue  # a request could not be made: the steps read it as no answer
            book = await task_book(uow, document, log)
            return Delegation(book.open_deadline())
        if probe.failed:
            return probe.result  # red: no rule acts
        return (await self._chain(uow, document, now, log, book, probe=False)).result

    async def _chain(
        self,
        uow: UnitOfWork,
        document: Document,
        now: datetime,
        log: Sequence[NodeRun],
        book: TaskBook | None,
        *,
        probe: bool,
    ) -> _Chain:
        """Walk the chain of spaces on `document` (`probe`: a copy, nothing else is written).
        Stops where a rule waits for an answer or the node fails."""
        definitions = await field_definitions(uow)
        earlier = [space for space in chain_before(log) if space != document.space_id]
        visited = [*earlier, document.space_id]
        first = True
        chain = Chain()
        looked: list[Rule] = []
        output: JsonObject = {}
        reasons: list[Reason] = []
        sends: list[Send] = []
        refused: list[Reason] = []
        asks: list[Ask] = []
        waiting = False
        failures: list[Reason] = []
        while True:
            # The first space with the global rules, every one it enters with its own.
            rules = (
                await active_rules(uow, document.space_id, Trigger.INGEST)
                if first
                else await space_rules(uow, document.space_id, Trigger.INGEST)
            )
            first = False
            looked += rules
            if not rules:
                break
            origin = chain.origin(
                provenance(await uow.processing_log.list_for(document.id), document)
            )
            run = await run_rules(
                uow,
                self.matcher,
                self.templates,
                mode=Mode.INGEST,
                document=document,
                rules=rules,
                prepared=self.prepared,
                origin=origin,
                definitions=definitions,
                locked=origin.person,
                book=book,
                link_base=self.link_base,
                now=now,
            )
            output = _merged(output, run.output())
            if run.failures or run.pending:
                asks += run.asks
                waiting = waiting or run.waiting
                failures += run.failures
                break
            reasons += run.plan.reasons
            reasons += run.reviews
            target = run.plan.space
            if target is not None and target != document.space_id and target in visited:
                reasons.append(back_and_forth(await _names(uow, [*visited, target])))
                problem = await apply_plan(
                    uow, document, replace(run.plan, space=None), definitions, now, arrive=not probe
                )
                reasons += [problem] if problem else []
                break
            problem = await apply_plan(uow, document, run.plan, definitions, now, arrive=not probe)
            reasons += [problem] if problem else []
            ok, not_sent = await deliverable(uow, run.sends, document)
            sends += ok
            refused += not_sent
            chain.record(run.plan, document)
            if document.space_id == visited[-1]:
                break
            visited.append(document.space_id)
        input: dict[str, JsonValue] = {
            TRIGGER: Trigger.INGEST.value,
            "rules": checked_rules(looked),
        }
        if earlier:
            input["chain"] = [str(space) for space in earlier]
        if failures:
            failed = NodeResult(
                outcome=Outcome.FAILED,
                reasons=tuple(failures),
                model_version=RULES,
                input=input,
                output=output,
            )
            return _Chain(failed, asks, waiting, failed=True)
        if len(visited) > len(earlier) + 1:
            output["spaces"] = [str(space) for space in visited[len(earlier) :]]
            if _suggested_here(log, document):
                document.settle(Node.JUDGE, now)
        if sends:
            output[SENDS] = [send.to_json() for send in sends]
        if refused:
            output[SENDS_REFUSED] = reasons_to_json(refused)
            if not document.processing.decided:
                reasons += refused
        if reasons:
            result = NodeResult(
                outcome=Outcome.UNCERTAIN,
                reasons=tuple(reasons),
                model_version=RULES,
                input=input,
                output=output,
            )
        else:
            result = NodeResult(outcome=Outcome.OK, model_version=RULES, input=input, output=output)
        return _Chain(_waiting_for_hand(document, definitions, result), asks, waiting, failed=False)


def _suggested_here(log: Sequence[NodeRun], document: Document) -> bool:
    """Whether the judge is uncertain only because it suggested the space the document lies
    in now (the rules filed it there): nothing is left for a person to decide."""
    if document.processing.outcome(Node.JUDGE) is not Outcome.UNCERTAIN:
        return False
    entry = latest_entries(log).get(Node.JUDGE)
    if entry is None:
        return False
    try:
        open = [
            check for check in checks_from_json(entry.result.output.get(CHECKS)) if not check.ok
        ]
    except ValidationError:
        return False
    return bool(open) and all(
        check.field == SPACE and check.suggestion == str(document.space_id) for check in open
    )


def chain_before(log: Sequence[NodeRun]) -> list[SpaceId]:
    """The spaces the rules of this processing filed the document through before a person's
    click let them go on: the chains of the latest `apply_rules` runs that waited for a person,
    one after the other, since the model's latest run. A chain goes on across a click, so the
    loop guard remembers them; a run that ended without waiting starts afresh."""
    latest = latest_entries(log, by_model=True)
    model_run = max((latest[node].run for node in MODEL_NODES if node in latest), default=0)
    runs = [
        entry
        for entry in log
        if entry.node is Node.APPLY_RULES
        and entry.result.model_version == RULES
        and entry.run >= model_run
    ]
    spaces: list[SpaceId] = []
    for entry in reversed(runs):
        if entry.result.outcome is not Outcome.UNCERTAIN:
            break
        chain = [SpaceId(UUID(str(space))) for space in as_list(entry.result.output.get("spaces"))]
        spaces = [*chain, *spaces]
    return list(dict.fromkeys(spaces))


def _merged(output: JsonObject, more: JsonObject) -> JsonObject:
    """The output of the rule runs of a chain: their reports, checks and reviews one after the
    other (one run: its own output)."""
    if not output:
        return more
    merged: JsonObject = dict(output)
    for key in ("rules", CHECKS, "reviews", "problems", STEPS_LOG, STEPS_REPORTED):
        if key in more:
            merged[key] = [*as_list(output.get(key)), *as_list(more[key])]
    return merged


async def _names(uow: UnitOfWork, spaces: Sequence[SpaceId]) -> list[str]:
    users = {user.id: user for user in await uow.users.list_all()}
    names = []
    for id in spaces:
        space = await uow.spaces.find(id)
        names.append(str(id) if space is None else space_label(space, users))
    return names


def _waiting_for_hand(
    document: Document, definitions: Mapping[FieldId, FieldDefinition], result: NodeResult
) -> NodeResult:
    """`result`, uncertain with a check for each required field set by hand that neither a
    person nor a rule has given a value: the person enters it in the inbox."""
    waiting = [
        FieldCheck(
            field=field_key(definition.id),
            outcome=Outcome.UNCERTAIN,
            confidence=0,
            reasons=(because(ReasonCode.FIELD_BY_HAND_MISSING, field=definition.name),),
        )
        for definition in sorted(definitions.values(), key=lambda item: sort_key(item.name))
        if not definition.is_read
        and definition.applies_to(document.document_type_id)
        and definition.is_required_for(document.document_type_id)
        and definition.id not in document.fields
    ]
    if not waiting:
        return result
    checks = result.output.get(CHECKS)
    output = {
        **result.output,
        CHECKS: [*as_list(checks), *(c.to_json() for c in waiting)],
    }
    reasons = (*result.reasons, *node_reasons(waiting))
    return replace(result, outcome=Outcome.UNCERTAIN, reasons=reasons, output=output)


class FileNode:
    """Files the document into its space. Rights hang on the space; whoever put the document
    there (an upload, a person, a rule) was allowed to, so filing always succeeds. The requests
    the rules of this run send through webhooks go now (Tobi, 25.10.2026): a green document at
    once, a yellow one once a person confirmed it, a red one never, and none twice."""

    async def run(self, document: Document) -> "FileResult":
        return FileResult()


@dataclass(frozen=True)
class FileResult:
    async def apply(self, uow: UnitOfWork, document: Document, now: datetime) -> NodeResult:
        run = document.processing.run
        entry = next(
            (
                item
                for item in reversed(await uow.processing_log.list_for(document.id))
                if item.node is Node.APPLY_RULES
                and item.run == run
                and item.result.model_version == RULES
            ),
            None,
        )
        sends = [] if entry is None else _sends(entry.result.output)
        await queue_sends(uow, sends, document, now)
        if not sends:
            return NodeResult(outcome=Outcome.OK)
        return NodeResult(outcome=Outcome.OK, output={SENDS: [send.to_json() for send in sends]})


def _sends(output: JsonObject) -> list[Send]:
    return [send for item in as_list(output.get(SENDS)) if (send := Send.from_json(item))]
