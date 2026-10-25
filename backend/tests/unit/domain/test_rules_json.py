"""The JSON form of rule definitions: round trip, shape, defaults, and errors that name the
place."""

import json

import pytest

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import (
    ContactId,
    DocumentTypeId,
    FieldId,
    SpaceId,
    TagId,
    WebhookId,
    new_id,
)
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.rules import (
    AddTags,
    Condition,
    ConditionField,
    ForceReview,
    Group,
    Operator,
    RemoveTags,
    RuleDefinition,
    SendWebhook,
    SetContact,
    SetDocumentType,
    SetField,
    SetSpace,
    SetTitle,
    Trigger,
)
from lekto.core.domain.rules_json import definition_from_json, definition_to_json

CONTACT = ContactId(new_id())
TYPE = DocumentTypeId(new_id())
TAG = TagId(new_id())
OTHER_TAG = TagId(new_id())
SPACE = SpaceId(new_id())
WEBHOOK = WebhookId(new_id())
FIELD = FieldId(new_id())


def full_definition() -> RuleDefinition:
    return RuleDefinition(
        name="Everything",
        priority=250,
        triggers=frozenset({Trigger.INGEST}),
        conditions=Group(
            mode="all",
            items=(
                Condition(field=ConditionField.CONTACT, op=Operator.IS, value=str(CONTACT)),
                Condition(field=ConditionField.DOCUMENT_TYPE, op=Operator.IN, value=[str(TYPE)]),
                Condition(field=ConditionField.TAGS, op=Operator.CONTAINS, value=str(TAG)),
                Condition(field=ConditionField.TAGS, op=Operator.MISSING),
                Condition(field=ConditionField.CHANNEL, op=Operator.IN, value=["web", "api"]),
                Condition(field=ConditionField.DOCUMENT_DATE, op=Operator.GT, value="2026-01-01"),
                Condition(
                    field=ConditionField.TEXT,
                    op=Operator.MATCHES,
                    value=r"Rechnung\s+Nr",
                    case_sensitive=True,
                ),
                Group(
                    mode="any",
                    negate=True,
                    items=(
                        Condition(field=ConditionField.TEXT, op=Operator.CONTAINS, value="Mahnung"),
                        Group(
                            mode="all",
                            items=(
                                Condition(
                                    field=ConditionField.FIELD,
                                    op=Operator.GT,
                                    value={"amount": "100.00", "currency": "EUR"},
                                    field_id=FIELD,
                                ),
                                Condition(
                                    field=ConditionField.FIELD,
                                    op=Operator.PRESENT,
                                    field_id=FIELD,
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
        actions=(
            SetSpace(SPACE),
            SetContact(CONTACT),
            SetDocumentType(TYPE),
            SetTitle("{contact} {document_date}"),
            AddTags(frozenset({TAG, OTHER_TAG})),
            RemoveTags(frozenset({OTHER_TAG})),
            SetField(FIELD, {"amount": "12.50", "currency": "EUR"}),
            ForceReview("check the amount"),
            SendWebhook(WEBHOOK),
        ),
    )


def test_definition_json_round_trip() -> None:
    original = full_definition()

    data = json.loads(json.dumps(definition_to_json(original)))

    assert definition_from_json(data) == original


def test_definition_json_shape() -> None:
    data = definition_to_json(full_definition())

    assert data["name"] == "Everything"
    assert data["priority"] == 250
    assert data["triggers"] == ["ingest"]
    conditions = data["conditions"]
    assert isinstance(conditions, dict) and set(conditions) == {"all"}
    items = conditions["all"]
    assert isinstance(items, list)
    assert items[3] == {"field": "tags", "op": "missing"}  # no value key
    assert items[6] == {
        "field": "text",
        "op": "matches",
        "value": r"Rechnung\s+Nr",
        "case_sensitive": True,
    }
    negated = items[7]
    assert isinstance(negated, dict) and negated["not"] is True and "any" in negated
    inner = negated["any"]
    assert isinstance(inner, list) and inner[0] == {
        "field": "text",
        "op": "contains",
        "value": "Mahnung",
    }
    assert {"field": "field", "op": "present", "field_id": str(FIELD)} in (
        inner[1]["all"] if isinstance(inner[1], dict) and isinstance(inner[1]["all"], list) else []
    )
    actions = data["actions"]
    assert isinstance(actions, list)
    assert [action["type"] for action in actions if isinstance(action, dict)] == [
        "set_space",
        "set_contact",
        "set_document_type",
        "set_title",
        "add_tags",
        "remove_tags",
        "set_field",
        "force_review",
        "send_webhook",
    ]
    assert actions[4] == {"type": "add_tags", "tag_ids": sorted([str(TAG), str(OTHER_TAG)])}


def test_definition_json_defaults() -> None:
    parsed = definition_from_json(
        {
            "name": "Defaults",
            "conditions": {"any": [{"field": "channel", "op": "is", "value": "web"}]},
            "actions": [{"type": "force_review", "reason": "look"}],
        }
    )

    assert parsed.priority == 100
    assert parsed.triggers == frozenset(Trigger)
    assert parsed.conditions == Group(
        mode="any",
        items=(Condition(field=ConditionField.CHANNEL, op=Operator.IS, value="web"),),
    )


CHANNEL_JSON: JsonObject = {"field": "channel", "op": "is", "value": "web"}
VALID_RULE: JsonObject = {
    "name": "R",
    "conditions": {"all": [CHANNEL_JSON]},
    "actions": [{"type": "force_review", "reason": "look"}],
}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"owner": "x"}, "rule: unknown key 'owner'"),
        ({"name": None}, "name: expected text"),
        ({"priority": "high"}, "priority: expected a whole number"),
        ({"priority": 1.5}, "priority: expected a whole number"),
        ({"triggers": "ingest"}, "triggers: expected a list"),
        ({"triggers": ["upload"]}, "triggers: unknown value 'upload'"),
        ({"actions": {"type": "force_review"}}, "actions: expected a list"),
        ({"actions": [{"type": "delete"}]}, r"actions\[0\].type: unknown action 'delete'"),
        (
            {"actions": [{"type": "set_contact", "contact_id": "nope"}]},
            r"actions\[0\]: contact_id: 'nope' is no id",
        ),
        (
            {"actions": [{"type": "add_tags", "tag_ids": str(TAG)}]},
            r"actions\[0\]: tag_ids: expected a list",
        ),
        (
            {"actions": [{"type": "set_title", "template": "x", "extra": 1}]},
            r"actions\[0\]: unknown key 'extra'",
        ),
        ({"conditions": []}, "conditions: expected an object"),
        (
            {"conditions": {"all": [CHANNEL_JSON], "any": [CHANNEL_JSON]}},
            "conditions: a group has exactly one of 'all' and 'any'",
        ),
        ({"conditions": {"all": []}}, "conditions: a group needs at least one condition"),
        ({"conditions": {"all": "x"}}, r"conditions.all: expected a list"),
        (
            {"conditions": {"all": [CHANNEL_JSON], "not": 1}},
            "conditions.not: expected true or false",
        ),
        (
            {"conditions": {"all": [{"any": [{"field": "text", "op": "is", "value": "x"}]}]}},
            r"conditions.all\[0\].any\[0\]: operator 'is' does not apply to text",
        ),
    ],
)
def test_definition_json_errors_name_the_place(change: JsonObject, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        definition_from_json({**VALID_RULE, **change})


def test_definition_from_json_needs_an_object() -> None:
    with pytest.raises(ValidationError, match="rule: expected an object"):
        definition_from_json([])
