"""Rules: definitions, versions, dry runs and applying a rule to existing documents.

Shape and types are checked here; operators by field and data type, values, patterns and the
actions a scope allows are checked by the core (`definition_from_json`), references by the
rule service."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.adapters.inbound.schemas import (
    FieldJson,
    MoneyValue,
    PeriodValue,
    ReasonOut,
    RuleEffectOut,
    RuleNoteOut,
    RuleReportOut,
)
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.rules import (
    DEFAULT_PRIORITY,
    MAX_ACTIONS,
    MAX_CONDITIONS,
    MAX_DEPTH,
    MAX_LIST,
    MAX_PRIORITY,
    MAX_TEXT,
    MIN_PRIORITY,
    ApplicationStatus,
    ConditionField,
    Operator,
    Rule,
    RuleApplication,
    RuleScope,
    RuleVersion,
    Trigger,
)
from lekto.core.domain.rules_json import definition_to_json
from lekto.core.domain.validation import MAX_NAME
from lekto.core.ports.repository import PAGE_LIMIT, PAGE_SIZE
from lekto.core.services.rules.changes import ArrivalStep
from lekto.core.services.rules.retroactive import Outcome


class ConditionSchema(BaseModel):
    """`field` `op` `value`. Operators by field: contact, document_type: `is`, `in`, `present`,
    `missing`; topic: the same, where a topic matches the ones below it too (unknown while the
    model set it and nobody confirmed it); tags (document tags), contact_group (the groups of
    the document's contact),
    document_type_group (those of its type): `contains` (this one), `in` (one of), `present`
    (any), `missing` (none), where a tag or group matches the ones below it too; channel:
    `is`, `in`; text: `contains`, `matches` (regular expression); document_date and
    number, amount, date fields: `is`, `gt`, `lt`, `present`, `missing`; text and link
    fields: `is`, `in`, `contains`, `matches`, `present`, `missing`; choice: `is`, `in`,
    `present`, `missing`; boolean: `is`, `present`, `missing`; period fields: `is`,
    `overlaps` (shares a day with the given period), `gt` (starts after the date), `lt` (ends
    before the date), `present`, `missing`."""

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
    value: str | bool | MoneyValue | PeriodValue | list[str] | None = Field(
        default=None,
        description=(
            "None for `present` and `missing`, a list for `in`, otherwise one value: an id, a "
            "channel, a text or pattern, a date `YYYY-MM-DD` (also for `gt` and `lt` of a "
            "period field), or a field value as in `fields` of a document."
        ),
    )
    field_id: UUID | None = Field(default=None, description="Only when `field` is `field`.")
    case_sensitive: bool = Field(
        default=False, description="For `matches` only; other comparisons ignore case."
    )


class AllGroup(BaseModel):
    """All items hold (and); `not` turns the result around."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    all: list["ConditionSchema | AllGroup | AnyGroup"] = Field(
        min_length=1, max_length=MAX_CONDITIONS
    )
    negate: bool = Field(default=False, alias="not")


class AnyGroup(BaseModel):
    """At least one item holds (or); `not` turns the result around."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    any: list["ConditionSchema | AllGroup | AnyGroup"] = Field(
        min_length=1, max_length=MAX_CONDITIONS
    )
    negate: bool = Field(default=False, alias="not")


class SetSpaceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_space"]
    space_id: UUID = Field(
        description=(
            "A space whoever saves the rule may file into, or another user's personal space "
            "(handing the document over)."
        )
    )


class SetContactAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_contact"]
    contact_id: UUID


class SetDocumentTypeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_document_type"]
    document_type_id: UUID


class SetTopicAction(BaseModel):
    """User rules only, as contact and type. Applied only if the document's contact (as the
    rules leave it) enables the topic; otherwise skipped and noted."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["set_topic"]
    topic_id: UUID = Field(description="A tag of scope `topic`.")


TEMPLATES_GUIDE = "https://github.com/tb1337/lekto-dms/blob/main/docs/templates.md"
"""The documentation of templates, linked from the API and the template editor."""

TEMPLATE_DESCRIPTION = (
    "A Liquid template (`{{ value }}`, `{% if value %}…{% endif %}`, filters with `|`). Values: "
    "`title`, `filename` (the original's name without extension), `original_filename`, "
    "`contact`, `document_type`, `topic` (its name), `document_date`, `added`, `tags` (a list, "
    "those set), "
    "`contact_groups` and `document_type_groups` (lists, the groups the contact and the type are "
    "in), `space`, `uploaded_by` (who uploaded it), "
    "`channel`, `pages`, and `field.<key>` (`FieldOut.key`; an amount has `.amount` and "
    "`.currency`, a period `.start` and `.end` and writes itself in ISO 8601 as `2026-09`, "
    "`2026-W38`, `2026-Q3` and the like). Besides Liquid's filters: `datetime` (`format: 'MMMM "
    "yyyy'`), `currency`, `decimal`, in `LEKTO_TEMPLATE_LOCALE`. Writing a missing value sets "
    "nothing (`| default: ''` or `{% if %}` make it optional). All of it, with examples: "
    f"{TEMPLATES_GUIDE}"
)


class SetTitleAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_title"]
    template: str = Field(
        max_length=MAX_TEXT,
        examples=["{{ contact }} {{ document_type }} {{ document_date | date: '%Y-%m' }}"],
        description=TEMPLATE_DESCRIPTION,
    )


class AddTagsAction(BaseModel):
    """Document tags (also those set by hand). A tag above one the document keeps or gets is
    not added; a parent gives way to a child added."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["add_tags"]
    tag_ids: list[UUID] = Field(min_length=1, max_length=MAX_LIST)


class RemoveTagsAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["remove_tags"]
    tag_ids: list[UUID] = Field(min_length=1, max_length=MAX_LIST)


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
        max_length=MAX_TEXT,
        examples=["check the contract term of {{ contact }}"],
        description="A template, as a title's; the review holds where it cannot be rendered.",
    )


ActionSchema = Annotated[
    SetSpaceAction
    | SetContactAction
    | SetDocumentTypeAction
    | SetTopicAction
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
        {"type": "set_space", "space_id": "01999d5e-5555-7c1e-b6a3-2f4d5e6f7a8b"},
        {"type": "add_tags", "tag_ids": ["01999d5e-2222-7c1e-b6a3-2f4d5e6f7a8b"]},
    ],
}


class RuleDefinitionIn(BaseModel):
    """The content of a rule; changing it makes a new version."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [_RULE_EXAMPLE]})

    name: str = Field(min_length=1, max_length=MAX_NAME)
    priority: int = Field(
        default=DEFAULT_PRIORITY,
        ge=MIN_PRIORITY,
        le=MAX_PRIORITY,
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
        description=f"Nested at most {MAX_DEPTH} deep, at most {MAX_CONDITIONS} conditions."
    )
    actions: list[ActionSchema] = Field(min_length=1, max_length=MAX_ACTIONS)

    def to_json(self) -> JsonValue:
        data: JsonValue = self.model_dump(mode="json", by_alias=True, exclude_defaults=True)
        return data


class RuleCreate(RuleDefinitionIn):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"scope": "space", **_RULE_EXAMPLE}]}
    )

    scope: RuleScope = Field(
        default=RuleScope.SPACE,
        description=(
            "`space`: a rule of the space `space_id` (one the caller edits; default: the "
            "caller's personal space), for the documents in it. `global` (admins): for every "
            "document."
        ),
    )
    space_id: UUID | None = Field(
        default=None, description="The space a space rule belongs to; none for a global rule."
    )
    enabled: bool = Field(
        default=True,
        description="false: saved switched off (to try it first); it never runs before it is "
        "switched on.",
    )

    def to_json(self) -> JsonValue:
        data: JsonValue = self.model_dump(
            mode="json",
            by_alias=True,
            exclude_defaults=True,
            exclude={"scope", "space_id", "enabled"},
        )
        return data


class RuleChange(RuleDefinitionIn):
    """The new content of a rule, and, with `scope`, where it moves."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [_RULE_EXAMPLE]})

    scope: RuleScope | None = Field(
        default=None,
        description=(
            "Moves the rule: `space`, into `space_id` (one the caller edits; default: the "
            "caller's personal space); `global` (admins). Without it the rule stays where it "
            "is."
        ),
    )
    space_id: UUID | None = Field(
        default=None, description="With `scope: space`: the space the rule moves into."
    )
    enabled: bool | None = Field(
        default=None,
        description="Switched on or off with the change, in one transaction (the editor saves "
        "a change switched off, to try it first); left out: as it was.",
    )

    def to_json(self) -> JsonValue:
        data: JsonValue = self.model_dump(
            mode="json",
            by_alias=True,
            exclude_defaults=True,
            exclude={"scope", "space_id", "enabled"},
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
    version: int = Field(
        description="Counts from 1; every change of the content or of the space adds one."
    )
    scope: RuleScope = Field(description="Where the rule belonged with this version.")
    space_id: UUID | None = Field(
        description="The space the rule belonged to with this version; None: global. A "
        "version whose space differs from the one before moved the rule."
    )
    created_at: datetime
    created_by: UUID | None

    @classmethod
    def of(cls, version: RuleVersion) -> "RuleVersionOut":
        return cls.model_validate(
            {
                **definition_to_json(version.definition),
                "rule_id": version.rule_id,
                "version": version.number,
                "scope": RuleScope.GLOBAL if version.space_id is None else RuleScope.SPACE,
                "space_id": version.space_id,
                "created_at": version.created_at,
                "created_by": version.created_by,
            }
        )


class RuleOut(_RuleDefinitionOut):
    id: UUID
    scope: RuleScope
    space_id: UUID | None = Field(
        description="The space the rule belongs to and acts in; None for global rules."
    )
    version: int = Field(description="The current version.")
    enabled: bool
    disabled_reason: str | None = Field(
        description=(
            "Why the rule was disabled automatically, e.g. a contact it uses was deleted, in "
            "English."
        )
    )
    disabled_reasons: list[ReasonOut] = Field(
        default_factory=list, description="The same with its code (one, or none)."
    )
    managed_by_document_type_id: UUID | None = Field(
        description="The document type whose title pattern this rule is: it follows the type "
        "and is read-only (changing, switching or deleting it is 409); None for other rules."
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, rule: Rule) -> "RuleOut":
        reason = rule.disabled_reason
        return cls.model_validate(
            {
                **definition_to_json(rule.definition),
                "id": rule.id,
                "scope": rule.scope,
                "space_id": rule.space_id,
                "version": rule.current.number,
                "enabled": rule.enabled,
                "disabled_reason": None if reason is None else reason.text,
                "disabled_reasons": [] if reason is None else [ReasonOut.of(reason)],
                "managed_by_document_type_id": rule.managed_by,
                "created_at": rule.created_at,
                "updated_at": rule.updated_at,
            }
        )


class TemplatePreviewIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "template": "Lohn {{ document_date | date: '%Y-%m' }} {{ field.la_brutto }}",
                    "document_id": "01999d5e-5555-7c1e-b6a3-2f4d5e6f7a8b",
                }
            ]
        },
    )

    template: str = Field(max_length=MAX_TEXT, description=TEMPLATE_DESCRIPTION)
    document_id: UUID | None = Field(
        default=None, description="A document the caller may read, to render the template with."
    )
    document_type_id: UUID | None = Field(
        default=None,
        description="The type whose fields the template may use (a title pattern's); else "
        "the document's type, else every field.",
    )


class TemplatePreviewOut(BaseModel):
    used: list[str] = Field(description="The values the template uses (`field.la_brutto`).")
    rendered: str | None = Field(
        description="The text for the document, whitespace collapsed as in a title; None "
        "without a document, a missing value or an error."
    )
    missing: str | None = Field(
        description="The value the document lacks that the template writes: it would set "
        "nothing (a title pattern leaves the model's title)."
    )
    error: str | None = Field(
        description="Why the template is invalid (its syntax, or a value templates do not know)."
    )
    values: dict[str, str] | None = Field(
        description="The document's values as a template writes them, by path (`contact`, "
        "`field.la_brutto`): each one it has, whatever the template. None without a document.",
        examples=[{"contact": "Stadtwerke", "field.la_brutto": "3.650,00 EUR"}],
    )


class ApplyPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"limit": 50}]})

    cursor: str | None = Field(default=None, max_length=64, description="`next_cursor`.")
    limit: int = Field(default=PAGE_SIZE, ge=1, le=PAGE_LIMIT)


class ArrivalStepOut(BaseModel):
    """What the rules of one space did to the document when it entered the space."""

    space_id: UUID = Field(description="The space the document entered; its own rules ran.")
    rules: list[RuleReportOut] = Field(description="Its rules that hold, and what each did.")
    moved_to: UUID | None = Field(description="The space its rules filed the document into.")
    looped_to: UUID | None = Field(
        description=(
            "A space its rules would file the document into again: the chain stops here (each "
            "space at most once)."
        )
    )
    problem: str | None = Field(
        description="Why the chain stopped, or why a change did not fit, in English."
    )
    problem_reason: ReasonOut | None = Field(default=None, description="The same with its code.")

    @classmethod
    def of(cls, step: ArrivalStep) -> "ArrivalStepOut":
        problem = step.problem
        return cls(
            space_id=step.space_id,
            rules=[RuleReportOut.of(report) for report in step.reports],
            moved_to=step.moved_to,
            looped_to=step.looped_to,
            problem=None if problem is None else problem.text,
            problem_reason=None if problem is None else ReasonOut.of(problem),
        )


class ApplyOutcomeOut(BaseModel):
    """Where applying the rule leaves the document."""

    space_id: UUID = Field(description="The space the document ends up in.")
    chain: list[ArrivalStepOut] = Field(
        description=(
            "The rules of the spaces the document enters on the way, in order, as applying runs "
            "them; empty if it stays where it is (or no rule there holds)."
        )
    )

    @classmethod
    def of(cls, outcome: Outcome) -> "ApplyOutcomeOut":
        return cls(
            space_id=outcome.space_id, chain=[ArrivalStepOut.of(step) for step in outcome.chain]
        )


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
    outcome: ApplyOutcomeOut = Field(
        description="Applied as shown: the steps of the spaces it enters, and where it ends up."
    )
    accepted: ApplyOutcomeOut | None = Field(
        description="With its conflicts accepted (only for documents with conflicts)."
    )


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
    reason: str = Field(description="Why, in English.")
    reasons: list[ReasonOut] = Field(default_factory=list, description="The same with its code.")


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
                SkippedOut(document_id=id, reason=reason.text, reasons=[ReasonOut.of(reason)])
                for id, reason in application.skipped
            ],
            error=application.error,
            created_at=application.created_at,
            finished_at=application.finished_at,
        )
