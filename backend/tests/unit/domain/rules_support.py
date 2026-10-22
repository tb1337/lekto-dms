"""What the tests of the rule conditions and of the rule planner share: fixed ids, spaces,
field definitions, tag trees, and helpers that build conditions, rules, documents and
situations."""

import itertools
from datetime import timedelta
from typing import Any
from uuid import UUID

from lekto.core.domain.documents import Document
from lekto.core.domain.fields import FieldDefinition, FieldType
from lekto.core.domain.ids import ContactId, DocumentTypeId, FieldId, SpaceId, TagId, UserId
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.master_data import Tag, TagScope
from lekto.core.domain.rule_conditions import Facts, Taxonomy, matches
from lekto.core.domain.rule_planner import Mode, RulePlan, Situation, SpaceTarget, plan
from lekto.core.domain.rules import (
    Action,
    Condition,
    ConditionField,
    Group,
    Operator,
    Rule,
    RuleDefinition,
    RuleScope,
)
from lekto.core.domain.tag_tree import TagTree
from tests import builders
from tests.builders import NOW


def _fixed(number: int) -> UUID:
    """A fixed id, so parametrized test ids are the same in every xdist worker."""
    return UUID(f"00000000-0000-7000-8000-{number:012d}")


OWNER = UserId(_fixed(1))  # who uploads the documents and saves the rules
STRANGER = UserId(_fixed(2))
DEFAULT = SpaceId(_fixed(3))  # OWNER's personal space, where the documents lie
OWN = SpaceId(_fixed(4))  # OWNER edits it, nobody else is a member
SHARED = SpaceId(_fixed(5))  # OWNER edits it, others are members too
READ_ONLY = SpaceId(_fixed(6))  # OWNER only reads it
THEIRS = SpaceId(_fixed(14))  # STRANGER's personal space
SPACES = {
    OWN: SpaceTarget("Taxes", filers=frozenset({OWNER}), personal=False, widens=False),
    SHARED: SpaceTarget("Family", filers=frozenset({OWNER}), personal=False, widens=True),
    READ_ONLY: SpaceTarget("Boss", filers=frozenset({STRANGER}), personal=False, widens=True),
    THEIRS: SpaceTarget("stranger", filers=frozenset({STRANGER}), personal=True, widens=True),
}
ACME, BETA = ContactId(_fixed(7)), ContactId(_fixed(8))
INVOICE, LETTER = DocumentTypeId(_fixed(9)), DocumentTypeId(_fixed(10))
PAID, OPEN, URGENT = TagId(_fixed(11)), TagId(_fixed(12)), TagId(_fixed(13))
EXISTING = frozenset({ACME, BETA, INVOICE, LETTER, PAID, OPEN, URGENT})
NAMES: dict[object, str] = {ACME: "ACME GmbH", BETA: "Beta AG", INVOICE: "Invoice"}


def cond(
    field: ConditionField,
    op: Operator,
    value: JsonValue = None,
    *,
    field_id: FieldId | None = None,
    case_sensitive: bool = False,
) -> Condition:
    return Condition(
        field=field, op=op, value=value, field_id=field_id, case_sensitive=case_sensitive
    )


def all_(*items: Condition | Group, negate: bool = False) -> Group:
    return Group(mode="all", items=items, negate=negate)


def any_(*items: Condition | Group, negate: bool = False) -> Group:
    return Group(mode="any", items=items, negate=negate)


IS_API = cond(ConditionField.CHANNEL, Operator.IS, "api")  # true for documents of `doc()`
IS_WEB = cond(ConditionField.CHANNEL, Operator.IS, "web")  # false for them
ALWAYS = all_(IS_API)
FROM_ACME = all_(cond(ConditionField.CONTACT, Operator.IS, str(ACME)))

_numbers = itertools.count(1)


def rule(
    *actions: Action,
    when: Group = ALWAYS,
    priority: int = 100,
    scope: RuleScope = RuleScope.SPACE,
    space: SpaceId = DEFAULT,
    by: UserId = OWNER,
    name: str | None = None,
) -> Rule:
    """A rule (of DEFAULT, the documents' space, unless global), saved by `by`; each is
    created a minute after the previous one."""
    number = next(_numbers)
    return Rule.create(
        scope=scope,
        space_id=None if scope is RuleScope.GLOBAL else space,
        definition=RuleDefinition(
            name=name or f"rule {number}", conditions=when, actions=actions, priority=priority
        ),
        by=by,
        now=NOW + timedelta(minutes=number),
    )


def doc(**fields: Any) -> Document:
    """A document OWNER uploaded into their personal space, from `Rechnung 2026.pdf`, via the
    API."""
    document = builders.document(OWNER, DEFAULT, filename="Rechnung 2026.pdf")
    for name, value in fields.items():
        setattr(document, name, value)
    return document


def situation(document: Document, mode: Mode = Mode.INGEST, **fields: Any) -> Situation:
    values: dict[str, Any] = {
        "in_personal_space": True,
        "definitions": {},
        "spaces": SPACES,
        "existing": EXISTING,
        "names": NAMES,
        "render": builders.TEMPLATES.render,
    }
    if mode is Mode.RETROACTIVE:
        values["applier"] = OWNER  # who applies the rules to existing documents
    values.update(fields)
    return Situation(mode=mode, document=document, **values)


def run(
    rules: list[Rule], where: Situation, *, facts: Facts | None = None, before: Facts | None = None
) -> RulePlan:
    """Match `rules` against the document and plan their change."""
    found = matches(rules, facts or Facts.of(where.document), where.definitions, before=before)
    return plan(found, where)


def notes(result: RulePlan) -> list[tuple[str, str]]:
    return [(note.field, note.kind) for report in result.reports for note in report.notes]


def check(result: RulePlan, field: str) -> Any:
    return next(item for item in result.checks if item.field == field)


def check_or_none(result: RulePlan, field: str) -> Any:
    return next((item for item in result.checks if item.field == field), None)


def field(data_type: FieldType, *choices: str) -> FieldDefinition:
    return FieldDefinition.create(
        name=data_type.value, data_type=data_type, now=NOW, choices=choices
    )


AMOUNT = field(FieldType.AMOUNT)
DUE = field(FieldType.DATE)
REFERENCE = field(FieldType.TEXT)
INTERVAL = field(FieldType.CHOICE, "monthly", "yearly", "weekly")
COUNT = field(FieldType.NUMBER)
PAID_FLAG = field(FieldType.BOOLEAN)
PORTAL = field(FieldType.LINK)
SPAN = field(FieldType.PERIOD)
DEFINITIONS = {
    item.id: item for item in (AMOUNT, DUE, REFERENCE, INTERVAL, COUNT, PAID_FLAG, PORTAL, SPAN)
}


def tagged() -> tuple[dict[str, Tag], Taxonomy]:
    """Insurance with Health (with Dental); the contact group Insurer with Health insurer,
    whose member is ACME; the type group Bills, whose member is INVOICE."""
    insurance = Tag.create(name="Insurance", now=NOW)
    health = Tag.create(name="Health", now=NOW, parent_id=insurance.id)
    dental = Tag.create(name="Dental", now=NOW, parent_id=health.id)
    insurer = Tag.create(name="Insurer", now=NOW, scope=TagScope.CONTACT)
    health_insurer = Tag.create(
        name="Health insurer", now=NOW, scope=TagScope.CONTACT, parent_id=insurer.id
    )
    bills = Tag.create(name="Bills", now=NOW, scope=TagScope.DOCUMENT_TYPE)
    tags = {
        "insurance": insurance,
        "health": health,
        "dental": dental,
        "insurer": insurer,
        "health_insurer": health_insurer,
        "bills": bills,
    }
    groups = {ACME: frozenset({health_insurer.id}), INVOICE: frozenset({bills.id})}
    by_id: dict[UUID, frozenset[TagId]] = dict(groups)
    return tags, Taxonomy(TagTree.of(tags.values()), by_id)


def topics() -> tuple[dict[str, Tag], Taxonomy]:
    """Health below Insurance, and Work; ACME enables Health and Work, BETA Work."""
    insurance = Tag.create(name="Insurance", now=NOW, scope=TagScope.TOPIC)
    health = Tag.create(name="Health", now=NOW, scope=TagScope.TOPIC, parent_id=insurance.id)
    work = Tag.create(name="Work", now=NOW, scope=TagScope.TOPIC)
    tags = {"insurance": insurance, "health": health, "work": work}
    topics: dict[UUID, frozenset[TagId]] = {
        ACME: frozenset({health.id, work.id}),
        BETA: frozenset({work.id}),
    }
    return tags, Taxonomy(TagTree.of(tags.values()), topics=topics)
