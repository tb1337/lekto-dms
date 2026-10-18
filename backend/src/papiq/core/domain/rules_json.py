"""Rule definitions as JSON, as they are stored and as the API takes them
(`definition_to_json`, `definition_from_json`). Reading names the place of what does not fit
(`actions[0].type: unknown action 'delete'`); values in conditions and actions keep their JSON
form (see `rules`).
"""

from collections.abc import Mapping
from enum import StrEnum

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.ids import ContactId, DocumentTypeId, FieldId, SpaceId, TagId
from papiq.core.domain.json_value import JsonObject, JsonValue, require_object, require_uuid
from papiq.core.domain.rules import (
    DEFAULT_PRIORITY,
    Action,
    AddTags,
    Condition,
    ConditionField,
    ForceReview,
    Group,
    GroupMode,
    Operator,
    RemoveTags,
    RuleDefinition,
    SetContact,
    SetDocumentType,
    SetField,
    SetSpace,
    SetTitle,
    SetTopic,
    Trigger,
)


def definition_to_json(definition: RuleDefinition) -> JsonObject:
    return {
        "name": definition.name,
        "priority": definition.priority,
        "triggers": _strings(sorted(trigger.value for trigger in definition.triggers)),
        "conditions": group_to_json(definition.conditions),
        "actions": [action_to_json(action) for action in definition.actions],
    }


def group_to_json(group: Group) -> JsonObject:
    data: JsonObject = {
        group.mode: [
            group_to_json(item) if isinstance(item, Group) else condition_to_json(item)
            for item in group.items
        ]
    }
    if group.negate:
        data["not"] = True
    return data


def condition_to_json(condition: Condition) -> JsonObject:
    data: JsonObject = {"field": condition.field.value, "op": condition.op.value}
    if condition.field_id is not None:
        data["field_id"] = str(condition.field_id)
    if condition.value is not None:
        data["value"] = condition.value
    if condition.case_sensitive:
        data["case_sensitive"] = True
    return data


def action_to_json(action: Action) -> JsonObject:
    match action:
        case SetSpace(space_id=space):
            return {"type": action.type, "space_id": str(space)}
        case SetContact(contact_id=contact):
            return {"type": action.type, "contact_id": str(contact)}
        case SetDocumentType(document_type_id=document_type):
            return {"type": action.type, "document_type_id": str(document_type)}
        case SetTopic(topic_id=topic):
            return {"type": action.type, "topic_id": str(topic)}
        case SetTitle(template=template):
            return {"type": action.type, "template": template}
        case AddTags(tag_ids=tags) | RemoveTags(tag_ids=tags):
            return {"type": action.type, "tag_ids": _strings(sorted(str(tag) for tag in tags))}
        case SetField(field_id=field, value=value):
            return {"type": action.type, "field_id": str(field), "value": value}
        case ForceReview(reason=reason):
            return {"type": action.type, "reason": reason}


def definition_from_json(data: JsonValue) -> RuleDefinition:
    """ValidationError, naming the place, if `data` is no valid definition."""
    object_ = require_object(data, "rule")
    _only(object_, {"name", "priority", "triggers", "conditions", "actions"}, "rule")
    triggers = object_.get("triggers", [trigger.value for trigger in Trigger])
    if not isinstance(triggers, list):
        raise ValidationError("triggers: expected a list")
    actions = object_.get("actions")
    if not isinstance(actions, list):
        raise ValidationError("actions: expected a list")
    priority = object_.get("priority", DEFAULT_PRIORITY)
    if not isinstance(priority, int):
        raise ValidationError("priority: expected a whole number")
    name = object_.get("name")
    if not isinstance(name, str):
        raise ValidationError("name: expected text")
    return RuleDefinition(
        name=name,
        priority=priority,
        triggers=frozenset(_enum(Trigger, item, "triggers") for item in triggers),
        conditions=group_from_json(object_.get("conditions"), "conditions"),
        actions=tuple(
            action_from_json(item, f"actions[{index}]") for index, item in enumerate(actions)
        ),
    )


def group_from_json(data: JsonValue, where: str = "conditions") -> Group:
    object_ = require_object(data, where)
    modes = [mode for mode in ("all", "any") if mode in object_]
    if len(modes) != 1:
        raise ValidationError(f"{where}: a group has exactly one of 'all' and 'any'")
    mode: GroupMode = "all" if modes[0] == "all" else "any"
    _only(object_, {mode, "not"}, where)
    negate = object_.get("not", False)
    if not isinstance(negate, bool):
        raise ValidationError(f"{where}.not: expected true or false")
    items = object_[mode]
    if not isinstance(items, list):
        raise ValidationError(f"{where}.{mode}: expected a list")
    parsed: list[Condition | Group] = []
    for index, item in enumerate(items):
        place = f"{where}.{mode}[{index}]"
        if isinstance(item, dict) and ("all" in item or "any" in item):
            parsed.append(group_from_json(item, place))
        else:
            parsed.append(condition_from_json(item, place))
    try:
        return Group(mode=mode, items=tuple(parsed), negate=negate)
    except ValidationError as error:
        raise ValidationError(f"{where}: {error}") from None


def condition_from_json(data: JsonValue, where: str = "condition") -> Condition:
    object_ = require_object(data, where)
    _only(object_, {"field", "op", "value", "field_id", "case_sensitive"}, where)
    field_id = object_.get("field_id")
    case_sensitive = object_.get("case_sensitive", False)
    if not isinstance(case_sensitive, bool):
        raise ValidationError(f"{where}.case_sensitive: expected true or false")
    try:
        return Condition(
            field=_enum(ConditionField, object_.get("field"), f"{where}.field"),
            op=_enum(Operator, object_.get("op"), f"{where}.op"),
            value=object_.get("value"),
            field_id=None if field_id is None else FieldId(require_uuid(field_id, "field_id")),
            case_sensitive=case_sensitive,
        )
    except ValidationError as error:
        raise ValidationError(f"{where}: {error}") from None


def action_from_json(data: JsonValue, where: str = "action") -> Action:
    object_ = require_object(data, where)
    kind = object_.get("type")
    try:
        match kind:
            case "set_space":
                _only(object_, {"type", "space_id"}, where)
                return SetSpace(SpaceId(require_uuid(object_.get("space_id"), "space_id")))
            case "set_contact":
                _only(object_, {"type", "contact_id"}, where)
                return SetContact(ContactId(require_uuid(object_.get("contact_id"), "contact_id")))
            case "set_document_type":
                _only(object_, {"type", "document_type_id"}, where)
                type_id = require_uuid(object_.get("document_type_id"), "document_type_id")
                return SetDocumentType(DocumentTypeId(type_id))
            case "set_topic":
                _only(object_, {"type", "topic_id"}, where)
                return SetTopic(TagId(require_uuid(object_.get("topic_id"), "topic_id")))
            case "set_title":
                _only(object_, {"type", "template"}, where)
                template = object_.get("template")
                if not isinstance(template, str):
                    raise ValidationError("template: expected text")
                return SetTitle(template)
            case "add_tags" | "remove_tags":
                _only(object_, {"type", "tag_ids"}, where)
                ids = object_.get("tag_ids")
                if not isinstance(ids, list):
                    raise ValidationError("tag_ids: expected a list")
                tags = frozenset(TagId(require_uuid(item, "tag_ids")) for item in ids)
                return AddTags(tags) if kind == "add_tags" else RemoveTags(tags)
            case "set_field":
                _only(object_, {"type", "field_id", "value"}, where)
                return SetField(
                    FieldId(require_uuid(object_.get("field_id"), "field_id")),
                    object_.get("value"),
                )
            case "force_review":
                _only(object_, {"type", "reason"}, where)
                reason = object_.get("reason")
                if not isinstance(reason, str):
                    raise ValidationError("reason: expected text")
                return ForceReview(reason)
    except ValidationError as error:
        raise ValidationError(f"{where}: {error}") from None
    raise ValidationError(f"{where}.type: unknown action {kind!r}")


# --- helpers ----------------------------------------------------------------------------------


def _strings(items: list[str]) -> list[JsonValue]:
    return list(items)


def _only(data: Mapping[str, JsonValue], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValidationError(f"{where}: unknown key '{unknown[0]}'")


def _enum[E: StrEnum](kind: type[E], value: JsonValue, where: str) -> E:
    try:
        return kind(str(value))
    except ValueError:
        raise ValidationError(f"{where}: unknown value {value!r}") from None
