"""The pipeline nodes `apply_rules` and `file`."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from lekto.core.domain.classification import CHECKS, FieldCheck, field_key
from lekto.core.domain.documents import Document
from lekto.core.domain.fields import FieldDefinition
from lekto.core.domain.ids import FieldId, SpaceId
from lekto.core.domain.json_value import JsonObject, JsonValue, as_list
from lekto.core.domain.pipeline import RULES, TRIGGER, NodeResult, Outcome
from lekto.core.domain.rule_planner import Mode
from lekto.core.domain.rules import Rule, Trigger
from lekto.core.domain.sorting import sort_key
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.patterns import PatternMatcher
from lekto.core.ports.templates import TemplateRenderer
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import field_definitions, space_label
from lekto.core.services.rules.running import (
    Prepared,
    active_rules,
    apply_plan,
    back_and_forth,
    checked_rules,
    prepare,
    provenance,
    reachable_rules,
    run_rules,
    space_rules,
)


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
    has no value after the rules (issue #52)."""

    def __init__(
        self,
        uow: UnitOfWorkFactory,
        store: ObjectStore,
        matcher: PatternMatcher,
        templates: TemplateRenderer,
        *,
        max_text: int,
    ) -> None:
        self._uow = uow
        self._store = store
        self._matcher = matcher
        self._templates = templates
        self._max_text = max_text

    async def run(self, document: Document) -> "RulesResult":
        async with self._uow() as uow:
            rules = await reachable_rules(
                uow, document.space_id, Trigger.INGEST, include_global=True
            )
        prepared = await prepare(
            self._store, self._matcher, rules, document, max_text=self._max_text
        )
        return RulesResult(prepared, self._matcher, self._templates)


@dataclass(frozen=True)
class RulesResult:
    prepared: Prepared
    matcher: PatternMatcher
    templates: TemplateRenderer

    async def apply(self, uow: UnitOfWork, document: Document, now: datetime) -> NodeResult:
        definitions = await field_definitions(uow)
        visited = [document.space_id]
        looked: list[Rule] = []
        output: JsonObject = {}
        reasons: list[str] = []
        while True:
            # The first space with the global rules, every one it enters with its own.
            rules = (
                await active_rules(uow, document.space_id, Trigger.INGEST)
                if len(visited) == 1
                else await space_rules(uow, document.space_id, Trigger.INGEST)
            )
            looked += rules
            if not rules:
                break
            origin = provenance(await uow.processing_log.list_for(document.id), document)
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
            )
            output = _merged(output, run.output())
            reasons += run.plan.reasons
            target = run.plan.space
            if target is not None and target != document.space_id and target in visited:
                reasons.append(back_and_forth(await _names(uow, [*visited, target])))
                problem = await apply_plan(
                    uow, document, replace(run.plan, space=None), definitions, now
                )
                reasons += [problem] if problem else []
                break
            problem = await apply_plan(uow, document, run.plan, definitions, now)
            reasons += [problem] if problem else []
            if document.space_id == visited[-1]:
                break
            visited.append(document.space_id)
        input: dict[str, JsonValue] = {
            TRIGGER: Trigger.INGEST.value,
            "rules": checked_rules(looked),
        }
        if len(visited) > 1:
            output["spaces"] = [str(space) for space in visited]
        if reasons:
            result = NodeResult(
                outcome=Outcome.UNCERTAIN,
                reason="; ".join(reasons),
                model_version=RULES,
                input=input,
                output=output,
            )
        else:
            result = NodeResult(outcome=Outcome.OK, model_version=RULES, input=input, output=output)
        return _waiting_for_hand(document, definitions, result)


def _merged(output: JsonObject, more: JsonObject) -> JsonObject:
    """The output of the rule runs of a chain: their reports, checks and reviews one after the
    other (one run: its own output)."""
    if not output:
        return more
    merged: JsonObject = dict(output)
    for key in ("rules", CHECKS, "reviews", "problems"):
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
            reason=f"'{definition.name}' is set by hand and has no value yet",
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
    reasons = [*([result.reason] if result.reason else []), *(c.reason or "" for c in waiting)]
    return replace(result, outcome=Outcome.UNCERTAIN, reason="; ".join(reasons), output=output)


class FileNode:
    """Files the document into its space. Rights hang on the space; whoever put the document
    there (an upload, a person, a rule) was allowed to, so filing always succeeds."""

    async def run(self, document: Document) -> "FileResult":
        return FileResult()


@dataclass(frozen=True)
class FileResult:
    async def apply(self, uow: UnitOfWork, document: Document, now: datetime) -> NodeResult:
        return NodeResult(outcome=Outcome.OK)
