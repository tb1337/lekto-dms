"""Rules with trigger `change`: when a person changes a document's metadata.

- Only on documents whose processing is complete; while processing runs (or waits in the
  inbox), the node `apply_rules` sees the change anyway.
- Edge, not state: a rule acts only if it holds after the change and did not hold before. A
  title change does not apply every rule again, and a new rule does not act silently on old
  documents.
- The person wins: fields they set in this change, or decided before in this processing run,
  are not changed by a rule (the rule is logged as overruled).
- Nothing turns yellow: conflicts, refused actions and forced reviews change nothing and are
  only reported (a filed document would disappear for everyone else).
- The change, the rules' change, the events and the log entry are stored together. The log
  entry also records what the person changed, for later rule runs.

A completed document that enters a space outside processing (a person moves or hands it over,
change rules or a rule applied to existing documents file it) runs that space's own rules with
trigger `ingest` the same way (`after_arrival`): as on arrival, but nothing turns yellow. Each
space at most once in the chain; a person's move fixes the space (the rules leave it). Values
rules set on unconfirmed values stay unconfirmed along the chain (`running.Chain`). It returns
the steps (`ArrivalStep`), which the preview of applying a rule shows.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from lekto.core.domain.classification import SPACE, TAGS, TITLE
from lekto.core.domain.document_facts import DocumentFact
from lekto.core.domain.documents import Document, DocumentChanges
from lekto.core.domain.fields import FieldDefinition
from lekto.core.domain.ids import FieldId, SpaceId
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.pipeline import (
    ACTOR,
    RULES_CHANGE,
    TRIGGER,
    TRIGGER_MOVE,
    Node,
    NodeRun,
    ProcessingStatus,
)
from lekto.core.domain.reasons import Reason
from lekto.core.domain.rule_planner import Mode, RuleReport, changed_fields
from lekto.core.domain.rules import Rule, SetSpace, Trigger
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import User
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.patterns import PatternMatcher
from lekto.core.ports.templates import TemplateRenderer
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.services._access import space_label
from lekto.core.services.rules.running import (
    Chain,
    Prepared,
    RuleRun,
    active_rules,
    apply_plan,
    back_and_forth,
    checked_rules,
    corrected_fields,
    entry_beside,
    field_patterns,
    person_record,
    prepare,
    problem_output,
    provenance,
    reachable_rules,
    send_now,
    space_choice,
    space_rules,
)
from lekto.core.services.rules.steps import run_rules


@dataclass(frozen=True)
class ArrivalStep:
    """What the rules of one space did to a document that entered it (`after_arrival`): each
    rule that holds (`reports`), the space they filed it into (`moved_to`), a space they would
    file it into again (`looped_to`: the chain stops there), and why their change did not
    apply (`problem`)."""

    space_id: SpaceId
    reports: tuple[RuleReport, ...]
    moved_to: SpaceId | None
    looped_to: SpaceId | None
    problem: Reason | None


class ChangeRules:
    """Runs the change rules for `DocumentService`."""

    def __init__(
        self,
        store: ObjectStore,
        matcher: PatternMatcher,
        templates: TemplateRenderer,
        *,
        max_text: int,
        pipeline_version: str,
    ) -> None:
        self._store = store
        self._matcher = matcher
        self._templates = templates
        self._max_text = max_text
        self._version = pipeline_version

    async def rules(self, uow: UnitOfWork, document: Document) -> list[Rule]:
        """The rules a change of `document` may set off."""
        if document.processing.status is not ProcessingStatus.COMPLETED:
            return []
        return await active_rules(uow, document.space_id, Trigger.CHANGE)

    async def followers(self, uow: UnitOfWork, rules: Sequence[Rule]) -> list[Rule]:
        """The rules of the spaces `rules` may file a document into, and of the spaces those
        file it into (trigger `ingest`, `after_arrival`): prepared together with them."""
        found: dict[object, Rule] = {}
        for target in {
            action.space_id
            for rule in rules
            for action in rule.definition.actions
            if isinstance(action, SetSpace)
        }:
            for rule in await reachable_rules(uow, target, Trigger.INGEST, include_global=False):
                found.setdefault(rule.id, rule)
        return list(found.values())

    async def prepare(self, rules: Sequence[Rule], document: Document) -> Prepared:
        """Outside a transaction: the text and its patterns, if a rule needs them."""
        return await prepare(self._store, self._matcher, rules, document, max_text=self._max_text)

    async def arrival_rules(self, uow: UnitOfWork, document: Document, space: Space) -> list[Rule]:
        """The rules `document` may meet when it enters `space` (see `after_arrival`): none
        while its processing is not complete (the node `apply_rules` runs them then)."""
        if document.processing.status is not ProcessingStatus.COMPLETED:
            return []
        return await reachable_rules(uow, space.id, Trigger.INGEST, include_global=False)

    async def after_arrival(
        self,
        uow: UnitOfWork,
        *,
        document: Document,
        source: Space,
        prepared: Prepared,
        definitions: Mapping[FieldId, FieldDefinition],
        now: datetime,
        by_person: bool,
        applier: User | None = None,
        chain: Chain | None = None,
    ) -> list[ArrivalStep]:
        """After `document` was moved out of `source` into the space it lies in now: run the
        rules of that space (its own, trigger `ingest`) in the manner of change rules, and of
        every space they file it into, each at most once; one log entry per space. `by_person`:
        a person chose the space, the rules leave it. `chain`: what the rules that moved it
        carry on (`running.Chain`). Returns what the rules of each space did, in order (spaces
        where no rule holds are left out)."""
        steps: list[ArrivalStep] = []
        if document.processing.status is not ProcessingStatus.COMPLETED:
            return steps
        visited = [source.id]
        chain = Chain() if chain is None else chain
        while True:
            here = document.space_id
            visited.append(here)
            rules = await space_rules(uow, here, Trigger.INGEST)
            if not rules:
                return steps
            origin = chain.origin(
                provenance(await uow.processing_log.list_for(document.id), document)
            )
            locked = origin.person | ({SPACE} if by_person else set())
            run = await run_rules(
                uow,
                self._matcher,
                self._templates,
                mode=Mode.CHANGE,
                document=document,
                rules=rules,
                prepared=prepared,
                origin=origin,
                definitions=definitions,
                locked=locked,
                applier=None if applier is None else applier.id,
            )
            output: dict[str, JsonValue] = run.output()
            target = run.plan.space
            looping = target is not None and target != here and target in visited
            plan = replace(run.plan, space=None) if looping else run.plan
            problem = await apply_plan(uow, document, plan, definitions, now)
            output |= await send_now(uow, run.sends, document, now)
            chain.record(plan, document)
            if looping:
                assert target is not None
                problem = back_and_forth(await self._names(uow, [*visited, target]))
            if problem is not None:
                output |= problem_output(problem)
            await uow.processing_log.append(
                entry_beside(
                    document,
                    node=Node.APPLY_RULES,
                    model_version=RULES_CHANGE,
                    input={
                        TRIGGER: Trigger.INGEST.value,
                        "space_id": str(here),
                        "rules": checked_rules(rules),
                        **({} if applier is None else {ACTOR: str(applier.id)}),
                    },
                    output=output,
                    version=self._version,
                    now=now,
                )
            )
            moved_to = None if document.space_id == here else document.space_id
            if run.plan.reports or problem is not None or moved_to is not None:
                steps.append(
                    ArrivalStep(
                        space_id=here,
                        reports=tuple(run.plan.reports),
                        moved_to=moved_to,
                        looped_to=target if looping else None,
                        problem=problem,
                    )
                )
            if looping or moved_to is None:
                return steps

    async def _names(self, uow: UnitOfWork, spaces: Sequence[SpaceId]) -> list[str]:
        users = {user.id: user for user in await uow.users.list_all()}
        names = []
        for id in spaces:
            space = await uow.spaces.find(id)
            names.append(str(id) if space is None else space_label(space, users))
        return names

    def space_chosen(self, document: Document, *, actor: User, now: datetime) -> NodeRun:
        """The log entry of a person moving the document: rules leave the space then."""
        return space_choice(
            document,
            node=Node.APPLY_RULES,
            actor=actor.id,
            trigger=TRIGGER_MOVE,
            version=self._version,
            now=now,
        )

    async def after_change(
        self,
        uow: UnitOfWork,
        *,
        actor: User,
        before: Document,
        document: Document,
        changes: DocumentChanges,
        prepared: Prepared,
        definitions: Mapping[FieldId, FieldDefinition],
        now: datetime,
        log: bool = True,
        kept_before: Sequence[DocumentFact] | None = None,
    ) -> RuleRun | None:
        """After the person's change is applied to `document`: run the rules, apply their
        change and (with `log`) write the log entry. Returns the run, if rules were
        evaluated. `changes`: the person's change as given, before `checked_changes` (a topic
        it clears because the new contact does not enable it is no decision of theirs).
        `kept_before`: the facts before a person's decision about one (`fact_decisions`); the
        change is then to the facts, the document's values stay."""
        changed = changed_fields(changes)
        record = person_record(
            changed=changed,
            tags_before=before.tag_ids,
            tags_after=document.tag_ids,
            corrected=corrected_fields(before, document, decided=changed),
        )
        input: dict[str, JsonValue] = {
            TRIGGER: Trigger.CHANGE.value,
            ACTOR: str(actor.id),
            **record,
        }
        rules = await self.rules(uow, document)
        run: RuleRun | None = None
        output: dict[str, JsonValue] = {}
        if rules:
            origin = provenance(await uow.processing_log.list_for(document.id), document)
            origin = replace(
                origin,
                person=origin.person | changed,
                model_values={
                    name: value
                    for name, value in origin.model_values.items()
                    if name not in changed
                },
                model_tags=frozenset() if TAGS in changed else origin.model_tags,
                machine_title=None if TITLE in changed else origin.machine_title,
                tags_added=(origin.tags_added & document.tag_ids)
                | (document.tag_ids - before.tag_ids),
                tags_removed=(origin.tags_removed - document.tag_ids)
                | (before.tag_ids - document.tag_ids),
            )
            # The facts stay as they are, unless the person decided one.
            kept = await uow.document_facts.of_document(document.id)
            earlier = kept if kept_before is None else kept_before
            before_patterns, _ = await field_patterns(self._matcher, rules, before, earlier)
            run = await run_rules(
                uow,
                self._matcher,
                self._templates,
                mode=Mode.CHANGE,
                document=document,
                rules=rules,
                prepared=prepared,
                origin=origin,
                definitions=definitions,
                before=(before, before_patterns),
                kept_before=kept_before,
                locked=origin.person,
            )
            input["rules"] = checked_rules(rules)
            output = run.output()
            unfit = await apply_plan(uow, document, run.plan, definitions, now)
            if unfit is not None:
                output |= problem_output(unfit)
            else:
                output |= await send_now(uow, run.sends, document, now)
        if log:
            await uow.processing_log.append(
                entry_beside(
                    document,
                    node=Node.APPLY_RULES,
                    model_version=RULES_CHANGE,
                    input=input,
                    output=output,
                    version=self._version,
                    now=now,
                )
            )
        if run is not None and document.space_id != before.space_id:
            # The change rules filed it into another space: that space's rules run on it.
            chain = Chain()
            chain.record(run.plan, document)
            await self.after_arrival(
                uow,
                document=document,
                source=await uow.spaces.get(before.space_id),
                prepared=prepared,
                definitions=definitions,
                now=now,
                by_person=False,
                chain=chain,
            )
        return run
