"""A rule's steps: asking a webhook and condition steps, what a definition allows of them, their
JSON, and conditions on what a step brought."""

from typing import Any

import pytest

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import TagId, WebhookId, new_id
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.rule_conditions import Facts, evaluate
from lekto.core.domain.rules import (
    AddTags,
    AskWebhook,
    Condition,
    ConditionField,
    Group,
    Missing,
    Operator,
    RuleDefinition,
    StepCondition,
    Trigger,
)
from lekto.core.domain.rules_json import definition_from_json, definition_to_json
from tests import builders

HOOK = WebhookId(new_id())
TAG = TagId(new_id())
ANY = Group(
    mode="all", items=(Condition(field=ConditionField.CHANNEL, op=Operator.IS, value="api"),)
)


def on(path: str, op: Operator, value: JsonValue = None) -> Group:
    return Group(
        mode="all", items=(Condition(field=ConditionField.STEP, op=op, value=value, path=path),)
    )


def definition(
    *steps: object, triggers: frozenset[Trigger] = frozenset({Trigger.INGEST})
) -> RuleDefinition:
    return RuleDefinition(
        name="Invoices",
        conditions=ANY,
        actions=tuple(steps),  # type: ignore[arg-type]
        triggers=triggers,
    )


def test_a_rule_asks_checks_the_answer_and_acts() -> None:
    rule = definition(
        AskWebhook("accounting", HOOK, timeout_seconds=120, missing=Missing.YELLOW),
        StepCondition(on("accounting.paid", Operator.IS, True)),
        AddTags(frozenset({TAG})),
    )
    assert [step.name for step in rule.asks] == ["accounting"]
    assert rule.has_steps and rule.references().webhooks == {HOOK}
    data = definition_to_json(rule)
    assert data["actions"] == [
        {
            "type": "ask_webhook",
            "name": "accounting",
            "webhook_id": str(HOOK),
            "timeout_seconds": 120,
            "missing": "yellow",
        },
        {
            "type": "condition",
            "conditions": {
                "all": [{"field": "step", "op": "is", "value": True, "path": "accounting.paid"}]
            },
        },
        {"type": "add_tags", "tag_ids": [str(TAG)]},
    ]
    assert definition_from_json(data) == rule


def test_an_ask_step_takes_defaults() -> None:
    data: dict[str, Any] = definition_to_json(definition(AskWebhook("a", HOOK)))
    data["actions"] = [{"type": "ask_webhook", "name": "a", "webhook_id": str(HOOK)}]
    (step,) = definition_from_json(data).asks
    assert (step.timeout_seconds, step.missing) == (300, Missing.RED)


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda: AskWebhook("Accounting", HOOK), "small letters"),
        (lambda: AskWebhook("a" * 51, HOOK), "small letters"),
        (lambda: AskWebhook("a", HOOK, timeout_seconds=10), "30 seconds"),
        (lambda: on("1st.paid", Operator.IS, 1), "path"),
        (lambda: on("a.paid", Operator.GT, "soon"), "date"),
        (lambda: on("a.paid", Operator.CONTAINS, True), "true or false"),
        (lambda: Condition(field=ConditionField.STEP, op=Operator.IS, value=1), "path"),
        (
            lambda: Condition(field=ConditionField.TEXT, op=Operator.CONTAINS, value="x", path="a"),
            "path",
        ),
    ],
)
def test_steps_and_step_conditions_are_checked(make: Any, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make()


@pytest.mark.parametrize(
    ("steps", "triggers", "message"),
    [
        ((AskWebhook("a", HOOK),), frozenset(Trigger), "on arrival only"),
        ((StepCondition(ANY),), frozenset({Trigger.INGEST}), "at least one action"),
        (
            (StepCondition(on("a.paid", Operator.PRESENT)), AskWebhook("a", HOOK)),
            frozenset({Trigger.INGEST}),
            "no step before it is named 'a'",
        ),
        (
            (AskWebhook("a", HOOK), AskWebhook("a", HOOK)),
            frozenset({Trigger.INGEST}),
            "step a",
        ),
    ],
)
def test_a_definition_keeps_steps_in_order(
    steps: tuple[object, ...], triggers: frozenset[Trigger], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        definition(*steps, triggers=triggers)


def test_the_head_has_no_condition_on_steps() -> None:
    with pytest.raises(ValidationError, match="belongs in a condition step"):
        RuleDefinition(
            name="x", conditions=on("a.b", Operator.PRESENT), actions=(AskWebhook("a", HOOK),)
        )


def facts(steps: dict[str, JsonValue]) -> Facts:
    return Facts.of(builders.received(), steps=steps)


ANSWER: dict[str, JsonValue] = {
    "a": {
        "paid": True,
        "amount": 12.5,
        "status": "Booked",
        "due": "2026-11-01",
        "items": ["x", 2],
        "none": None,
    }
}


@pytest.mark.parametrize(
    ("path", "op", "value", "holds"),
    [
        ("a.paid", Operator.IS, True, True),
        ("a.paid", Operator.IS, 1, False),
        ("a.amount", Operator.IS, 12.50, True),
        ("a.amount", Operator.GT, 12, True),
        ("a.amount", Operator.LT, 12, False),
        ("a.amount", Operator.IS, "12.5", False),
        ("a.status", Operator.IS, "booked", True),
        ("a.status", Operator.IN, ["open", "BOOKED"], True),
        ("a.status", Operator.CONTAINS, "ook", True),
        ("a.due", Operator.GT, "2026-10-31", True),
        ("a.due", Operator.LT, "2026-10-31", False),
        ("a.items", Operator.CONTAINS, "x", True),
        ("a.items.1", Operator.IS, 2, True),
        ("a.items.5", Operator.PRESENT, None, False),
        ("a.none", Operator.MISSING, None, True),
        ("a.gone", Operator.MISSING, None, True),
        ("b", Operator.PRESENT, None, False),
        ("a.status.deeper", Operator.PRESENT, None, False),
    ],
)
def test_a_condition_on_what_a_step_brought(
    path: str, op: Operator, value: JsonValue, holds: bool
) -> None:
    assert evaluate(on(path, op, value), facts(ANSWER), {}) is holds
