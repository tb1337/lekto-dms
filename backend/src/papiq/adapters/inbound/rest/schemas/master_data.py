"""Contacts, document types and fields."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from papiq.adapters.inbound.rest.schemas.common import Name, NameIn
from papiq.core.domain.fields import FieldDefinition, FieldType
from papiq.core.domain.master_data import (
    MAX_ALIASES,
    MAX_DESCRIPTION,
    Contact,
    DocumentType,
    MasterData,
)


class MasterDataOut(BaseModel):
    id: UUID
    name: str = Field(examples=["ACME Energy"])
    created_at: datetime

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


Description = Annotated[
    str,
    Field(
        max_length=MAX_DESCRIPTION,
        description="What belongs to the type, for the language model; empty removes it.",
        examples=["Gehaltsabrechnung, Entgeltbescheinigung, Verdienstnachweis"],
    ),
]


class ContactCreate(NameIn):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"name": "ACME Energy", "aliases": ["ACME Strom"]}]},
    )

    aliases: Aliases = Field(default_factory=list)


class ContactPatch(BaseModel):
    """Fields left out stay; `aliases` replaces all aliases."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"aliases": ["ACME Strom"]}]}
    )

    name: Name | None = None
    aliases: Aliases | None = None


class ContactOut(MasterDataOut):
    aliases: list[str] = Field(examples=[["ACME Strom"]])

    @classmethod
    def of(cls, item: MasterData) -> "ContactOut":
        assert isinstance(item, Contact)
        return cls(id=item.id, name=item.name, aliases=item.aliases, created_at=item.created_at)


class DocumentTypeCreate(NameIn):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"name": "Pay slip", "description": "Entgeltbescheinigung"}]
        },
    )

    description: Description | None = None


class DocumentTypePatch(BaseModel):
    """Fields left out stay; a `description` of null or empty removes it."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"description": "Entgeltbescheinigung"}]}
    )

    name: Name | None = None
    description: Description | None = None


class DocumentTypeOut(MasterDataOut):
    description: str | None = Field(examples=["Entgeltbescheinigung"])

    @classmethod
    def of(cls, item: MasterData) -> "DocumentTypeOut":
        assert isinstance(item, DocumentType)
        return cls(
            id=item.id, name=item.name, description=item.description, created_at=item.created_at
        )


class FieldCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "Amount",
                    "data_type": "amount",
                    "document_type_ids": ["01999d5e-3333-7c1e-b6a3-2f4d5e6f7a8b"],
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


class FieldPatch(BaseModel):
    """Fields left out stay. The data type cannot change."""

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
            "have values."
        ),
    )


class FieldOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "01999d5e-4444-7c1e-b6a3-2f4d5e6f7a8b",
                    "name": "Amount",
                    "data_type": "amount",
                    "document_type_ids": None,
                    "choices": [],
                    "created_at": "2026-01-10T09:00:00Z",
                }
            ]
        }
    )

    id: UUID
    name: str
    data_type: FieldType
    document_type_ids: list[UUID] | None
    choices: list[str]
    created_at: datetime

    @classmethod
    def of(cls, item: FieldDefinition) -> "FieldOut":
        return cls(
            id=item.id,
            name=item.name,
            data_type=item.data_type,
            document_type_ids=(
                None if item.document_type_ids is None else sorted(item.document_type_ids)
            ),
            choices=list(item.choices),
            created_at=item.created_at,
        )
