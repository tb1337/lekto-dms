"""The inbox: what is open in a yellow or red document, and how its owner's decision on the open
fields turns into a metadata change.

What the model proposed and how each field was checked lies in the processing log (output of
the classify and extract steps). These functions read it from there; the rules (M7) use
`field_checks` for the proposals of the latest model run.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any
from uuid import UUID

from papiq.core.domain.classification import (
    CONTACT,
    DOCUMENT_DATE,
    DOCUMENT_TYPE,
    TAGS,
    FieldCheck,
    checks_from_json,
    field_from_json,
    field_id_of,
)
from papiq.core.domain.documents import Document, DocumentChanges, Unset
from papiq.core.domain.errors import OpenFieldsError, ValidationError
from papiq.core.domain.fields import FieldDefinition
from papiq.core.domain.ids import ContactId, DocumentTypeId, FieldId, TagId
from papiq.core.domain.json_value import JsonObject, JsonValue
from papiq.core.domain.pipeline import (
    OUTSIDE_PIPELINE,
    PERSON,
    PIPELINE,
    Outcome,
    Step,
    StepResult,
    StepRun,
)

ALWAYS_SET = frozenset({"drawer", "title", "review"})
"""Open fields of the rules that always have a value: confirming keeps it."""

MODEL_STEPS = (Step.CLASSIFY, Step.EXTRACT_FIELDS)


@dataclass(frozen=True)
class OpenStep:
    """A step whose result is uncertain or failed: why, and the fields its owner has to decide
    (uncertain fields of classification or field extraction; none for other steps)."""

    step: Step
    outcome: Outcome
    reason: str | None
    fields: tuple[FieldCheck, ...] = ()


@dataclass(frozen=True)
class StepReview:
    """The latest run of a model step: what was sent, what came back and how it was checked."""

    step: Step
    run: int
    outcome: Outcome
    reason: str | None
    model_version: str | None
    truncated: bool | None
    fields: tuple[FieldCheck, ...]


@dataclass(frozen=True)
class InboxItem:
    document: Document
    open: tuple[OpenStep, ...]


@dataclass(frozen=True)
class Review:
    document: Document
    open: tuple[OpenStep, ...]
    steps: tuple[StepReview, ...]


@dataclass(frozen=True)
class Decision:
    """The owner's decision on the open fields: the change to apply, and which fields were
    accepted as suggested, entered by the owner, or kept with the value the document has, by
    step."""

    changes: DocumentChanges
    accepted: Mapping[Step, tuple[str, ...]]
    entered: Mapping[Step, tuple[str, ...]]
    kept: Mapping[Step, tuple[str, ...]]


def latest_entries(log: Sequence[StepRun], *, by_model: bool = False) -> dict[Step, StepRun]:
    """The latest log entry of each step written by processing; with `by_model`, leaving out
    confirmations too."""
    latest: dict[Step, StepRun] = {}
    for entry in log:
        if entry.result.model_version in OUTSIDE_PIPELINE:
            continue
        if by_model and entry.result.model_version == PERSON:
            continue
        latest[entry.step] = entry
    return latest


def field_checks(log: Sequence[StepRun]) -> dict[str, FieldCheck]:
    """The field checks of the latest classification and field extraction, by field."""
    latest = latest_entries(log, by_model=True)
    checks: dict[str, FieldCheck] = {}
    for step in MODEL_STEPS:
        if step in latest:
            checks.update((check.field, check) for check in _checks(latest[step].result))
    return checks


def open_steps(document: Document, log: Sequence[StepRun]) -> tuple[OpenStep, ...]:
    """The uncertain and failed steps of the document's current state, in pipeline order."""
    latest = latest_entries(log)
    result = []
    for step in PIPELINE:
        outcome = document.processing.outcomes.get(step)
        if outcome not in (Outcome.UNCERTAIN, Outcome.FAILED):
            continue
        entry = latest.get(step)
        reason = entry.result.reason if entry is not None else None
        fields: tuple[FieldCheck, ...] = ()
        if entry is not None and outcome is Outcome.UNCERTAIN:
            fields = tuple(check for check in _checks(entry.result) if not check.ok)
        result.append(OpenStep(step, outcome, reason, fields))
    return tuple(result)


def step_reviews(log: Sequence[StepRun]) -> tuple[StepReview, ...]:
    latest = latest_entries(log, by_model=True)
    reviews = []
    for step in MODEL_STEPS:
        entry = latest.get(step)
        if entry is None:
            continue
        truncated = entry.result.input.get("truncated")
        reviews.append(
            StepReview(
                step=step,
                run=entry.run,
                outcome=entry.result.outcome,
                reason=entry.result.reason,
                model_version=entry.result.model_version,
                truncated=truncated if isinstance(truncated, bool) else None,
                fields=tuple(_checks(entry.result)),
            )
        )
    return tuple(reviews)


def decide(
    open: Sequence[OpenStep],
    document: Document,
    changes: DocumentChanges,
    *,
    accept_suggestions: bool,
    definitions: Mapping[FieldId, FieldDefinition],
    given: Collection[str] = (),
) -> Decision:
    """Every open field needs a decision: a value (or None) in `changes` (or named in `given`,
    such as the drawer), a value the document has (its owner set it meanwhile; it is kept), or,
    with `accept_suggestions`, a suggestion that can be taken as it is. Suggestions never
    replace a value. OpenFieldsError lists the fields without a decision. Fields whose definition
    no longer exists need none. The rules' drawer, title and review always have a value:
    confirming keeps them."""
    accepted: dict[Step, list[str]] = {}
    entered: dict[Step, list[str]] = {}
    kept: dict[Step, list[str]] = {}
    suggested: dict[str, Any] = {}
    fields = dict(changes.fields)
    undecided: list[str] = []
    for item in open:
        for check in item.fields:
            field_id = _field_id(check.field)
            if field_id is not None and field_id not in definitions:
                continue
            if check.field in given or _given(changes, check.field, field_id):
                entered.setdefault(item.step, []).append(check.field)
            elif _has_value(document, check.field, field_id):
                kept.setdefault(item.step, []).append(check.field)
            elif accept_suggestions and check.suggestion is not None:
                value = _suggested(check, field_id, definitions)
                if field_id is not None:
                    fields[field_id] = value
                else:
                    suggested[check.field] = value
                accepted.setdefault(item.step, []).append(check.field)
            else:
                undecided.append(_label(check.field, field_id, definitions))
    if undecided:
        raise OpenFieldsError(tuple(undecided))
    combined = replace(
        changes,
        fields=fields,
        **{_CHANGE_FIELDS[name]: value for name, value in suggested.items()},
    )
    return Decision(
        changes=combined,
        accepted={step: tuple(fields) for step, fields in accepted.items()},
        entered={step: tuple(fields) for step, fields in entered.items()},
        kept={step: tuple(fields) for step, fields in kept.items()},
    )


LEARNED_ALIAS = "learned_alias"
"""Key of the alias a confirmation taught a contact, in the output of its `apply_rules` entry."""
_LONGEST_ALIAS = 100  # characters; longer proposals are not learned


def alias_to_learn(
    open: Sequence[OpenStep], decision: Decision, document: Document
) -> tuple[ContactId, str] | None:
    """The contact the owner chose for an open contact field, and the name the model read for
    it: the owner entered the contact or accepted the suggestion. None if the field was not
    open, the model read no name, or the document has no contact."""
    for item in open:
        if item.step is not Step.CLASSIFY:
            continue
        decided = (*decision.entered.get(item.step, ()), *decision.accepted.get(item.step, ()))
        for check in item.fields:
            if check.field != CONTACT or CONTACT not in decided:
                continue
            proposed = check.proposed
            if (
                isinstance(proposed, str)
                and proposed.strip()
                and len(proposed) <= _LONGEST_ALIAS
                and document.contact_id is not None
            ):
                return document.contact_id, proposed.strip()
    return None


def confirmation(
    step: Step, before: Outcome | None, decision: Decision, confirmed_by: UUID
) -> StepResult:
    """The log entry's result for a step the owner confirmed."""
    output: JsonObject = {
        "confirmed_by": str(confirmed_by),
        "outcome_before": None if before is None else before.value,
        "accepted": list(decision.accepted.get(step, ())),
        "entered": list(decision.entered.get(step, ())),
        "kept": list(decision.kept.get(step, ())),
    }
    return StepResult(outcome=Outcome.OK, model_version=PERSON, output=output)


_CHANGE_FIELDS = {
    CONTACT: "contact_id",
    DOCUMENT_TYPE: "document_type_id",
    TAGS: "tag_ids",
    DOCUMENT_DATE: "document_date",
    "title": "title",
}


def _checks(result: StepResult) -> list[FieldCheck]:
    try:
        return checks_from_json(result.output.get("fields"))
    except ValidationError:
        return []


def _field_id(field: str) -> FieldId | None:
    id = field_id_of(field)
    if id is None:
        return None
    try:
        return FieldId(UUID(id))
    except ValueError:
        return None


def _given(changes: DocumentChanges, field: str, field_id: FieldId | None) -> bool:
    if field_id is not None:
        return field_id in changes.fields
    name = _CHANGE_FIELDS.get(field)
    return name is not None and not isinstance(getattr(changes, name), Unset)


def _has_value(document: Document, field: str, field_id: FieldId | None) -> bool:
    if field in ALWAYS_SET:
        return True
    if field_id is not None:
        return field_id in document.fields
    name = _CHANGE_FIELDS.get(field)
    return name is not None and getattr(document, name) not in (None, set())


def _suggested(
    check: FieldCheck,
    field_id: FieldId | None,
    definitions: Mapping[FieldId, FieldDefinition],
) -> object:
    value: JsonValue = check.suggestion
    try:
        if field_id is not None:
            return field_from_json(definitions[field_id], value)
        match check.field:
            case "contact":
                return ContactId(UUID(str(value)))
            case "document_type":
                return DocumentTypeId(UUID(str(value)))
            case "tags" if isinstance(value, list):
                return frozenset(TagId(UUID(str(item))) for item in value)
            case "document_date":
                return date.fromisoformat(str(value))
    except ValueError:
        pass
    raise ValidationError(f"the suggestion for {check.field} cannot be taken: {value!r}")


def _label(
    field: str,
    field_id: FieldId | None,
    definitions: Mapping[FieldId, FieldDefinition],
) -> str:
    if field_id is None:
        return field
    return f"{field} ({definitions[field_id].name})"
