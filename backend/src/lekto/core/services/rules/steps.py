"""A rule's steps, one after the other (Tobi, 25.10.2026, `webhooks-und-auftraege.md`).

A rule whose conditions hold goes through its steps in order: actions (which the planner
combines with the other rules' at the end), conditions on the document as the rule's own steps
before left it (`StepCondition`: if one does not hold, the rule ends there and its steps before
count), and steps that ask a webhook (`AskWebhook`): their answer is `steps.<name>` for the
steps after them. A step that asks and has no answer yet ends the walk: the rule waits for it
(`Walk.ask`, `Walk.waiting`), and the node delegates (`rules.nodes`). Without an answer (none in
time, an error, an invalid one) the step does what it says (`Missing`): the node fails (red),
the rule ends there (yellow), or it goes on without `steps.<name>`. Once a person decided in the
run (`Processing.decided`), a missing answer is only reported: no click can bring it. Outside
processing (the rules a space runs when a person moves a document into it) a step that asks is
not asked: the rule ends there.

What the tasks brought is read from the tasks of the node's run (`TaskBook`); after a
confirmation in the inbox that changed nothing, from those of the run before as well, so the
steps do not ask again (Tobi, 25.10.2026).
"""

import contextlib
import copy
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import FieldDefinition
from lekto.core.domain.ids import FieldId, RuleId, UserId
from lekto.core.domain.json_value import JsonObject, JsonValue
from lekto.core.domain.permissions import in_reach
from lekto.core.domain.pipeline import (
    CHOSEN_SPACE,
    CORRECTED,
    PERSON,
    TAGS_ADDED,
    TAGS_REMOVED,
    Node,
    NodeRun,
)
from lekto.core.domain.reasons import Reason, ReasonCode, because
from lekto.core.domain.rule_conditions import Facts, Match, distrusted_fields, evaluate, matches
from lekto.core.domain.rule_planner import Mode, Situation, plan
from lekto.core.domain.rules import Action, AskWebhook, Missing, Rule, SendWebhook, StepCondition
from lekto.core.domain.tasks import Task, TaskKind, TaskStatus, TaskStep
from lekto.core.domain.templates import TemplateValue, json_value
from lekto.core.ports.patterns import PatternMatcher
from lekto.core.ports.templates import TemplateRenderer
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.services._templates import document_json, webhook_values
from lekto.core.services.rules.running import (
    PatternKey,
    Prepared,
    Provenance,
    RuleRun,
    Send,
    facts,
    field_patterns,
    situation,
    taxonomy,
)
from lekto.core.services.tasks.desk import Ask, TaskRequest

NOT_ASKED = "not_asked"
"""The status, in the log, of a step that asks outside processing: it is not asked."""
MAX_LOGGED_ANSWER = 10_000
"""An answer longer than this (as JSON) is not repeated in the log; the task keeps it."""


@dataclass(frozen=True)
class TaskBook:
    """What the tasks of a node's run brought, by what they ask for (`Task.key`): `current`
    those of the run, `earlier` those of the runs before that a confirmation without a change
    carries on (answered or ended without an answer)."""

    current: Mapping[str, Task] = field(default_factory=dict)
    earlier: Mapping[str, Task] = field(default_factory=dict)

    def find(self, key: str) -> Task | None:
        return self.current.get(key) or self.earlier.get(key)

    def open_deadline(self) -> "datetime | None":
        """When the last open task of the run ends at the latest."""
        deadlines = [
            task.deadline
            for task in self.current.values()
            if task.status is TaskStatus.OPEN and task.deadline is not None
        ]
        return max(deadlines, default=None)


async def task_book(uow: UnitOfWork, document: Document, log: Sequence[NodeRun]) -> TaskBook:
    """The tasks of the rules node in the document's run, and of the runs before it that a
    confirmation without a change carries on."""
    run = document.processing.run
    current = {
        task.key: task for task in await uow.tasks.list_for_run(document.id, Node.APPLY_RULES, run)
    }
    earlier: dict[str, Task] = {}
    while run > 1 and _confirmed_unchanged(log, run):
        run -= 1
        for task in reversed(await uow.tasks.list_for_run(document.id, Node.APPLY_RULES, run)):
            if task.status in (TaskStatus.ANSWERED, TaskStatus.FAILED, TaskStatus.EXPIRED):
                earlier.setdefault(task.key, task)
    return TaskBook(current, earlier)


def _confirmed_unchanged(log: Sequence[NodeRun], run: int) -> bool:
    """Whether `run` began with a confirmation in the inbox that changed nothing: no value
    altered, no tag added or removed, no space chosen, no field read again."""
    confirmed = False
    for entry in log:
        if entry.run != run:
            continue
        result = entry.result
        if entry.node is Node.FIELDS and result.model_version != PERSON:
            return False  # a type correction reads the fields again
        if entry.node is Node.APPLY_RULES and result.model_version == PERSON:
            output = result.output
            if (
                output.get(CORRECTED)
                or output.get(TAGS_ADDED)
                or output.get(TAGS_REMOVED)
                or output.get(CHOSEN_SPACE)
            ):
                return False
            confirmed = True
    return confirmed


@dataclass(frozen=True)
class Walk:
    """How far a rule's steps went on a document.

    - `match`: the rule as it matched; its trust drops if a condition step holds only with
      unconfirmed model values.
    - `actions`: the actions that count: all of them, or those before the step where the
      rule ended (a condition that does not hold, an answer that did not come, a step that
      asks and waits).
    - `steps`: the answers so far, by step name.
    - `ask`: the request of the step the rule waits at, if it is to be sent (or waits to be
      sent: its task is queued); `waiting`: it waits for a task that was sent.
    - `review`: why the document waits for a person (yellow); `failure`: why the node fails
      (red); `notes`: what is only reported.
    - `log`: each step that is not an action, for the processing log.
    """

    match: Match
    actions: tuple[Action, ...]
    steps: dict[str, JsonValue] = field(default_factory=dict)
    ask: Ask | None = None
    waiting: bool = False
    review: Reason | None = None
    failure: Reason | None = None
    notes: tuple[Reason, ...] = ()
    log: tuple[JsonObject, ...] = ()

    @property
    def rule(self) -> Rule:
        return self.match.rule

    @property
    def ended_early(self) -> bool:
        return len(self.actions) != len(
            [step for step in self.rule.definition.actions if _is_action(step)]
        )

    @property
    def pending(self) -> bool:
        """The rule waits for an answer."""
        return self.ask is not None or self.waiting

    @classmethod
    def plain(cls, match: Match) -> "Walk":
        """A rule without steps between its actions: all of them count."""
        return cls(match, tuple(match.rule.definition.actions))


@dataclass(frozen=True)
class Walker:
    """What walking a rule's steps needs of the run (`running.run_rules`)."""

    uow: UnitOfWork
    matcher: PatternMatcher
    document: Document
    context: Situation
    prepared: Prepared
    origin: Provenance
    definitions: Mapping[FieldId, FieldDefinition]
    book: TaskBook | None
    link_base: str | None
    now: datetime

    async def walk(self, match: Match) -> Walk:
        rule = match.rule
        if not rule.definition.has_steps:
            return Walk.plain(match)
        decided = self.document.processing.decided
        actions: list[Action] = []
        steps: dict[str, JsonValue] = {}
        notes: list[Reason] = []
        log: list[JsonObject] = []
        for index, step in enumerate(rule.definition.actions):
            match step:
                case StepCondition(conditions=group):
                    state = await self._after(match, actions, steps)
                    facts = await self._facts(rule, state, steps)
                    holds = evaluate(group, facts, self.definitions)
                    log.append({"step": index, "type": step.type, "holds": bool(holds)})
                    if not holds:
                        return Walk(
                            match, tuple(actions), steps, notes=tuple(notes), log=tuple(log)
                        )
                    if evaluate(group, facts, self.definitions, distrust=True) is not True:
                        distrusted = (*match.distrusted, *distrusted_fields(group, facts))
                        match = replace(
                            match, trusted=False, distrusted=tuple(dict.fromkeys(distrusted))
                        )
                case AskWebhook():
                    walk = await self._ask(match, index, step, actions, steps, notes, log, decided)
                    if walk is None:
                        continue  # answered, or goes on without an answer
                    return replace(walk, notes=tuple(notes))
                case _:
                    actions.append(step)
        return Walk(match, tuple(actions), steps, notes=tuple(notes), log=tuple(log))

    async def _ask(
        self,
        match: Match,
        index: int,
        step: AskWebhook,
        actions: list[Action],
        steps: dict[str, JsonValue],
        notes: list[Reason],
        log: list[JsonObject],
        decided: bool,
    ) -> Walk | None:
        """A step that asks: None if the rule goes on (it has its answer, or goes on without
        one); otherwise how the rule ends here. `steps`, `notes` and `log` grow with the
        step."""
        rule = match.rule
        key = task_step(rule, step).key
        task = None if self.book is None else self.book.find(key)
        entry: JsonObject = {"step": index, "type": step.type, "name": step.name}
        if task is not None:
            entry |= {"task_id": str(task.id), "status": task.status.value}
            if task.producer:
                entry["producer"] = task.producer
        if task is not None and task.status is TaskStatus.ANSWERED:
            steps[step.name] = task.answer
            log.append(entry | _answer_log(task.answer))
            return None
        if task is not None and task.status.settled:
            assert task.reason is not None
            log.append(entry | {"reason": task.reason.to_json()})
            return self._without_answer(
                match, step, actions, steps, notes, log, task.reason, decided
            )
        if task is not None and task.status is TaskStatus.OPEN:
            log.append(entry)
            return Walk(match, tuple(actions), steps, waiting=True, log=tuple(log))
        if self.book is None:
            # Outside processing (a person moved the document into the rule's space) nothing
            # waits for an answer: the rule ends here, its steps before count.
            log.append(entry | {"status": NOT_ASKED})
            return Walk(match, tuple(actions), steps, log=tuple(log))
        refused = await self._refused(rule, step)
        if refused is not None:
            log.append(entry | {"reason": refused.to_json()})
            return self._without_answer(
                match, step, actions, steps, notes, log, refused, decided, refused=True
            )
        webhook = await self.uow.webhooks.get(step.webhook_id)
        state = await self._after(match, actions, steps)
        request = TaskRequest(
            document=await document_json(self.uow, state, self.link_base),
            values=await webhook_values(self.uow, state, self.link_base),
            rule={"id": str(rule.id), "name": rule.definition.name},
            steps=dict(steps),
        )
        ask = Ask(
            kind=TaskKind.ASK,
            step=task_step(rule, step),
            webhook=webhook,
            timeout=step.timeout,
            request=request,
            task=task,
        )
        log.append(entry | {"status": "asking"})
        return Walk(match, tuple(actions), steps, ask=ask, log=tuple(log))

    def _without_answer(
        self,
        match: Match,
        step: AskWebhook,
        actions: list[Action],
        steps: dict[str, JsonValue],
        notes: list[Reason],
        log: list[JsonObject],
        reason: Reason,
        decided: bool,
        *,
        refused: bool = False,
    ) -> Walk | None:
        """No answer: as the step says (`Missing`); a webhook the rule may not ask through
        holds the document for a person. After a person decided in the run, it is only
        reported (`notes`), and the rule goes on."""
        missing = Missing.YELLOW if refused else step.missing
        if decided:
            notes.append(reason)
            log[-1] = log[-1] | {"reported": True}
            return None
        if missing is Missing.CONTINUE:
            return None
        if missing is Missing.YELLOW:
            return Walk(match, tuple(actions), steps, review=reason, log=tuple(log))
        return Walk(match, tuple(actions), steps, failure=reason, log=tuple(log))

    async def _refused(self, rule: Rule, step: AskWebhook) -> Reason | None:
        """Why the rule may not ask through the step's webhook now: it is gone, no longer its
        author's, or its owner may not read the document."""
        webhook = await self.uow.webhooks.find(step.webhook_id)
        owner = None if webhook is None else await self.uow.users.find(webhook.owner_id)
        if owner is None or not owner.active or owner.id != rule.current.created_by:
            return because(ReasonCode.RULE_WEBHOOK_GONE, rule=rule.definition.name)
        space = await self.uow.spaces.find(self.document.space_id)
        if space is None or not in_reach(owner, self.document, space):
            return because(ReasonCode.RULE_WEBHOOK_UNREADABLE, rule=rule.definition.name)
        return None

    async def _after(
        self, match: Match, actions: Sequence[Action], steps: Mapping[str, JsonValue]
    ) -> Document:
        """The document as the rule's actions so far leave it, alone (a copy)."""
        state = copy.deepcopy(self.document)
        if not actions:
            return state
        alone = plan(
            [match],
            replace(
                self.context,
                actions={match.rule.id: tuple(actions)},
                steps={match.rule.id: _template_steps(steps)},
            ),
        )
        with contextlib.suppress(ValidationError):  # actions that do not fit change nothing
            state.apply_changes(alone.changes, self.definitions, self.now)
        if alone.space is not None:
            state.space_id = alone.space
        state.pull_events()
        return state

    async def _facts(self, rule: Rule, state: Document, steps: Mapping[str, JsonValue]) -> Facts:
        patterns, _ = await field_patterns(self.matcher, [rule], state, self.context.kept_facts)
        return Facts.of(
            state,
            kept_facts=self.context.kept_facts,
            text=self.prepared.text,
            patterns={**self.prepared.patterns, **patterns},
            unverified=self.origin.unverified,
            unverified_tags=self.origin.model_tags,
            taxonomy=self.context.taxonomy,
            steps=steps,
        )


def task_step(rule: Rule, step: AskWebhook) -> TaskStep:
    return TaskStep(rule.id, rule.current.number, rule.definition.name, step.name)


def template_steps(walks: Sequence[Walk]) -> dict[RuleId, Mapping[str, TemplateValue]]:
    """What each rule's templates see as `steps`, by rule."""
    return {walk.rule.id: _template_steps(walk.steps) for walk in walks if walk.steps}


def _template_steps(steps: Mapping[str, JsonValue]) -> dict[str, TemplateValue]:
    return {
        name: value for name, answer in steps.items() if (value := json_value(answer)) is not None
    }


def _answer_log(answer: JsonValue) -> JsonObject:
    if len(json.dumps(answer, ensure_ascii=False)) > MAX_LOGGED_ANSWER:
        return {"answer_too_long": True}
    return {"answer": answer}


def _is_action(step: object) -> bool:
    return not isinstance(step, AskWebhook | StepCondition)


# --- one run ------------------------------------------------------------------------------------


async def run_rules(
    uow: UnitOfWork,
    matcher: PatternMatcher,
    templates: TemplateRenderer,
    *,
    mode: Mode,
    document: Document,
    rules: Sequence[Rule],
    prepared: Prepared,
    origin: Provenance,
    definitions: Mapping[FieldId, FieldDefinition],
    before: tuple[Document, Mapping[PatternKey, bool]] | None = None,
    locked: Collection[str] = (),
    accept_conflicts: bool = False,
    applier: UserId | None = None,
    book: TaskBook | None = None,
    link_base: str | None = None,
    now: datetime | None = None,
) -> RuleRun:
    """Evaluate `rules` on the document, walk the steps of those that match and plan their
    change (nothing is applied). `before`: for a change, the state before it and its field
    pattern results; only rules that become true with the change act. `applier`: who applies
    the rules to existing documents. `book`: what the tasks of the node's run brought, on
    arrival; without it, no step asks (`link_base`: where consumers answer)."""
    kept = tuple(await uow.document_facts.of_document(document.id))
    patterns, problems = await field_patterns(matcher, rules, document, kept)
    loaded = await taxonomy(uow, [document, *([] if before is None else [before[0]])], rules)
    now_facts = facts(document, prepared, patterns, origin, loaded.taxonomy, kept)
    before_facts = None
    if before is not None:
        before_facts = facts(before[0], prepared, before[1], origin, loaded.taxonomy, kept)
    matched = matches(rules, now_facts, definitions, before=before_facts)
    context = await situation(
        uow,
        mode=mode,
        document=document,
        rules=[match.rule for match in matched],
        definitions=definitions,
        origin=origin,
        templates=templates,
        locked=locked,
        person_added_tags=origin.tags_added,
        person_removed_tags=origin.tags_removed,
        accept_conflicts=accept_conflicts,
        loaded=loaded,
        applier=applier,
        kept_facts=kept,
        codes=prepared.codes,
    )
    walker = Walker(
        uow,
        matcher,
        document,
        context,
        prepared,
        origin,
        definitions,
        book,
        link_base,
        now or document.updated_at,
    )
    walks = [await walker.walk(match) for match in matched]
    acting = [walk for walk in walks if walk.failure is None]
    context = replace(
        context,
        actions={walk.rule.id: walk.actions for walk in acting if walk.ended_early},
        steps=template_steps(acting),
    )
    sends = tuple(
        Send(
            rule_id=walk.rule.id,
            version=walk.rule.current.number,
            name=walk.rule.definition.name,
            author=walk.rule.current.created_by,
            webhook_id=action.webhook_id,
        )
        for walk in acting
        for action in walk.actions
        if isinstance(action, SendWebhook)
    )
    return RuleRun(
        plan([walk.match for walk in acting], context),
        prepared.problems + problems,
        sends,
        asks=tuple(walk.ask for walk in walks if walk.ask is not None),
        waiting=any(walk.waiting for walk in walks),
        reviews=tuple(walk.review for walk in walks if walk.review is not None),
        failures=tuple(walk.failure for walk in walks if walk.failure is not None),
        notes=tuple(note for walk in walks for note in walk.notes),
        steps=tuple(
            {"rule_id": str(walk.rule.id), "steps": list[JsonValue](walk.log)}
            for walk in walks
            if walk.log
        ),
    )
