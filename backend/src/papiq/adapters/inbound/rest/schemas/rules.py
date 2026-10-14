"""Rules: definitions, versions, dry runs and applying a rule to existing documents.

Shape and types are checked here; operators by field and data type, values, patterns and the
actions a scope allows are checked by the core (`definition_from_json`), references by the
rule service."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from papiq.adapters.inbound.schemas import FieldJson, MoneyValue, RuleEffectOut, RuleNoteOut
from papiq.core.domain.json_value import JsonValue
from papiq.core.domain.rules import (
    ApplicationStatus,
    ConditionField,
    Operator,
    Rule,
    RuleApplication,
    RuleScope,
    RuleVersion,
    Trigger,
    definition_to_json,
)


class ConditionSchema(BaseModel):
    """`field` `op` `value`. Operators by field: contact, document_type: `is`, `in`, `present`,
    `missing`; tags: `contains` (this tag), `in` (one of), `present` (any), `missing` (none);
    channel: `is`, `in`; text: `contains`, `matches` (regular expression); document_date and
    number, amount, date fields: `is`, `gt`, `lt`, `present`, `missing`; text and link
    fields: `is`, `in`, `contains`, `matches`, `present`, `missing`; choice: `is`, `in`,
    `present`, `missing`; boolean: `is`, `present`, `missing`."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"field": "contact", "op": "is", "value": "01999d5e-3333-7c1e-b6a3-2f4d5e6f7a8b"},
                {
                    "field": "text",
                    "op": "matches",
                    "value": "Rechnung\\s+Nr",
                    "case_sensitive": True,
                },
            ]
        },
    )

    field: ConditionField
    op: Operator
    value: str | bool | MoneyValue | list[str] | None = Field(
        default=None,
        description=(
            "None for `present` and `missing`, a list for `in`, otherwise one value: an id, a "
            "channel, a text or pattern, a date `YYYY-MM-DD`, or a field value as in "
            "`fields` of a document."
        ),
    )
    field_id: UUID | None = Field(default=None, description="Only when `field` is `field`.")
    case_sensitive: bool = Field(
        default=False, description="For `matches` only; other comparisons ignore case."
    )


class AllGroup(BaseModel):
    """All items hold (and); `not` turns the result around."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    all: list["ConditionSchema | AllGroup | AnyGroup"] = Field(min_length=1, max_length=50)
    negate: bool = Field(default=False, alias="not")


class AnyGroup(BaseModel):
    """At least one item holds (or); `not` turns the result around."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    any: list["ConditionSchema | AllGroup | AnyGroup"] = Field(min_length=1, max_length=50)
    negate: bool = Field(default=False, alias="not")


class SetDrawerAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_drawer"]
    drawer_id: UUID = Field(description="A drawer the rule's owner may write to (user rules).")


class SetContactAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_contact"]
    contact_id: UUID


class SetDocumentTypeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_document_type"]
    document_type_id: UUID


TEMPLATE_DESCRIPTION = (
    "A Liquid template (`{{ value }}`, `{% if value %}…{% endif %}`, filters with `|`). Values: "
    "`title`, `filename` (the original's name without extension), `original_filename`, "
    "`contact`, `document_type`, `document_date`, `added`, `tags` (a list), `drawer`, `owner`, "
    "`channel`, `pages`, and `field.<key>` (`FieldOut.key`; an amount has `.amount` and "
    "`.currency`). Besides Liquid's filters: `datetime` (`format: 'MMMM yyyy'`), `currency`, "
    "`decimal`, in `PAPIQ_TEMPLATE_LOCALE`. Writing a missing value sets nothing (`| default: "
    "''` or `{% if %}` make it optional)."
)


class SetTitleAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_title"]
    template: str = Field(
        max_length=500,
        examples=["{{ contact }} {{ document_type }} {{ document_date | date: '%Y-%m' }}"],
        description=TEMPLATE_DESCRIPTION,
    )


class AddTagsAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["add_tags"]
    tag_ids: list[UUID] = Field(min_length=1, max_length=100)


class RemoveTagsAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["remove_tags"]
    tag_ids: list[UUID] = Field(min_length=1, max_length=100)


class SetFieldAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_field"]
    field_id: UUID
    value: FieldJson = Field(
        description="As the field's type has it; for a text field a template, as a title's."
    )


class ForceReviewAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["force_review"]
    reason: str = Field(
        max_length=500,
        examples=["check the contract term of {{ contact }}"],
        description="A template, as a title's; the review holds where it cannot be rendered.",
    )


ActionSchema = Annotated[
    SetDrawerAction
    | SetContactAction
    | SetDocumentTypeAction
    | SetTitleAction
    | AddTagsAction
    | RemoveTagsAction
    | SetFieldAction
    | ForceReviewAction,
    Field(discriminator="type"),
]


_RULE_EXAMPLE: dict[str, Any] = {
    "name": "Telekom to household",
    "priority": 100,
    "triggers": ["ingest", "change"],
    "conditions": {
        "all": [
            {"field": "contact", "op": "is", "value": "01999d5e-3333-7c1e-b6a3-2f4d5e6f7a8b"},
            {"field": "text", "op": "contains", "value": "Rechnung"},
        ]
    },
    "actions": [
        {"type": "set_drawer", "drawer_id": "01999d5e-5555-7c1e-b6a3-2f4d5e6f7a8b"},
        {"type": "add_tags", "tag_ids": ["01999d5e-2222-7c1e-b6a3-2f4d5e6f7a8b"]},
    ],
}


class RuleDefinitionIn(BaseModel):
    """The content of a rule; changing it makes a new version."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [_RULE_EXAMPLE]})

    name: str = Field(min_length=1, max_length=200)
    priority: int = Field(
        default=100,
        ge=0,
        le=1000,
        description=(
            "Higher first; the order of the log and of suggestions. Conflicts are never "
            "decided by priority."
        ),
    )
    triggers: list[Trigger] = Field(
        default_factory=lambda: list(Trigger),
        min_length=1,
        description="`ingest`: when a document arrives; `change`: when a person changes it.",
    )
    conditions: AllGroup | AnyGroup = Field(
        description="Nested at most 5 deep, at most 50 conditions."
    )
    actions: list[ActionSchema] = Field(min_length=1, max_length=20)

    def to_json(self) -> JsonValue:
        data: JsonValue = self.model_dump(mode="json", by_alias=True, exclude_defaults=True)
        return data


class RuleCreate(RuleDefinitionIn):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"scope": "user", **_RULE_EXAMPLE}]}
    )

    scope: RuleScope = Field(
        default=RuleScope.USER,
        description=(
            "`user`: the caller's rule, for their documents. `global` (admins): for every "
            "document, but only tags, fields and reviews."
        ),
    )

    def to_json(self) -> JsonValue:
        data: JsonValue = self.model_dump(
            mode="json", by_alias=True, exclude_defaults=True, exclude={"scope"}
        )
        return data


class RulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"enabled": False}]})

    enabled: bool


class _RuleDefinitionOut(BaseModel):
    name: str
    priority: int
    triggers: list[Trigger]
    conditions: AllGroup | AnyGroup
    actions: list[ActionSchema]


class RuleVersionOut(_RuleDefinitionOut):
    rule_id: UUID
    version: int = Field(description="Counts from 1; every change of the content adds one.")
    created_at: datetime
    created_by: UUID | None

    @classmethod
    def of(cls, version: RuleVersion) -> "RuleVersionOut":
        return cls.model_validate(
            {
                **definition_to_json(version.definition),
                "rule_id": version.rule_id,
                "version": version.number,
                "created_at": version.created_at,
                "created_by": version.created_by,
            }
        )


class RuleOut(_RuleDefinitionOut):
    id: UUID
    scope: RuleScope
    owner_id: UUID | None = Field(description="None for global rules.")
    version: int = Field(description="The current version.")
    enabled: bool
    disabled_reason: str | None = Field(
        description="Why the rule was disabled automatically, e.g. a contact it uses was deleted."
    )
    managed_by_document_type_id: UUID | None = Field(
        description="The document type whose title pattern this rule is: it follows the type "
        "and is read-only (changing, switching or deleting it is 409); None for other rules."
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, rule: Rule) -> "RuleOut":
        return cls.model_validate(
            {
                **definition_to_json(rule.definition),
                "id": rule.id,
                "scope": rule.scope,
                "owner_id": rule.owner_id,
                "version": rule.current.number,
                "enabled": rule.enabled,
                "disabled_reason": rule.disabled_reason,
                "managed_by_document_type_id": rule.managed_by,
                "created_at": rule.created_at,
                "updated_at": rule.updated_at,
            }
        )


class ApplyPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"limit": 50}]})

    cursor: str | None = Field(default=None, max_length=64, description="`next_cursor`.")
    limit: int = Field(default=50, ge=1, le=200)


class ApplyPreviewItemOut(BaseModel):
    document_id: UUID
    title: str
    changes: list[RuleEffectOut] = Field(description="What the rule would change.")
    conflicts: list[RuleNoteOut] = Field(
        description=(
            "Fields that have another value: changed only if the document is in `accept_conflicts`."
        )
    )
    notes: list[RuleNoteOut] = Field(description="Other actions that would not act, and why.")


class ApplyPreviewOut(BaseModel):
    rule_id: UUID
    version: int = Field(description="The version the preview used; pass it to apply.")
    items: list[ApplyPreviewItemOut]
    next_cursor: str | None = Field(
        description=(
            "Pass as `cursor` for the next page; null when all documents were looked at. A page "
            "may hold fewer items than `limit` and still have a next one."
        )
    )


class ApplyRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "version": 2,
                    "document_ids": ["01999d5e-8a7f-7c1e-b6a3-2f4d5e6f7a8b"],
                    "accept_conflicts": [],
                }
            ]
        },
    )

    version: int = Field(ge=1, description="The rule version to apply (from the preview).")
    document_ids: list[UUID] = Field(min_length=1, max_length=100_000)
    accept_conflicts: list[UUID] = Field(
        default_factory=list,
        description="Selected documents where the rule's value replaces a different one.",
    )


class SkippedOut(BaseModel):
    document_id: UUID
    reason: str


class RuleApplicationOut(BaseModel):
    id: UUID
    rule_id: UUID
    version: int
    status: ApplicationStatus
    total: int = Field(description="Selected documents.")
    done: int = Field(description="Documents worked through so far.")
    applied: int
    unchanged: int = Field(description="The rule no longer holds or changes nothing.")
    skipped: list[SkippedOut] = Field(
        description="Not changed: conflicts not accepted, no longer writable, ..."
    )
    error: str | None
    created_at: datetime
    finished_at: datetime | None

    @classmethod
    def of(cls, application: RuleApplication) -> "RuleApplicationOut":
        return cls(
            id=application.id,
            rule_id=application.rule_id,
            version=application.rule_version,
            status=application.status,
            total=len(application.documents),
            done=application.position,
            applied=application.applied,
            unchanged=application.unchanged,
            skipped=[
                SkippedOut(document_id=id, reason=reason) for id, reason in application.skipped
            ],
            error=application.error,
            created_at=application.created_at,
            finished_at=application.finished_at,
        )
