"""The pipeline nodes `apply_rules` and `file`."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from lekto.core.domain.classification import CHECKS, FieldCheck, field_key
from lekto.core.domain.documents import Document
from lekto.core.domain.fields import FieldDefinition
from lekto.core.domain.ids import FieldId
from lekto.core.domain.json_value import JsonValue, as_list
from lekto.core.domain.pipeline import RULES, TRIGGER, NodeResult, Outcome
from lekto.core.domain.rule_planner import Mode
from lekto.core.domain.rules import Trigger
from lekto.core.domain.sorting import sort_key
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.patterns import PatternMatcher
from lekto.core.ports.templates import TemplateRenderer
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import field_definitions
from lekto.core.services.rules.running import (
    Prepared,
    active_rules,
    apply_plan,
    checked_rules,
    prepare,
    provenance,
    run_rules,
)


class ApplyRulesNode:
    """Runs the rules with trigger `ingest`: the global ones and those of the document's space.

    The text is loaded and its patterns run here, outside any transaction; the rules are
    evaluated and applied when the result is stored, on the state that is stored. Conflicts,
    refused actions and forced reviews make the node uncertain: the document waits in the
    inbox before it is filed. So does a required field set by hand that has no value after the
    rules (issue #52)."""

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
            rules = await active_rules(uow, document.space_id, Trigger.INGEST)
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
        rules = await active_rules(uow, document.space_id, Trigger.INGEST)
        input: dict[str, JsonValue] = {
            TRIGGER: Trigger.INGEST.value,
            "rules": checked_rules(rules),
        }
        definitions = await field_definitions(uow)
        if not rules:
            ok = NodeResult(outcome=Outcome.OK, model_version=RULES, input=input)
            return _waiting_for_hand(document, definitions, ok)
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
        output = run.output()
        problem = await apply_plan(uow, document, run.plan, definitions, now)
        reasons = run.plan.reasons + ([problem] if problem else [])
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
