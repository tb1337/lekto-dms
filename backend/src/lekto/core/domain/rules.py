"""Rules: data that tags, files and checks documents.

A rule has a scope, triggers, a tree of conditions and actions:

- Scope: a global rule is made by an admin and acts on every document. A space rule belongs
  to a space, is made by its editors and acts on the documents in that space. Both have all
  actions; a rule files only into spaces whoever saved it last may file into, or hands a
  document over into another user's personal space (`rule_planner`).
- Triggers: a document arriving (`ingest`, the pipeline node `apply_rules`) and a document being
  changed by a person (`change`).
- Conditions: groups of `all` (and) or `any` (or), each may be negated; a condition is field,
  operator and value.
- Actions: set space, contact, type, topic, title or a field, add or remove tags, force a
  review, send a webhook (a notification through a webhook of whoever saved the rule).
- Steps (Tobi, 25.10.2026, `webhooks-und-auftraege.md`): the actions are an ordered, linear
  sequence that may hold two more kinds: asking a webhook (`AskWebhook`, a task whose answer
  the steps after it see as `steps.<name>`) and a condition (`StepCondition`: if it does not
  hold, the rule ends there; the steps before it count). Each rule works on its own copy of the
  document and sees what its own steps before set; the rules are combined at the end.

The definition (name, priority, triggers, conditions, actions) is versioned: every change makes
a new version; old versions stay readable so the processing log can refer to them. Enabling and
disabling are state, not content, and make no version.

Definitions are stored as JSON (`rules_json`). Values in conditions and actions keep their
JSON form (field values as `field_to_json` writes them) and are read with the field
definitions where needed (`check_fields`).
"""

import math
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from lekto.core.domain.classification import field_key
from lekto.core.domain.documents import Channel
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import (
    FieldDefinition,
    FieldType,
    FieldValue,
    Writing,
    field_from_json,
    read_written,
)
from lekto.core.domain.ids import (
    ContactId,
    DocumentId,
    DocumentTypeId,
    FieldId,
    RuleApplicationId,
    RuleId,
    SpaceId,
    TagId,
    UserId,
    WebhookId,
    new_id,
)
from lekto.core.domain.json_value import JsonValue, require_date, require_uuid
from lekto.core.domain.master_data import DocumentType, TagScope
from lekto.core.domain.reasons import Reason
from lekto.core.domain.tasks import DEFAULT_TIMEOUT, validate_timeout
from lekto.core.domain.validation import require_name, require_utc

DEFAULT_PRIORITY = 100
MIN_PRIORITY = 0
MAX_PRIORITY = 1000
MAX_DEPTH = 5
MAX_CONDITIONS = 50
MAX_ACTIONS = 20
MAX_TEXT = 500
MAX_PATTERN = 200
MAX_LIST = 100


class RuleScope(StrEnum):
    GLOBAL = "global"
    SPACE = "space"


class Trigger(StrEnum):
    INGEST = "ingest"  # the pipeline node `apply_rules`
    CHANGE = "change"  # a person changed the document's metadata


class ConditionField(StrEnum):
    STEP = "step"  # what an earlier step brought (`steps.<path>`), in a condition step only
    CONTACT = "contact"
    CONTACT_GROUP = "contact_group"  # the groups of the document's contact
    DOCUMENT_TYPE = "document_type"
    DOCUMENT_TYPE_GROUP = "document_type_group"  # the groups of the document's type
    TOPIC = "topic"  # the document's topic: a topic given matches the ones below it too
    TAGS = "tags"
    CHANNEL = "channel"
    TEXT = "text"
    FIELD = "field"
    DOCUMENT_DATE = "document_date"


class Operator(StrEnum):
    IS = "is"  # for a topic: it, or one below it
    IN = "in"  # is one of; for tags, groups and topics: has one of (or one below it)
    CONTAINS = "contains"  # for tags and groups: has this one (or one below it)
    MATCHES = "matches"  # regular expression
    GT = "gt"  # for a period: starts after the date
    LT = "lt"  # for a period: ends before the date
    OVERLAPS = "overlaps"  # a period shares a day with the given one
    PRESENT = "present"
    MISSING = "missing"


type GroupMode = Literal["all", "any"]

_REFERENCE_OPERATORS = frozenset({Operator.IS, Operator.IN, Operator.PRESENT, Operator.MISSING})
_TAG_OPERATORS = frozenset({Operator.CONTAINS, Operator.IN, Operator.PRESENT, Operator.MISSING})
_FIELD_OPERATORS: dict[ConditionField, frozenset[Operator]] = {
    ConditionField.STEP: frozenset(
        {
            Operator.IS,
            Operator.IN,
            Operator.CONTAINS,
            Operator.GT,
            Operator.LT,
            Operator.PRESENT,
            Operator.MISSING,
        }
    ),
    ConditionField.CONTACT: _REFERENCE_OPERATORS,
    ConditionField.CONTACT_GROUP: _TAG_OPERATORS,
    ConditionField.DOCUMENT_TYPE: _REFERENCE_OPERATORS,
    ConditionField.DOCUMENT_TYPE_GROUP: _TAG_OPERATORS,
    ConditionField.TOPIC: _REFERENCE_OPERATORS,
    ConditionField.TAGS: _TAG_OPERATORS,
    ConditionField.CHANNEL: frozenset({Operator.IS, Operator.IN}),
    ConditionField.TEXT: frozenset({Operator.CONTAINS, Operator.MATCHES}),
    ConditionField.DOCUMENT_DATE: frozenset(
        {Operator.IS, Operator.GT, Operator.LT, Operator.PRESENT, Operator.MISSING}
    ),
}
TAG_FIELDS: dict[ConditionField, TagScope] = {
    ConditionField.TAGS: TagScope.DOCUMENT,
    ConditionField.CONTACT_GROUP: TagScope.CONTACT,
    ConditionField.DOCUMENT_TYPE_GROUP: TagScope.DOCUMENT_TYPE,
    ConditionField.TOPIC: TagScope.TOPIC,
}
"""The conditions on tags (a topic is one), and the scope of the tags each names."""
_ID_FIELDS = frozenset({ConditionField.CONTACT, ConditionField.DOCUMENT_TYPE, *TAG_FIELDS})
_ORDERED = frozenset({Operator.IS, Operator.GT, Operator.LT, Operator.PRESENT, Operator.MISSING})
FIELD_TYPE_OPERATORS: dict[FieldType, frozenset[Operator]] = {
    FieldType.TEXT: frozenset(
        {
            Operator.IS,
            Operator.IN,
            Operator.CONTAINS,
            Operator.MATCHES,
            Operator.PRESENT,
            Operator.MISSING,
        }
    ),
    FieldType.LINK: frozenset(
        {
            Operator.IS,
            Operator.IN,
            Operator.CONTAINS,
            Operator.MATCHES,
            Operator.PRESENT,
            Operator.MISSING,
        }
    ),
    FieldType.NUMBER: _ORDERED,
    FieldType.AMOUNT: _ORDERED,
    FieldType.DATE: _ORDERED,
    FieldType.BOOLEAN: frozenset({Operator.IS, Operator.PRESENT, Operator.MISSING}),
    FieldType.CHOICE: frozenset({Operator.IS, Operator.IN, Operator.PRESENT, Operator.MISSING}),
    FieldType.PERIOD: frozenset(
        {
            Operator.IS,
            Operator.OVERLAPS,
            Operator.GT,
            Operator.LT,
            Operator.PRESENT,
            Operator.MISSING,
        }
    ),
}


# --- conditions -------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Condition:
    """Field, operator and value. `value` is None for `present` and `missing`, a list for
    `in`, otherwise one value. `field_id` names the field of a `field` condition, `path` what
    a `step` condition looks at (`accounting.paid`: the answer of the step `accounting`, its
    key `paid`); `case_sensitive` applies to `matches` only."""

    field: ConditionField
    op: Operator
    value: JsonValue = None
    field_id: FieldId | None = None
    case_sensitive: bool = False
    path: str | None = None

    def __post_init__(self) -> None:
        if (self.field is ConditionField.FIELD) != (self.field_id is not None):
            raise ValidationError("field_id is given exactly for field conditions")
        if (self.field is ConditionField.STEP) != (self.path is not None):
            raise ValidationError("path is given exactly for step conditions")
        if self.path is not None:
            object.__setattr__(self, "path", validate_step_path(self.path))
        if self.field is not ConditionField.FIELD and self.op not in _FIELD_OPERATORS[self.field]:
            raise ValidationError(f"operator '{self.op}' does not apply to {self.field}")
        if self.case_sensitive and self.op is not Operator.MATCHES:
            raise ValidationError("case_sensitive applies to 'matches' only")
        if self.op in (Operator.PRESENT, Operator.MISSING):
            if self.value is not None:
                raise ValidationError(f"'{self.op}' takes no value")
            return
        if self.op is Operator.IN:
            if not isinstance(self.value, list) or not self.value:
                raise ValidationError("'in' takes a non-empty list")
            if len(self.value) > MAX_LIST:
                raise ValidationError(f"'in' takes at most {MAX_LIST} values")
            items = self.value
        else:
            if self.value is None or isinstance(self.value, list):
                raise ValidationError(f"'{self.op}' takes one value")
            items = [self.value]
        for item in items:
            self._check_value(item)
        if self.field in _ID_FIELDS:
            # One spelling of every id, so conditions compare ids as text.
            ids = [str(require_uuid(item, self.field.value)) for item in items]
            object.__setattr__(self, "value", ids if self.op is Operator.IN else ids[0])

    def _check_value(self, value: JsonValue) -> None:
        match self.field:
            case id_field if id_field in _ID_FIELDS:
                require_uuid(value, self.field.value)
            case ConditionField.CHANNEL:
                if not isinstance(value, str) or value not in {
                    channel.value for channel in Channel
                }:
                    raise ValidationError(f"unknown channel {value!r}")
            case ConditionField.TEXT:
                # A pattern is checked by the pattern matcher that runs it (`check_patterns`).
                _text(value, MAX_PATTERN if self.op is Operator.MATCHES else MAX_TEXT)
            case ConditionField.DOCUMENT_DATE:
                require_date(value, self.field.value)
            case ConditionField.FIELD:
                # Checked against the definition by `check_fields`; here only patterns.
                if self.op is Operator.MATCHES:
                    _text(value, MAX_PATTERN)
                elif self.op is Operator.CONTAINS:
                    _text(value, MAX_TEXT)
            case ConditionField.STEP:
                _step_value(self.op, value)

    @property
    def values(self) -> list[JsonValue]:
        if self.op is Operator.IN:
            assert isinstance(self.value, list)
            return list(self.value)
        return [] if self.value is None else [self.value]


@dataclass(frozen=True, kw_only=True)
class Group:
    """`all` (and) or `any` (or) of its items; `negate` turns the result around."""

    mode: GroupMode
    items: tuple["Condition | Group", ...]
    negate: bool = False

    def __post_init__(self) -> None:
        if self.mode not in ("all", "any"):
            raise ValidationError(f"a group is 'all' or 'any', not {self.mode!r}")
        if not self.items:
            raise ValidationError("a group needs at least one condition")

    def conditions(self) -> list[Condition]:
        """All conditions of the tree, depth first."""
        found: list[Condition] = []
        for item in self.items:
            if isinstance(item, Group):
                found.extend(item.conditions())
            else:
                found.append(item)
        return found

    @property
    def depth(self) -> int:
        return 1 + max((item.depth for item in self.items if isinstance(item, Group)), default=0)


STEP_NAME = re.compile(r"[a-z][a-z0-9_]{0,49}")
"""A step's name: what the steps after it write as `steps.<name>`."""
_STEP_KEY = re.compile(r"[A-Za-z0-9_-]{1,100}")
MAX_STEP_PATH = 200


def validate_step_path(path: str) -> str:
    """`<step>.<key>.<key>…`: a step's name, then keys of its answer (a number for an item of
    a list). ValidationError otherwise."""
    name, *keys = path.split(".")
    if (
        len(path) > MAX_STEP_PATH
        or not STEP_NAME.fullmatch(name)
        or not all(_STEP_KEY.fullmatch(key) for key in keys)
    ):
        raise ValidationError(
            f"path {path!r}: a step's name (small letters, digits, _), then keys, "
            f"separated by dots, at most {MAX_STEP_PATH} characters"
        )
    return path


def _step_value(op: Operator, value: JsonValue) -> None:
    """What a step condition compares with: a text, a number or true/false; `gt` and `lt` a
    number or a date (`YYYY-MM-DD`)."""
    if isinstance(value, bool):
        if op in (Operator.GT, Operator.LT, Operator.CONTAINS):
            raise ValidationError(f"'{op}' does not compare with true or false")
        return
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValidationError("a number is finite")
        return
    if not isinstance(value, str):
        raise ValidationError("a step condition compares with a text, a number or true/false")
    _text(value, MAX_TEXT)
    if op in (Operator.GT, Operator.LT):
        require_date(value, "value")


# --- actions ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SetSpace:
    space_id: SpaceId
    type: Literal["set_space"] = "set_space"


@dataclass(frozen=True)
class SetContact:
    contact_id: ContactId
    type: Literal["set_contact"] = "set_contact"


@dataclass(frozen=True)
class SetDocumentType:
    document_type_id: DocumentTypeId
    type: Literal["set_document_type"] = "set_document_type"


@dataclass(frozen=True)
class SetTopic:
    """The topic, if the document's contact (as the rules leave it) enables it."""

    topic_id: TagId
    type: Literal["set_topic"] = "set_topic"


@dataclass(frozen=True)
class SetTitle:
    """The title from a template (Liquid, `domain.templates`): `{{ contact }} {{ document_date
    | date: '%Y-%m' }}`. Its syntax and values are checked where the rule is saved (the
    template renderer is a port)."""

    template: str
    type: Literal["set_title"] = "set_title"

    def __post_init__(self) -> None:
        _text(self.template, MAX_TEXT)


@dataclass(frozen=True)
class AddTags:
    tag_ids: frozenset[TagId]
    type: Literal["add_tags"] = "add_tags"

    def __post_init__(self) -> None:
        _tag_list(self.tag_ids)


@dataclass(frozen=True)
class RemoveTags:
    tag_ids: frozenset[TagId]
    type: Literal["remove_tags"] = "remove_tags"

    def __post_init__(self) -> None:
        _tag_list(self.tag_ids)


@dataclass(frozen=True)
class SetField:
    """`value`: text is a template for any type, as the title's; what it renders is read as the
    field's type has it (`fields.read_written`), and what cannot be read sets nothing. Other
    values are fixed, in the JSON form of the field's type (`field_to_json`): an amount or a
    period as an object, yes or no as a boolean, a number as a JSON number. A fixed value that is
    text in its JSON form (`"12.50"`, `"2026-03-12"`, a choice, a link) is a template that writes
    itself and reads as it is: rules saved before templates for every type stay as they were."""

    field_id: FieldId
    value: JsonValue
    type: Literal["set_field"] = "set_field"

    def __post_init__(self) -> None:
        if self.value is None:
            raise ValidationError("set_field needs a value")


@dataclass(frozen=True)
class ForceReview:
    """The document waits in the inbox with this reason (when it arrives), a template as the
    title's; the review holds even where the reason cannot be rendered."""

    reason: str
    type: Literal["force_review"] = "force_review"

    def __post_init__(self) -> None:
        _text(self.reason, MAX_TEXT)


class Missing(StrEnum):
    """What a step that asks does without an answer (none in time, an error, an invalid
    one)."""

    RED = "red"  # the node fails: no rule acts
    YELLOW = "yellow"  # the rule ends here, its steps before count; the document waits
    CONTINUE = "continue"  # `steps.<name>` is missing, the rule goes on


@dataclass(frozen=True)
class AskWebhook:
    """Ask through the webhook (of whoever saved the rule) and wait for the answer: a task
    (`domain.tasks`). The steps after it see the answer as `steps.<name>`. `timeout_seconds`:
    the time to answer from sending; `missing`: what the rule does without an answer. Only on
    arrival (Tobi, 25.10.2026)."""

    name: str
    webhook_id: WebhookId
    timeout_seconds: int = int(DEFAULT_TIMEOUT.total_seconds())
    missing: Missing = Missing.RED
    type: Literal["ask_webhook"] = "ask_webhook"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not STEP_NAME.fullmatch(self.name):
            raise ValidationError(
                f"name {self.name!r}: small letters, digits and _, beginning with a letter, "
                "at most 50"
            )
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, int):
            raise ValidationError("timeout_seconds: a whole number")
        validate_timeout(timedelta(seconds=self.timeout_seconds))
        object.__setattr__(self, "missing", Missing(self.missing))

    @property
    def timeout(self) -> timedelta:
        return timedelta(seconds=self.timeout_seconds)


@dataclass(frozen=True)
class StepCondition:
    """The rule goes on only if the conditions hold, on the document as the rule's steps before
    left it and on `steps` (`ConditionField.STEP`); otherwise it ends here, and its steps
    before count."""

    conditions: Group
    type: Literal["condition"] = "condition"


@dataclass(frozen=True)
class SendWebhook:
    """A notification through the webhook (`webhooks.Webhook`, of whoever saved the rule) about
    the document as the rules leave it: on arrival when the document is filed, on a change once
    it is stored (Tobi, 25.10.2026). Its owner must be able to read the document."""

    webhook_id: WebhookId
    type: Literal["send_webhook"] = "send_webhook"


type Action = (
    SetSpace
    | SetContact
    | SetDocumentType
    | SetTopic
    | SetTitle
    | AddTags
    | RemoveTags
    | SetField
    | ForceReview
    | SendWebhook
    | AskWebhook
    | StepCondition
)
"""A rule's step: an action, asking a webhook or a condition."""

# --- definition -------------------------------------------------------------------------------


@dataclass(frozen=True)
class References:
    """What a definition refers to; the caller checks that it exists. `tags`: of every scope
    (groups in the conditions on them too); `tag_scopes` the scope each must have."""

    contacts: frozenset[ContactId] = frozenset()
    document_types: frozenset[DocumentTypeId] = frozenset()
    tags: frozenset[TagId] = frozenset()
    fields: frozenset[FieldId] = frozenset()
    spaces: frozenset[SpaceId] = frozenset()
    tag_scopes: tuple[tuple[TagId, TagScope], ...] = ()
    webhooks: frozenset[WebhookId] = frozenset()


@dataclass(frozen=True, kw_only=True)
class RuleDefinition:
    """The versioned content of a rule. Checked here for everything that needs no stored
    data; `check_fields` does the rest."""

    name: str
    conditions: Group
    actions: tuple[Action, ...]
    priority: int = DEFAULT_PRIORITY
    triggers: frozenset[Trigger] = frozenset(Trigger)

    def __post_init__(self) -> None:
        name = require_name(self.name, "rule name")
        object.__setattr__(self, "name", name)
        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or not MIN_PRIORITY <= self.priority <= MAX_PRIORITY
        ):
            raise ValidationError(
                f"priority must be a whole number from {MIN_PRIORITY} to {MAX_PRIORITY}"
            )
        if not self.triggers:
            raise ValidationError("a rule needs at least one trigger")
        groups = [self.conditions, *(step.conditions for step in self.step_conditions)]
        if any(group.depth > MAX_DEPTH for group in groups):
            raise ValidationError(f"conditions may be nested at most {MAX_DEPTH} deep")
        if len(self.all_conditions()) > MAX_CONDITIONS:
            raise ValidationError(f"a rule has at most {MAX_CONDITIONS} conditions")
        if any(
            condition.field is ConditionField.STEP for condition in self.conditions.conditions()
        ):
            raise ValidationError(
                "conditions: a condition on what a step brought belongs in a condition step"
            )
        if not any(not isinstance(action, StepCondition) for action in self.actions):
            raise ValidationError("a rule needs at least one action")
        if len(self.actions) > MAX_ACTIONS:
            raise ValidationError(f"a rule has at most {MAX_ACTIONS} actions")
        if self.asks and self.triggers != {Trigger.INGEST}:
            raise ValidationError("a rule that asks a webhook runs on arrival only (ingest)")
        seen: set[str] = set()
        asked: set[str] = set()
        for index, action in enumerate(self.actions):
            key = _single_key(action)
            if key in seen:
                raise ValidationError(
                    f"actions[{index}]: an action sets the same field twice: {key}"
                )
            if key is not None:
                seen.add(key)
            if isinstance(action, AskWebhook):
                asked.add(action.name)
            elif isinstance(action, StepCondition):
                for condition in action.conditions.conditions():
                    if condition.path is not None and condition.path.split(".")[0] not in asked:
                        raise ValidationError(
                            f"actions[{index}]: no step before it is named "
                            f"'{condition.path.split('.')[0]}'"
                        )

    def references(self) -> References:
        contacts: set[ContactId] = set()
        types: set[DocumentTypeId] = set()
        tags: set[TagId] = set()
        fields: set[FieldId] = set()
        spaces: set[SpaceId] = set()
        webhooks: set[WebhookId] = set()
        scopes: dict[tuple[TagId, TagScope], None] = {}
        for condition in self.all_conditions():
            match condition.field:
                case ConditionField.CONTACT:
                    contacts.update(ContactId(id) for id in _ids(condition))
                case ConditionField.DOCUMENT_TYPE:
                    types.update(DocumentTypeId(id) for id in _ids(condition))
                case tag_field if tag_field in TAG_FIELDS:
                    named = [TagId(id) for id in _ids(condition)]
                    tags.update(named)
                    scopes.update(((id, TAG_FIELDS[tag_field]), None) for id in named)
                case ConditionField.FIELD:
                    assert condition.field_id is not None
                    fields.add(condition.field_id)
        for action in self.actions:
            match action:
                case SetSpace(space_id=space):
                    spaces.add(space)
                case SetContact(contact_id=contact):
                    contacts.add(contact)
                case SetDocumentType(document_type_id=document_type):
                    types.add(document_type)
                case SetTopic(topic_id=topic):
                    tags.add(topic)
                    scopes[(topic, TagScope.TOPIC)] = None
                case AddTags(tag_ids=ids) | RemoveTags(tag_ids=ids):
                    tags.update(ids)
                    scopes.update(((id, TagScope.DOCUMENT), None) for id in sorted(ids))
                case SetField(field_id=field):
                    fields.add(field)
                case SendWebhook(webhook_id=webhook) | AskWebhook(webhook_id=webhook):
                    webhooks.add(webhook)
        return References(
            frozenset(contacts),
            frozenset(types),
            frozenset(tags),
            frozenset(fields),
            frozenset(spaces),
            tuple(scopes),
            frozenset(webhooks),
        )

    @property
    def sends(self) -> tuple[SendWebhook, ...]:
        """The webhooks the rule sends through, in order."""
        return tuple(action for action in self.actions if isinstance(action, SendWebhook))

    @property
    def asks(self) -> tuple[AskWebhook, ...]:
        """The steps that ask a webhook, in order."""
        return tuple(action for action in self.actions if isinstance(action, AskWebhook))

    @property
    def step_conditions(self) -> tuple[StepCondition, ...]:
        return tuple(action for action in self.actions if isinstance(action, StepCondition))

    @property
    def has_steps(self) -> bool:
        """Whether the rule asks or checks between its actions (not only actions)."""
        return any(isinstance(action, AskWebhook | StepCondition) for action in self.actions)

    def all_conditions(self) -> list[Condition]:
        """The conditions of the rule's head and of its condition steps."""
        return [
            *self.conditions.conditions(),
            *(item for step in self.step_conditions for item in step.conditions.conditions()),
        ]

    @property
    def uses_text(self) -> bool:
        return any(condition.field is ConditionField.TEXT for condition in self.all_conditions())

    def patterns(self) -> set[tuple[str, str, bool]]:
        """The regular expressions of the conditions: target (`text` or a field id),
        pattern and case setting."""
        return {
            (
                "text" if condition.field_id is None else str(condition.field_id),
                str(condition.value),
                condition.case_sensitive,
            )
            for condition in self.all_conditions()
            if condition.op is Operator.MATCHES
        }


def _ids(condition: Condition) -> list[UUID]:
    return [UUID(str(value)) for value in condition.values]


def _single_key(action: Action) -> str | None:
    """The field an action sets alone; two such actions in one rule contradict each other (a
    webhook twice would send twice)."""
    match action:
        case SetField(field_id=field):
            return field_key(field)
        case SendWebhook(webhook_id=webhook):
            return f"{action.type}:{webhook}"
        case AskWebhook(name=name):
            return f"step {name}"
        case AddTags() | RemoveTags() | ForceReview() | StepCondition():
            return None
    return action.type


def title_rule(document_type: DocumentType) -> RuleDefinition:
    """The rule of a type's title pattern (`Rule.managed_by`): "document type is X → set the
    title", on arrival and on a change."""
    if document_type.title_pattern is None:
        raise ValidationError(f"'{document_type.name}' has no title pattern")
    condition = Condition(
        field=ConditionField.DOCUMENT_TYPE, op=Operator.IS, value=str(document_type.id)
    )
    return RuleDefinition(
        name=document_type.name,
        conditions=Group(mode="all", items=(condition,)),
        actions=(SetTitle(document_type.title_pattern),),
        priority=0,
        triggers=frozenset({Trigger.INGEST, Trigger.CHANGE}),
    )


def check_fields(
    definition: RuleDefinition, definitions: Mapping[FieldId, FieldDefinition]
) -> None:
    """Conditions and actions on fields fit the field's data type. ValidationError
    otherwise, naming the place; a missing field is a ValidationError too."""
    places = [
        *condition_places(definition.conditions),
        *(
            item
            for index, step in enumerate(definition.actions)
            if isinstance(step, StepCondition)
            for item in condition_places(step.conditions, f"actions[{index}].conditions")
        ),
    ]
    for place, condition in places:
        if condition.field is not ConditionField.FIELD:
            continue
        assert condition.field_id is not None
        with _at(place):
            field = _field(definitions, condition.field_id)
            if condition.op not in FIELD_TYPE_OPERATORS[field.data_type]:
                raise ValidationError(
                    f"operator '{condition.op}' does not apply to field '{field.name}' "
                    f"({field.data_type})"
                )
            if condition.op in (Operator.CONTAINS, Operator.MATCHES):
                continue
            for value in condition.values:
                condition_value(field, condition.op, value)
    for index, action in enumerate(definition.actions):
        if isinstance(action, SetField):
            with _at(f"actions[{index}]"):
                field = _field(definitions, action.field_id)
                if not is_template(field, action.value):
                    field_from_json(field, action.value)
                elif (
                    # Text without markup writes itself: it must be readable now. A template's
                    # syntax and values are checked where the rule is saved (a port renders it).
                    not TEMPLATE_MARKUP.search(str(action.value))
                    and read_written(field, str(action.value), Writing()) is None
                ):
                    raise field.refusal(action.value)


TEMPLATE_MARKUP = re.compile(r"\{[{%]")
"""Where Liquid begins an output or a tag."""


def is_template(field: FieldDefinition, value: JsonValue) -> bool:
    """Whether a `set_field` value for `field` is a template: text, unless it is one of a choice
    field's options as written (a fixed value, whatever it holds: `Projekt {{A}}`)."""
    if not isinstance(value, str):
        return False
    return not (field.data_type is FieldType.CHOICE and value in field.choices)


def condition_value(field: FieldDefinition, op: Operator, value: JsonValue) -> FieldValue:
    """A value a condition on `field` compares with, in the field's type; for a period's `gt`
    and `lt` a date (it starts after, it ends before). ValidationError if it does not fit."""
    if field.data_type is FieldType.PERIOD and op in (Operator.GT, Operator.LT):
        return require_date(value, field.name)
    return field_from_json(field, value)


def condition_places(group: Group, where: str = "conditions") -> Iterator[tuple[str, Condition]]:
    """The conditions of the tree with their place in the JSON form, depth first."""
    for index, item in enumerate(group.items):
        place = f"{where}.{group.mode}[{index}]"
        if isinstance(item, Group):
            yield from condition_places(item, place)
        else:
            yield place, item


@contextmanager
def _at(place: str) -> Iterator[None]:
    """Prefix the message of a ValidationError with `place`."""
    try:
        yield
    except ValidationError as error:
        raise ValidationError(f"{place}: {error}") from None


def _field(definitions: Mapping[FieldId, FieldDefinition], id: FieldId) -> FieldDefinition:
    try:
        return definitions[id]
    except KeyError:
        raise ValidationError(f"field {id} does not exist") from None


# --- rule -------------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class RuleVersion:
    """A saved state of a rule. `space_id`: the space the rule belonged to with it (None:
    global), so its history shows who moved it from where to where."""

    rule_id: RuleId
    number: int
    definition: RuleDefinition
    created_at: datetime
    created_by: UserId | None
    space_id: SpaceId | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))
        if self.number < 1:
            raise ValidationError("rule versions start at 1")


@dataclass(kw_only=True)
class Rule:
    """A rule with its current version. `space_id` is None exactly for global rules.

    `disabled_reason` says why the rule was disabled automatically (e.g. a contact it refers to
    was deleted), with its code; None if a person disabled it or it is enabled. A deleted rule
    stays stored for its versions; it never runs and is not listed.

    `managed_by`: the document type whose title pattern this rule is (global, it sets the
    title). The type keeps it as the pattern says; nobody changes it otherwise."""

    id: RuleId
    scope: RuleScope
    space_id: SpaceId | None
    current: RuleVersion
    created_at: datetime
    updated_at: datetime
    enabled: bool = True
    disabled_reason: Reason | None = None
    deleted_at: datetime | None = None
    managed_by: DocumentTypeId | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if (self.scope is RuleScope.GLOBAL) != (self.space_id is None):
            raise ValidationError("global rules belong to no space, space rules to one")
        if self.managed_by is not None and self.scope is not RuleScope.GLOBAL:
            raise ValidationError("the rule of a title pattern is global")
        if self.current.rule_id != self.id:
            raise ValidationError("the current version belongs to another rule")
        if self.current.space_id != self.space_id:
            raise ValidationError("the current version names another space")
        self.created_at = require_utc(self.created_at, "created_at")
        self.updated_at = require_utc(self.updated_at, "updated_at")

    @classmethod
    def create(
        cls,
        *,
        scope: RuleScope,
        space_id: SpaceId | None,
        definition: RuleDefinition,
        by: UserId,
        now: datetime,
        managed_by: DocumentTypeId | None = None,
    ) -> Self:
        id = RuleId(new_id())
        return cls(
            id=id,
            scope=scope,
            space_id=space_id,
            current=RuleVersion(
                rule_id=id,
                number=1,
                definition=definition,
                created_at=now,
                created_by=by,
                space_id=space_id,
            ),
            created_at=now,
            updated_at=now,
            managed_by=managed_by,
        )

    @property
    def definition(self) -> RuleDefinition:
        return self.current.definition

    @property
    def is_active(self) -> bool:
        return self.enabled and self.deleted_at is None

    def change(
        self,
        definition: RuleDefinition,
        by: UserId,
        now: datetime,
        *,
        scope: RuleScope | None = None,
        space_id: SpaceId | None = None,
    ) -> RuleVersion:
        """A new version with `definition`; with `scope`, the rule moves: into the space
        `space_id` or, global, into none (the rule of a title pattern stays global)."""
        self._check_not_deleted()
        if scope is not None:
            if (scope is RuleScope.GLOBAL) != (space_id is None):
                raise ValidationError("global rules belong to no space, space rules to one")
            if self.managed_by is not None and scope is not RuleScope.GLOBAL:
                raise ValidationError("the rule of a title pattern is global")
            self.scope, self.space_id = scope, space_id
        self.current = RuleVersion(
            rule_id=self.id,
            number=self.current.number + 1,
            definition=definition,
            created_at=now,
            created_by=by,
            space_id=self.space_id,
        )
        self.updated_at = require_utc(now, "updated_at")
        return self.current

    def enable(self, now: datetime) -> None:
        self._check_not_deleted()
        self.enabled, self.disabled_reason = True, None
        self.updated_at = require_utc(now, "updated_at")

    def disable(self, now: datetime, reason: Reason | None = None) -> None:
        self._check_not_deleted()
        self.enabled, self.disabled_reason = False, reason
        self.updated_at = require_utc(now, "updated_at")

    def delete(self, now: datetime) -> None:
        """A deleted rule is no document type's rule any more: the type may get another."""
        self._check_not_deleted()
        self.enabled = False
        self.managed_by = None
        self.deleted_at = self.updated_at = require_utc(now, "deleted_at")

    def _check_not_deleted(self) -> None:
        if self.deleted_at is not None:
            raise ValidationError(f"rule {self.id} is deleted")

    @property
    def order(self) -> tuple[int, int, datetime, RuleId]:
        """Sort key: higher priority first, then global before space rules, then older first."""
        return (
            -self.definition.priority,
            0 if self.scope is RuleScope.GLOBAL else 1,
            self.created_at,
            self.id,
        )


# --- applying a rule to existing documents ----------------------------------------------------


class ApplicationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(kw_only=True)
class RuleApplication:
    """A person applies one version of a rule to documents they selected (in the background).

    `accept_conflicts`: documents where the rule's value replaces a different value the
    document has (a deliberate decision, no review). `position`: how many of `documents` are
    done. `skipped`: document id and reason (with its code)."""

    id: RuleApplicationId
    rule_id: RuleId
    rule_version: int
    user_id: UserId
    documents: tuple[DocumentId, ...]
    accept_conflicts: frozenset[DocumentId] = frozenset()
    status: ApplicationStatus = ApplicationStatus.QUEUED
    position: int = 0
    applied: int = 0
    unchanged: int = 0
    skipped: list[tuple[DocumentId, Reason]] = field(default_factory=list)
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if not self.documents:
            raise ValidationError("select at least one document")
        if len(set(self.documents)) != len(self.documents):
            raise ValidationError("a document is selected twice")
        if not self.accept_conflicts <= set(self.documents):
            raise ValidationError("accepted conflicts must be among the selected documents")
        self.created_at = require_utc(self.created_at, "created_at")

    @classmethod
    def create(
        cls,
        *,
        rule_id: RuleId,
        rule_version: int,
        user_id: UserId,
        documents: tuple[DocumentId, ...],
        accept_conflicts: frozenset[DocumentId],
        now: datetime,
    ) -> Self:
        return cls(
            id=RuleApplicationId(new_id()),
            rule_id=rule_id,
            rule_version=rule_version,
            user_id=user_id,
            documents=documents,
            accept_conflicts=accept_conflicts,
            created_at=now,
        )

    @property
    def remaining(self) -> tuple[DocumentId, ...]:
        return self.documents[self.position :]

    def record_applied(self) -> None:
        """One more document done: the rule changed it."""
        self.applied += 1
        self._next()

    def record_unchanged(self) -> None:
        """One more document done: the rule did not hold or changed nothing."""
        self.unchanged += 1
        self._next()

    def record_skipped(self, document: DocumentId, reason: Reason) -> None:
        """One more document done: left as it was, for `reason`."""
        self.skipped.append((document, reason))
        self._next()

    def _next(self) -> None:
        self.position += 1
        self.status = ApplicationStatus.RUNNING

    def finish(self, now: datetime, error: str | None = None) -> None:
        self.status = ApplicationStatus.FAILED if error else ApplicationStatus.DONE
        self.error = error
        self.finished_at = require_utc(now, "finished_at")


# --- helpers ----------------------------------------------------------------------------------


def _text(value: JsonValue, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"expected non-empty text, got {value!r}")
    if len(value) > limit:
        raise ValidationError(f"text longer than {limit} characters")
    return value


def _tag_list(tags: frozenset[TagId]) -> None:
    if not tags:
        raise ValidationError("give at least one tag")
    if len(tags) > MAX_LIST:
        raise ValidationError(f"at most {MAX_LIST} tags")
