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
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from uuid import UUID

from lekto.core.domain.classification import CONTACT, DOCUMENT_TYPE, TAGS, TOPIC
from lekto.core.domain.document_facts import DocumentFact, FactState
from lekto.core.domain.documents import Channel, Document
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.evidence import DocumentText, contains, normalise, without_markup
from lekto.core.domain.fields import FieldDefinition, FieldType, FieldValue, Money, Url
from lekto.core.domain.ids import ContactId, DocumentTypeId, FieldId, TagId, UserId
from lekto.core.domain.json_value import JsonValue, require_date
from lekto.core.domain.periods import Period
from lekto.core.domain.rules import (
    Condition,
    ConditionField,
    Group,
    Operator,
    Rule,
    condition_value,
)
from lekto.core.domain.tag_tree import TagTree

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
    contact and the type. `steps`: what a rule's steps brought so far, by step name (for its
    condition steps). `kept_facts`: the document's facts (`domain.document_facts`).
    `referred_types`: the types of the documents it refers to (None: one without a type)."""

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
    steps: Mapping[str, JsonValue] = field(default_factory=dict)
    kept_facts: tuple[DocumentFact, ...] = ()
    referred_types: tuple[DocumentTypeId | None, ...] = ()

    @classmethod
    def of(
        cls,
        document: Document,
        *,
        kept_facts: Sequence[DocumentFact] = (),
        text: DocumentText | None = None,
        patterns: Mapping[tuple[str, str, bool], bool] | None = None,
        unverified: frozenset[str] = frozenset(),
        unverified_tags: frozenset[TagId] = frozenset(),
        taxonomy: Taxonomy | None = None,
        steps: Mapping[str, JsonValue] | None = None,
        referred_types: Sequence[DocumentTypeId | None] = (),
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
            steps=steps or {},
            kept_facts=tuple(kept_facts),
            referred_types=tuple(referred_types),
        )


def fact_values(condition: Condition, kept: Sequence[DocumentFact]) -> list[DocumentFact]:
    """The facts a `fact` condition looks at: of its kind, in its role if it names one, none a
    person rejected."""
    return [
        fact
        for fact in kept
        if fact.state is not FactState.REJECTED
        and fact.kind is condition.fact_kind
        and (condition.fact_role is None or fact.role is condition.fact_role)
    ]


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
        case ConditionField.STEP:
            assert condition.path is not None
            return _step(op, step_value(facts.steps, condition.path), values)
        case ConditionField.RELATION:
            # Found by Lekto or set by a person: never unknown.
            match op:
                case Operator.PRESENT:
                    return bool(facts.referred_types)
                case Operator.MISSING:
                    return not facts.referred_types
            return any(str(kind) in values for kind in facts.referred_types if kind is not None)
        case ConditionField.FACT:
            # Read from the text (or decided by a person): never unknown.
            held = [fact.value for fact in fact_values(condition, facts.kept_facts)]
            match op:
                case Operator.PRESENT:
                    return bool(held)
                case Operator.MISSING:
                    return not held
                case Operator.MATCHES:
                    key = (condition.target, str(condition.value), condition.case_sensitive)
                    return facts.patterns.get(key, False)
            return any(value in values for value in held)


_MISSING = object()


def step_value(steps: Mapping[str, JsonValue], path: str) -> JsonValue | object:
    """The value at `path` (`<step>.<key>…`, a number for an item of a list) in what the steps
    brought; `_MISSING` where there is none (null counts as none)."""
    name, *keys = path.split(".")
    if name not in steps:
        return _MISSING
    value: JsonValue = steps[name]
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return _MISSING
    return _MISSING if value is None else value


def _step(op: Operator, value: JsonValue | object, wanted: list[JsonValue]) -> bool:
    """A condition on what a step brought: texts compare without case, numbers as numbers
    (`1` is `1.0`, `"2"` is not), `gt` and `lt` numbers or dates; `contains` a text in a
    text, or an item of a list."""
    match op:
        case Operator.PRESENT:
            return value is not _MISSING
        case Operator.MISSING:
            return value is _MISSING
    if value is _MISSING:
        return False
    match op:
        case Operator.IS | Operator.IN:
            return any(_same(value, item) for item in wanted)
        case Operator.CONTAINS:
            target = wanted[0]
            if isinstance(value, str):
                return isinstance(target, str) and target.casefold() in value.casefold()
            return isinstance(value, list) and any(_same(item, target) for item in value)
        case Operator.GT | Operator.LT:
            order = _order(value, wanted[0])
            if order is None:
                return False
            return order > 0 if op is Operator.GT else order < 0
    return False


def _same(value: object, wanted: JsonValue) -> bool:
    if isinstance(value, bool) or isinstance(wanted, bool):
        return value is wanted
    if isinstance(value, int | float) and isinstance(wanted, int | float):
        return Decimal(str(value)) == Decimal(str(wanted))
    if isinstance(value, str) and isinstance(wanted, str):
        return value.casefold() == wanted.casefold()
    return False


def _order(value: object, wanted: JsonValue) -> int | None:
    """-1, 0 or 1 as `value` comes before, with or after `wanted`, both numbers or both dates;
    None if they do not compare."""
    if isinstance(wanted, int | float) and not isinstance(wanted, bool):
        if isinstance(value, int | float) and not isinstance(value, bool):
            current, given = Decimal(str(value)), Decimal(str(wanted))
            return (current > given) - (current < given)
        return None
    if isinstance(wanted, str) and isinstance(value, str):
        try:
            day, other = date.fromisoformat(value[:10]), date.fromisoformat(wanted)
        except ValueError:
            return None
        return (day > other) - (day < other)
    return None


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


PatternSubject = str | tuple[str, ...]
"""What a regular expression runs against: one text, or several, each on its own (it matches
if it matches one of them)."""


def pattern_subjects(
    rules: Sequence[Rule],
    document: Document,
    text: str | None,
    kept_facts: Sequence[DocumentFact] = (),
) -> dict[tuple[str, str, bool], PatternSubject]:
    """What each regular expression of `rules` runs against: the text, a field value (as
    text), or the values of the facts a condition looks at, each on its own as the text writes
    it on one line (`DocumentFact.shown`). Patterns without a subject (no text, no value, no
    fact) are left out."""
    subjects: dict[tuple[str, str, bool], PatternSubject] = {}
    conditions = {
        condition.target: condition
        for rule in rules
        for condition in rule.definition.all_conditions()
        if condition.field is ConditionField.FACT
    }
    for rule in rules:
        for target, pattern, case_sensitive in rule.definition.patterns():
            subject: PatternSubject | None
            if target == TEXT_TARGET:
                subject = text
            elif target in conditions:
                held = fact_values(conditions[target], kept_facts)
                subject = tuple(fact.shown for fact in held) or None
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
    referred: Mapping[UserId | None, tuple[DocumentTypeId | None, ...]] | None = None,
) -> list[Match]:
    """The rules whose conditions hold, in rule order. With `before` (a change): only those
    that did not hold before the change (they become true with it). `referred`: the types of
    the documents it refers to, by reader (`Facts.referred_types` of each rule, as its author
    may read them)."""
    found: list[Match] = []
    for rule in sorted(rules, key=lambda item: item.order):
        if referred is not None:
            seen = referred.get(rule.current.created_by, ())
            facts = replace(facts, referred_types=seen)
            before = None if before is None else replace(before, referred_types=seen)
        conditions = rule.definition.conditions
        if not evaluate(conditions, facts, definitions):
            continue
        if before is not None and evaluate(conditions, before, definitions):
            continue
        trusted = evaluate(conditions, facts, definitions, distrust=True) is True
        found.append(Match(rule, trusted, () if trusted else distrusted_fields(conditions, facts)))
    return found
