"""Contacts, document types and fields."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from papiq.adapters.inbound.rest.schemas.common import Name, NameIn
from papiq.core.domain.fields import FieldDefinition, FieldType
from papiq.core.domain.identifiers import MAX_IDENTIFIERS, IdentifierKind, IdentifierSource
from papiq.core.domain.master_data import (
    MAX_ALIASES,
    MAX_DESCRIPTION,
    MAX_TITLE_PATTERN,
    Assignment,
    Contact,
    DocumentType,
    MasterData,
)


class MasterDataOut(BaseModel):
    id: UUID
    name: str = Field(examples=["ACME Energy"])
    created_at: datetime
    document_count: int | None = Field(
        default=None,
        description=(
            "With `document_counts`: how many documents within the caller's reach (with "
            "`all_users`, every document) have it; for a field, a value for it."
        ),
    )

    @classmethod
    def of(cls, item: MasterData) -> "MasterDataOut":
        return cls(id=getattr(item, "id"), name=item.name, created_at=item.created_at)  # noqa: B009


Aliases = Annotated[
    list[Name],
    Field(
        max_length=MAX_ALIASES,
        description=(
            "Other names the contact is written as in documents. Unique across contacts, "
            "together with the names; papiq also learns them when a contact is chosen in the "
            "review."
        ),
        examples=[["ACME Energy Services GmbH"]],
    ),
]


class IdentifierIn(BaseModel):
    """Written as in documents; papiq stores it normalised (an IBAN without spaces, a domain
    without `www.`)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"kind": "customer_number", "value": "2004-7718"}]},
    )

    kind: IdentifierKind
    value: str = Field(min_length=1, max_length=100, examples=["DE89 3704 0044 0532 0130 00"])


class IdentifierOut(BaseModel):
    kind: IdentifierKind
    value: str = Field(examples=["DE89370400440532013000"])
    source: IdentifierSource = Field(
        description="`manual`: entered by an admin; `learned`: found by training in "
        "confirmed documents of only this contact; `rejected`: learned, then rejected by an "
        "admin (does not count, and training does not learn it again)."
    )


Identifiers = Annotated[
    list[IdentifierIn],
    Field(
        max_length=MAX_IDENTIFIERS,
        description=(
            "Values the contact's documents carry: IBAN, VAT number, customer (or contract) "
            "number, the personnel number at an employer (without leading zeros), the domain "
            "of its e-mail and web addresses. Unique across contacts; found "
            "in a document, they are evidence for the contact. The identifiers entered by "
            "hand: a learned one given here becomes one entered by hand."
        ),
    ),
]

Rejected = Annotated[
    list[IdentifierIn],
    Field(
        max_length=MAX_IDENTIFIERS,
        description="The rejected identifiers: a learned one given here no longer counts, and "
        "training does not learn it again; one left out may be learned again.",
    ),
]


Description = Annotated[
    str,
    Field(
        max_length=MAX_DESCRIPTION,
        description="What belongs to the type, for the language model; empty removes it.",
        examples=["Gehaltsabrechnung, Entgeltbescheinigung, Verdienstnachweis"],
    ),
]
FieldDescription = Annotated[
    str,
    Field(
        max_length=MAX_DESCRIPTION,
        description=(
            "What belongs in the field, for the language model (the field's name is often an "
            "internal one no document shows); empty removes it."
        ),
        examples=["Gesamtbrutto des Monats, nicht das Grundgehalt; steht als Gesamt-Brutto"],
    ),
]


TitlePattern = Annotated[
    str,
    Field(
        max_length=MAX_TITLE_PATTERN,
        description=(
            "The title of the type's documents: a template as a rule's title "
            "(`SetTitleAction.template`), with the fields of the type. A rule of the type "
            "carries it out (`RuleOut.managed_by_document_type_id`, read-only): it replaces "
            "the language model's title and gives way to another rule that sets the title. A "
            "document missing a value it writes keeps the model's title."
        ),
        examples=["Lohn {{ document_date | date: '%Y-%m' }} {{ field.la_brutto }}"],
    ),
]


class ContactCreate(NameIn):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"name": "ACME Energy", "aliases": ["ACME Strom"]}]},
    )

    aliases: Aliases = Field(default_factory=list)
    identifiers: Identifiers = Field(default_factory=list)


class ContactPatch(BaseModel):
    """Fields left out stay; `aliases` replaces all aliases, `identifiers` those entered by
    hand and `rejected_identifiers` the rejected ones. A value another contact learned or
    rejected moves here; one another contact entered by hand is a conflict (409)."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"aliases": ["ACME Strom"]}]}
    )

    name: Name | None = None
    aliases: Aliases | None = None
    identifiers: Identifiers | None = None
    rejected_identifiers: Rejected | None = None


class ContactOut(MasterDataOut):
    aliases: list[str] = Field(examples=[["ACME Strom"]])
    identifiers: list[IdentifierOut] = Field(
        description="Entered, learned and rejected identifiers, in this order."
    )

    @classmethod
    def of(cls, item: MasterData) -> "ContactOut":
        assert isinstance(item, Contact)
        return cls(
            id=item.id,
            name=item.name,
            aliases=item.aliases,
            identifiers=[
                IdentifierOut(kind=entry.kind, value=entry.value, source=entry.source)
                for entry in item.identifiers
            ],
            created_at=item.created_at,
        )


class DocumentTypeCreate(NameIn):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"name": "Pay slip", "description": "Entgeltbescheinigung"}]
        },
    )

    description: Description | None = None
    title_pattern: TitlePattern | None = None


class DocumentTypePatch(BaseModel):
    """Fields left out stay; a `description` or `title_pattern` of null or empty removes
    it."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"description": "Entgeltbescheinigung"}]}
    )

    name: Name | None = None
    description: Description | None = None
    title_pattern: TitlePattern | None = None


class DocumentTypeOut(MasterDataOut):
    description: str | None = Field(examples=["Entgeltbescheinigung"])
    title_pattern: str | None = Field(examples=["Lohn {document_date:YYYY-MM}"])

    @classmethod
    def of(cls, item: MasterData) -> "DocumentTypeOut":
        assert isinstance(item, DocumentType)
        return cls(
            id=item.id,
            name=item.name,
            description=item.description,
            title_pattern=item.title_pattern,
            created_at=item.created_at,
        )


Required = Annotated[
    bool,
    Field(
        description="A global field: whether every document needs a value (read by the model, "
        "or entered by hand for a field set by hand)."
    ),
]
RequiredTypes = Annotated[
    list[UUID],
    Field(
        description=(
            "A typed field: the document types (of its own) it is required for; for the others "
            "it is optional. Extraction must find a required field; an optional one may stay "
            "empty, but a value it gives must be shown by the text."
        )
    ),
]


class FieldCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "LA_Brutto",
                    "data_type": "amount",
                    "document_type_ids": ["01999d5e-3333-7c1e-b6a3-2f4d5e6f7a8b"],
                    "description": "Gesamtbrutto des Monats, nicht das Grundgehalt",
                }
            ]
        },
    )

    name: Name
    data_type: FieldType
    document_type_ids: list[UUID] | None = Field(
        default=None, description="null: global; otherwise only for these document types."
    )
    choices: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=200, description="For `choice` only."
    )
    required: Required = False
    required_document_type_ids: RequiredTypes = Field(default_factory=list)
    description: FieldDescription | None = None
    assignment: Assignment = Field(
        default=Assignment.AUTO,
        description="`auto`: the language model reads it; `manual`: set by hand only, never "
        "asked of the model (a required one keeps the document open until a person sets it).",
    )


class FieldPatch(BaseModel):
    """Fields left out stay; a `description` of null or empty removes it. The data type
    cannot change."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"name": "Payment method", "choices": ["Card", "Transfer", "Cash"]}]
        },
    )

    name: Name | None = None
    choices: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(
        default=None,
        max_length=200,
        description="All choices; removing one that documents use is a conflict (409).",
    )
    document_type_ids: list[UUID] | None = Field(
        default=None,
        description=(
            "null: global. Narrowing is a conflict (409) while documents outside the new scope "
            "have values; the types it is required for narrow with it."
        ),
    )
    required: Required | None = None
    required_document_type_ids: RequiredTypes | None = None
    description: FieldDescription | None = None
    assignment: Assignment | None = Field(
        default=None,
        description="`auto`: the language model reads it; `manual`: set by hand only, never "
        "asked of the model (a required one keeps the document open until a person sets it).",
    )


class FieldOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "01999d5e-4444-7c1e-b6a3-2f4d5e6f7a8b",
                    "name": "Amount",
                    "key": "amount",
                    "data_type": "amount",
                    "document_type_ids": None,
                    "choices": [],
                    "required": False,
                    "required_document_type_ids": [],
                    "description": "Gesamtbrutto des Monats, nicht das Grundgehalt",
                    "assignment": "auto",
                    "created_at": "2026-01-10T09:00:00Z",
                }
            ]
        }
    )

    id: UUID
    name: str
    key: str = Field(
        description="The field in templates of rules and title patterns: `field.<key>`, from "
        "the name (lower case, umlauts as ae/oe/ue, anything else `_`)"
    )
    data_type: FieldType
    document_type_ids: list[UUID] | None
    choices: list[str]
    required: Required
    required_document_type_ids: RequiredTypes
    description: str | None
    assignment: Assignment = Field(
        description="`auto`: the language model reads it; `manual`: set by hand only, never "
        "asked of the model (a required one keeps the document open until a person sets it).",
    )
    created_at: datetime
    document_count: int | None = Field(
        default=None,
        description=(
            "With `document_counts`: how many documents within the caller's reach (with "
            "`all_users`, every document) have it; for a field, a value for it."
        ),
    )

    @classmethod
    def of(cls, item: FieldDefinition) -> "FieldOut":
        return cls(
            id=item.id,
            name=item.name,
            key=item.key,
            data_type=item.data_type,
            document_type_ids=(
                None if item.document_type_ids is None else sorted(item.document_type_ids)
            ),
            choices=list(item.choices),
            required=item.required,
            required_document_type_ids=sorted(item.required_types),
            description=item.description,
            assignment=item.assignment,
            created_at=item.created_at,
        )


class FieldAssignmentIn(BaseModel):
    """A field of a document type, from the type."""

    model_config = ConfigDict(extra="forbid")

    field_id: UUID
    required: bool = False


class FieldAssignmentsIn(BaseModel):
    """The fields of a document type, global ones aside."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "fields": [
                        {"field_id": "01999d5e-4444-7c1e-b6a3-2f4d5e6f7a8b", "required": True},
                        {"field_id": "01999d5e-5555-7c1e-b6a3-2f4d5e6f7a8b", "required": False},
                    ]
                }
            ]
        },
    )

    fields: list[FieldAssignmentIn] = Field(max_length=500)
