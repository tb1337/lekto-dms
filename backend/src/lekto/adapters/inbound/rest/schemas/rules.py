"""Rules: definitions, versions, dry runs and applying a rule to existing documents.

Shape and types are checked here; operators by field and data type, values, patterns and the
actions a scope allows are checked by the core (`definition_from_json`), references by the
rule service."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.adapters.inbound.rest.schemas.open_identifiers import OccurrenceOut
from lekto.adapters.inbound.schemas import (
    FieldJson,
    MoneyValue,
    PeriodValue,
    ReasonOut,
    RuleEffectOut,
    RuleNoteOut,
    RuleReportOut,
)
from lekto.core.domain.document_facts import FactRole
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.rules import (
    DEFAULT_PRIORITY,
    MAX_ACTIONS,
    MAX_CONDITIONS,
    MAX_DEPTH,
    MAX_LIST,
    MAX_PRIORITY,
    MAX_STEP_PATH,
    MAX_TEXT,
    MIN_PRIORITY,
    ApplicationStatus,
    ConditionField,
    Missing,
    Operator,
    Rule,
    RuleApplication,
    RuleScope,
    RuleVersion,
    Trigger,
)
from lekto.core.domain.rules_json import definition_to_json
from lekto.core.domain.tasks import DEFAULT_TIMEOUT, MAX_TIMEOUT, MIN_TIMEOUT
from lekto.core.domain.validation import MAX_NAME
from lekto.core.domain.webhooks import MAX_BODY_TEMPLATE
from lekto.core.ports.repository import PAGE_LIMIT, PAGE_SIZE
from lekto.core.services.rules.changes import ArrivalStep
from lekto.core.services.rules.retroactive import Outcome, TextHit


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
    before the date), `present`, `missing`; step (in a condition step only: what a step that
    asks brought, at `path`): `is`, `in` (texts without case, numbers as numbers, true or
    false), `contains` (a text in a text, an item of a list), `gt`, `lt` (a number or a date),
    `present`, `missing`; fact (`fact_kind`, `fact_role` if given; facts a person rejected do
    not count): `is`, `in` (the values as written, compared as Lekto compares them), `matches`
    (against each value as the text writes it; `^` and `$` mark its ends), `present`,
    `missing`; relation (the documents it refers to by a set relation; suggestions do not
    count): `present` (any), `missing` (none), `is`, `in` (one of the document type ids)."""

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
                {
                    "field": "fact",
                    "op": "present",
                    "fact_kind": "invoice_number",
                    "fact_role": "refers",
                },
                {
                    "field": "relation",
                    "op": "in",
                    "value": ["01999d5e-4444-7c1e-b6a3-2f4d5e6f7a8b"],
                },
            ]
        },
    )

    field: ConditionField
    op: Operator
    value: (
        str
        | bool
        | int
        | float
        | MoneyValue
        | PeriodValue
        | list[str]
        | list[str | bool | int | float]
        | None
    ) = Field(
        default=None,
        description=(
            "None for `present` and `missing`, a list for `in`, otherwise one value: an id, a "
            "channel, a text or pattern, a date `YYYY-MM-DD` (also for `gt` and `lt` of a "
            "period field), a field value as in `fields` of a document, or (for `step`) a "
            "text, a number or true/false."
        ),
    )
    field_id: UUID | None = Field(default=None, description="Only when `field` is `field`.")
    path: str | None = Field(
        default=None,
        max_length=MAX_STEP_PATH,
        examples=["accounting.paid"],
        description=(
            "Only when `field` is `step`: the name of a step before that asks, then keys of "
            "its answer (a number for an item of a list), separated by dots."
        ),
    )
    case_sensitive: bool = Field(
        default=False, description="For `matches` only; other comparisons ignore case."
    )
    fact_kind: IdentifierKind | None = Field(
        default=None, description="Only when `field` is `fact`: the kind of the facts."
    )
    fact_role: FactRole | None = Field(
        default=None,
        description="Only when `field` is `fact`: their role; none for any.",
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
    "`channel`, `pages`, `field.<key>` (`FieldOut.key`; an amount has `.amount` and "
    "`.currency`, a period `.start` and `.end` and writes itself in ISO 8601 as `2026-09`, "
    "`2026-W38`, `2026-Q3` and the like), and the facts: `facts.<kind>` (the document's own "
    "value of the kind, as written), `facts.refers.<kind>` (one it refers to), `facts.girocode` "
    "(`name`, `iban`, `bic`, `amount`, `purpose`) and `fact_list` (each with `kind`, `value`, "
    "`written`, `role`, `origin`); none a person rejected, none of a person's. Besides "
    "Liquid's filters: `datetime` (`format: 'MMMM yyyy'`), `currency`, `decimal`, in "
    "`LEKTO_TEMPLATE_LOCALE`. Writing a missing value sets "
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
        description=(
            "Text is a template for every type, as a title's: what it renders is read as the "
            "field's type has it, first in the forms templates write (`1234.5`, `2026-03-12`, "
            "`2026-Q3`, `true`), else as a person writes it (`2.111,68 €`, `12. März 2026`, "
            "`KW 38/2026`, `ja`; an ambiguous number as `LEKTO_TEMPLATE_LOCALE` means it, an "
            "amount without currency in `LEKTO_DEFAULT_CURRENCY`); text that cannot be read sets "
            "nothing (noted, the document does not wait for it). An amount, a period or yes/no "
            "as JSON is a fixed value."
        )
    )


class ForceReviewAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["force_review"]
    reason: str = Field(
        max_length=MAX_TEXT,
        examples=["check the contract term of {{ contact }}"],
        description="A template, as a title's; the review holds where it cannot be rendered.",
    )


class SendWebhookAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["send_webhook"]
    webhook_id: UUID = Field(
        description=(
            "A webhook of whoever saves the rule (someone else's is not found). It gets a "
            "request of type `rule.send` with the rule's `id` and `name`, in the webhook's body "
            "format: on arrival once the document is filed (a yellow one after it was "
            "confirmed, a red one never), after a change once it is stored. Its owner must be "
            "able to read the document: on arrival the document turns yellow otherwise (unless "
            "a person decided already), else it is only reported."
        )
    )


class AskWebhookAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ask_webhook"]
    name: str = Field(
        min_length=1,
        max_length=50,
        examples=["accounting"],
        description=(
            "Small letters, digits and `_`, unique in the rule: the steps after it see the "
            "answer as `steps.<name>`."
        ),
    )
    webhook_id: UUID = Field(
        description=(
            "A webhook of whoever saves the rule (someone else's is not found). It gets a task "
            "(`rule.ask`, with `task` and the headers `lekto-*`) and answers at "
            "`/external/tasks/{id}/result`. Its owner must be able to read the document, "
            "otherwise the document waits for a person (unless one decided already). Needs "
            "`LEKTO_PUBLIC_URL`."
        )
    )
    timeout_seconds: int = Field(
        default=int(DEFAULT_TIMEOUT.total_seconds()),
        ge=int(MIN_TIMEOUT.total_seconds()),
        le=int(MAX_TIMEOUT.total_seconds()),
        description="The time to answer, from sending (the request may wait for its webhook).",
    )
    missing: Missing = Field(
        default=Missing.RED,
        description=(
            "Without an answer (none in time, an error, an invalid one): `red` fails the node "
            "(no rule acts), `yellow` ends the rule here (its steps before count) and holds "
            "the document for a person, `continue` goes on without `steps.<name>`. After a "
            "person decided in the run, it is only reported."
        ),
    )


class ConditionStepAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["condition"]
    conditions: "AllGroup | AnyGroup" = Field(
        description=(
            "On the document as the rule's steps before left it, and on `step` (what a step "
            "that asks brought). If they do not hold, the rule ends here; its steps before "
            "count."
        )
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
    | ForceReviewAction
    | SendWebhookAction
    | AskWebhookAction
    | ConditionStepAction,
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
        description=(
            "`ingest`: when a document arrives; `change`: when a person changes it. A rule "
            "with a step that asks a webhook: `ingest` only."
        ),
    )
    conditions: AllGroup | AnyGroup = Field(
        description=f"Nested at most {MAX_DEPTH} deep, at most {MAX_CONDITIONS} conditions."
    )
    actions: list[ActionSchema] = Field(
        min_length=1,
        max_length=MAX_ACTIONS,
        description=(
            "The steps, in order: actions, steps that ask a webhook and condition steps. Each "
            "rule works on its own copy of the document and sees what its own steps before set; "
            "the actions of all rules are combined at the end."
        ),
    )

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

    template: str = Field(
        max_length=MAX_BODY_TEMPLATE,
        description=TEMPLATE_DESCRIPTION
        + f" At most {MAX_TEXT} characters, a webhook's body {MAX_BODY_TEMPLATE}.",
    )
    document_id: UUID | None = Field(
        default=None, description="A document the caller may read, to render the template with."
    )
    purpose: Literal["rule", "webhook"] = Field(
        default="rule",
        description=(
            "`webhook`: the template of a webhook's body. It sees `event` (here a "
            "`webhook.test`), `document_id`, `lane` and `link` too, is rendered as it is "
            "(whitespace kept) and must make JSON."
        ),
    )
    document_type_id: UUID | None = Field(
        default=None,
        description="The type whose fields the template may use (a title pattern's); else "
        "the document's type, else every field.",
    )
    field_id: UUID | None = Field(
        default=None,
        description="The field a rule's action sets with the template: what it renders is read "
        "as the field's type has it (`read`, `unreadable`); also without a document if the "
        "template uses no value.",
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
    read: FieldJson | None = Field(
        default=None,
        description="With `field_id`: the value the rendered text gives the field, in its JSON "
        "form; None if nothing was rendered or it cannot be read.",
    )
    unreadable: bool = Field(
        default=False,
        description="With `field_id`: the rendered text cannot be read as the field's type has "
        "it, so the action would set nothing.",
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


class TextHitOut(BaseModel):
    """Where one text condition hits the document."""

    value: str = Field(description="The condition's text or pattern.")
    occurrences: list[OccurrenceOut] = Field(description="Each place its pages show a hit.")

    @classmethod
    def of(cls, hit: TextHit) -> "TextHitOut":
        return cls(
            value=hit.value, occurrences=[OccurrenceOut.of(item) for item in hit.occurrences]
        )


class TextHitsOut(BaseModel):
    hits: list[TextHitOut] = Field(description="One per text condition, in the rule's order.")


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
    sends: list[UUID] = Field(
        default_factory=list,
        description="The webhooks applying would send a request through, about this document.",
    )
    sends_refused: list[ReasonOut] = Field(
        default_factory=list,
        description="Requests that would not go, and why (the owner may not read the document).",
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
