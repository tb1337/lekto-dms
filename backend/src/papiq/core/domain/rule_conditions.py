"""Evaluating the conditions of rules against a document: which rules match.

Conditions are evaluated against the state before any rule acts (a rule's action never makes
another rule match in the same run). A condition on a tag, a group or a topic matches the ones
below it too (the document has the tag set and its ancestors; its contact and type have their
groups and theirs; its topic has its ancestors). The result of a condition is three-valued: with
`distrust`, a condition on a contact, type, topic or tag that the model set and no person
confirmed is unknown, and so is one on the groups of such a contact or type. A rule that matches
only with such values does not file into a space that others see (the accepted risk of M5: a
text can name a wrong contact and make it green; see `rule_planner`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from papiq.core.domain.classification import CONTACT, DOCUMENT_TYPE, TAGS, TOPIC
from papiq.core.domain.documents import Channel, Document
from papiq.core.domain.errors import ValidationError
from papiq.core.domain.evidence import DocumentText, contains, normalise, without_markup
from papiq.core.domain.fields import FieldDefinition, FieldType, FieldValue, Money, Url
from papiq.core.domain.ids import ContactId, DocumentTypeId, FieldId, TagId
from papiq.core.domain.json_value import JsonValue, require_date
from papiq.core.domain.periods import Period
from papiq.core.domain.rules import (
    Condition,
    ConditionField,
    Group,
    Operator,
    Rule,
    condition_value,
)
from papiq.core.domain.tag_tree import TagTree

TEXT_TARGET = "text"

type Truth = bool | None
"""Three-valued: None is unknown."""


# --- facts and evaluation ---------------------------------------------------------------------


@dataclass(frozen=True)
class Taxonomy:
    """The tags as trees, the groups of the contacts and types a run looks at (by the
    contact's or type's id), and the topics those contacts enable."""

    tree: TagTree = field(default_factory=lambda: TagTree.of(()))
    groups: Mapping[UUID, frozenset[TagId]] = field(default_factory=dict)
    topics: Mapping[UUID, frozenset[TagId]] = field(default_factory=dict)

    def groups_of(self, id: UUID | None) -> frozenset[TagId]:
        return frozenset() if id is None else self.groups.get(id, frozenset())

    def topics_of(self, contact: UUID | None) -> frozenset[TagId]:
        return frozenset() if contact is None else self.topics.get(contact, frozenset())


@dataclass(frozen=True, kw_only=True)
class Facts:
    """A document's state as conditions see it.

    `patterns`: results of the regular expressions, by (target, pattern, case setting), target
    `text` or a field id; computed beforehand with a time limit. A missing result (no
    text, time out) does not match. `unverified`: the fields `contact`, `document_type` and
    `topic` if they hold a value the model set and no person confirmed; `unverified_tags`
    likewise.
    `taxonomy`: the tag trees; `contact_groups` and `document_type_groups` the groups of the
    contact and the type."""

    contact_id: ContactId | None
    document_type_id: DocumentTypeId | None
    tag_ids: frozenset[TagId]
    channel: Channel
    document_date: date | None
    fields: Mapping[FieldId, FieldValue]
    topic_id: TagId | None = None
    text: DocumentText | None = None
    patterns: Mapping[tuple[str, str, bool], bool] = field(default_factory=dict)
    unverified: frozenset[str] = frozenset()
    unverified_tags: frozenset[TagId] = frozenset()
    taxonomy: Taxonomy = field(default_factory=Taxonomy)
    contact_groups: frozenset[TagId] = frozenset()
    document_type_groups: frozenset[TagId] = frozenset()

    @classmethod
    def of(
        cls,
        document: Document,
        *,
        text: DocumentText | None = None,
        patterns: Mapping[tuple[str, str, bool], bool] | None = None,
        unverified: frozenset[str] = frozenset(),
        unverified_tags: frozenset[TagId] = frozenset(),
        taxonomy: Taxonomy | None = None,
    ) -> "Facts":
        taxonomy = taxonomy or Taxonomy()
        return cls(
            contact_id=document.contact_id,
            document_type_id=document.document_type_id,
            tag_ids=frozenset(document.tag_ids),
            channel=document.channel,
            document_date=document.document_date,
            fields=dict(document.fields),
            topic_id=document.topic_id,
            text=text,
            patterns=patterns or {},
            unverified=unverified,
            unverified_tags=unverified_tags & frozenset(document.tag_ids),
            taxonomy=taxonomy,
            contact_groups=taxonomy.groups_of(document.contact_id),
            document_type_groups=taxonomy.groups_of(document.document_type_id),
        )


def evaluate(
    group: Group,
    facts: Facts,
    definitions: Mapping[FieldId, FieldDefinition],
    *,
    distrust: bool = False,
) -> Truth:
    """Whether the conditions hold; with `distrust`, unknown where they depend on unconfirmed
    model values (Kleene logic: unknown and false is false, unknown or true is true)."""
    results = [
        evaluate(item, facts, definitions, distrust=distrust)
        if isinstance(item, Group)
        else _condition(item, facts, definitions, distrust)
        for item in group.items
    ]
    if group.mode == "all":
        result: Truth = False if False in results else (None if None in results else True)
    else:
        result = True if True in results else (None if None in results else False)
    if group.negate and result is not None:
        return not result
    return result


def distrusted_fields(group: Group, facts: Facts) -> tuple[str, ...]:
    """The unconfirmed model fields the conditions look at."""
    found: list[str] = []
    for condition in group.conditions():
        match condition.field:
            case ConditionField.CONTACT if CONTACT in facts.unverified:
                found.append(CONTACT)
            case ConditionField.DOCUMENT_TYPE if DOCUMENT_TYPE in facts.unverified:
                found.append(DOCUMENT_TYPE)
            case ConditionField.CONTACT_GROUP if CONTACT in facts.unverified:
                found.append(CONTACT)
            case ConditionField.DOCUMENT_TYPE_GROUP if DOCUMENT_TYPE in facts.unverified:
                found.append(DOCUMENT_TYPE)
            case ConditionField.TOPIC if TOPIC in facts.unverified:
                found.append(TOPIC)
            case ConditionField.TAGS if facts.unverified_tags:
                found.append(TAGS)
    return tuple(dict.fromkeys(found))


def _condition(
    condition: Condition,
    facts: Facts,
    definitions: Mapping[FieldId, FieldDefinition],
    distrust: bool,
) -> Truth:
    op, values = condition.op, condition.values
    match condition.field:
        case ConditionField.CONTACT | ConditionField.DOCUMENT_TYPE:
            field_name = condition.field.value
            current = facts.contact_id if field_name == CONTACT else facts.document_type_id
            if distrust and field_name in facts.unverified:
                return None
            return _reference(op, None if current is None else str(current), values)
        case ConditionField.TAGS:
            return _tags(op, values, facts, distrust)
        case ConditionField.CONTACT_GROUP | ConditionField.DOCUMENT_TYPE_GROUP:
            owner = CONTACT if condition.field is ConditionField.CONTACT_GROUP else DOCUMENT_TYPE
            if distrust and owner in facts.unverified:
                return None
            groups = facts.contact_groups if owner == CONTACT else facts.document_type_groups
            return _held(op, values, facts.taxonomy.tree.with_ancestors(groups))
        case ConditionField.TOPIC:
            if distrust and TOPIC in facts.unverified:
                return None
            topic = () if facts.topic_id is None else (facts.topic_id,)
            return _held(op, values, facts.taxonomy.tree.with_ancestors(topic))
        case ConditionField.CHANNEL:
            return facts.channel.value in values
        case ConditionField.TEXT:
            if facts.text is None:
                return False
            if op is Operator.MATCHES:
                key = (TEXT_TARGET, str(condition.value), condition.case_sensitive)
                return facts.patterns.get(key, False)
            return facts.text.contains(str(condition.value))
        case ConditionField.DOCUMENT_DATE:
            return _ordered(
                op,
                facts.document_date,
                [require_date(value, ConditionField.DOCUMENT_DATE) for value in values],
            )
        case ConditionField.FIELD:
            assert condition.field_id is not None
            definition = definitions.get(condition.field_id)
            if definition is None:
                return False
            return _field(condition, definition, facts)


def _reference(op: Operator, current: str | None, values: list[JsonValue]) -> bool:
    match op:
        case Operator.PRESENT:
            return current is not None
        case Operator.MISSING:
            return current is None
    return current is not None and current in {str(value) for value in values}


def _tags(op: Operator, values: list[JsonValue], facts: Facts, distrust: bool) -> Truth:
    """A tag wanted matches the tags set below it: the document has it as an ancestor."""
    unverified = facts.unverified_tags if distrust else frozenset()
    verified = facts.tag_ids - unverified
    tree = facts.taxonomy.tree
    wanted = {TagId(UUID(str(value))) for value in values}
    match op:
        case Operator.PRESENT:
            return True if verified else (None if unverified else False)
        case Operator.MISSING:
            return False if verified else (None if unverified else True)
    if wanted & tree.with_ancestors(verified):
        return True
    return None if wanted & tree.with_ancestors(unverified) else False


def _held(op: Operator, values: list[JsonValue], held: frozenset[TagId]) -> bool:
    """A condition on groups (or the topic), against the groups held with their ancestors."""
    match op:
        case Operator.PRESENT:
            return bool(held)
        case Operator.MISSING:
            return not held
    return bool({TagId(UUID(str(value))) for value in values} & held)


def _ordered[T: (date, Decimal)](op: Operator, current: T | None, values: list[T]) -> bool:
    match op:
        case Operator.PRESENT:
            return current is not None
        case Operator.MISSING:
            return current is None
    if current is None or not values:
        return False
    match op:
        case Operator.GT:
            return current > values[0]
        case Operator.LT:
            return current < values[0]
    return current in values


def _field(condition: Condition, definition: FieldDefinition, facts: Facts) -> bool:
    op = condition.op
    value = facts.fields.get(definition.id)
    if op is Operator.PRESENT:
        return value is not None
    if op is Operator.MISSING:
        return value is None
    if value is None:
        return False
    if op is Operator.MATCHES:
        key = (str(definition.id), str(condition.value), condition.case_sensitive)
        return facts.patterns.get(key, False)
    if op is Operator.CONTAINS:
        return contains(normalise(_text_of(value)), str(condition.value))
    try:
        wanted = [condition_value(definition, op, item) for item in condition.values]
    except ValidationError:
        return False
    match value:
        case Period():
            return _period(op, value, wanted)
        case Money():
            same = [
                item.amount
                for item in wanted
                if isinstance(item, Money) and item.currency == value.currency
            ]
            return _ordered(op, value.amount, same)
        case bool():
            return value in wanted
        case Decimal():
            return _ordered(op, value, [item for item in wanted if isinstance(item, Decimal)])
        case date():
            return _ordered(op, value, [item for item in wanted if isinstance(item, date)])
        case str() if definition.data_type is FieldType.TEXT:
            return value.casefold() in {str(item).casefold() for item in wanted}
    return value in wanted


def _period(op: Operator, value: Period, wanted: list[FieldValue]) -> bool:
    """`is`: one of the given periods; `overlaps`: shares a day with one; `gt`: starts after
    the given date; `lt`: ends before it."""
    match op:
        case Operator.OVERLAPS:
            return any(isinstance(item, Period) and value.overlaps(item) for item in wanted)
        case Operator.GT:
            return bool(wanted) and isinstance(wanted[0], date) and value.start > wanted[0]
        case Operator.LT:
            return bool(wanted) and isinstance(wanted[0], date) and value.end < wanted[0]
    return value in wanted


def _text_of(value: FieldValue) -> str:
    return value.value if isinstance(value, Url) else str(value)


def pattern_subjects(
    rules: Sequence[Rule], document: Document, text: str | None
) -> dict[tuple[str, str, bool], str]:
    """What each regular expression of `rules` runs against: the text or a field value
    (as text). Patterns without a subject (no text, no value) are left out."""
    subjects: dict[tuple[str, str, bool], str] = {}
    for rule in rules:
        for target, pattern, case_sensitive in rule.definition.patterns():
            subject: str | None
            if target == TEXT_TARGET:
                subject = text
            else:
                value = document.fields.get(FieldId(UUID(target)))
                subject = None if value is None else _text_of(value)
            if subject is not None:
                subjects[(target, pattern, case_sensitive)] = subject
    return subjects


def pattern_text(markdown: str, limit: int) -> str:
    """The text regular expressions run against: Markdown markup removed, whitespace collapsed,
    case kept, at most `limit` characters."""
    return without_markup(markdown[: limit * 2])[:limit]


# --- matching rules ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Match:
    """A rule whose conditions hold. `trusted`: they hold without unconfirmed model values;
    otherwise `distrusted` names the model fields they rely on."""

    rule: Rule
    trusted: bool = True
    distrusted: tuple[str, ...] = ()


def matches(
    rules: Sequence[Rule],
    facts: Facts,
    definitions: Mapping[FieldId, FieldDefinition],
    *,
    before: Facts | None = None,
) -> list[Match]:
    """The rules whose conditions hold, in rule order. With `before` (a change): only those
    that did not hold before the change (they become true with it)."""
    found: list[Match] = []
    for rule in sorted(rules, key=lambda item: item.order):
        conditions = rule.definition.conditions
        if not evaluate(conditions, facts, definitions):
            continue
        if before is not None and evaluate(conditions, before, definitions):
            continue
        trusted = evaluate(conditions, facts, definitions, distrust=True) is True
        found.append(Match(rule, trusted, () if trusted else distrusted_fields(conditions, facts)))
    return found
