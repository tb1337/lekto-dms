"""The relations between documents (`GET /documents/{id}/relations`)."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.core.domain.relations import RelationOrigin, RelationState
from lekto.core.services.relations import DocumentRelations, Related


class RelatedDocumentOut(BaseModel):
    """The document at the other end of a relation, as a list shows it."""

    id: UUID
    title: str
    document_type_id: UUID | None
    contact_id: UUID | None
    document_date: date | None


class RelatedOut(BaseModel):
    document: RelatedDocumentOut
    origin: RelationOrigin = Field(description="`person` set it, `lekto` recognised it.")
    state: RelationState = Field(description="`set`, or `suggested` (a person decides).")
    evidence: dict[str, Any] = Field(
        description=(
            "What Lekto had: `kind` of the source (`fact`, `period`, ...) and its values; "
            "empty for a person's."
        )
    )
    created_at: datetime
    decided_at: datetime | None = Field(description="When a person last decided it.")
    changeable: bool = Field(
        description="Whether the caller edits the newer of the two: then they accept, reject or "
        "remove it."
    )

    @classmethod
    def of(cls, item: Related) -> "RelatedOut":
        other, relation = item.other, item.relation
        return cls(
            document=RelatedDocumentOut(
                id=other.id,
                title=other.title,
                document_type_id=other.document_type_id,
                contact_id=other.contact_id,
                document_date=other.document_date,
            ),
            origin=relation.origin,
            state=relation.state,
            evidence=dict(relation.evidence),
            created_at=relation.created_at,
            decided_at=relation.decided_at,
            changeable=item.changeable,
        )


class RelationsOut(BaseModel):
    """The relations of a document whose other end the caller reads."""

    refers_to: list[RelatedOut] = Field(
        description="The older documents it refers to (bezieht sich auf), the newest first."
    )
    referred_by: list[RelatedOut] = Field(
        description="The newer documents that refer to it (darauf beziehen sich)."
    )
    suggested: list[RelatedOut] = Field(
        description="Relations Lekto suggests in either direction: a person accepts or rejects "
        "them."
    )
    editable: bool = Field(
        description="Whether the caller edits the document: then they relate it with another "
        "(the newer of the two must be one they edit, 403 otherwise)."
    )

    @classmethod
    def of(cls, relations: DocumentRelations) -> "RelationsOut":
        return cls(
            refers_to=[RelatedOut.of(item) for item in relations.refers_to],
            referred_by=[RelatedOut.of(item) for item in relations.referred_by],
            suggested=[RelatedOut.of(item) for item in relations.suggested],
            editable=relations.editable,
        )


class RelateIn(BaseModel):
    """The document to relate the document with; Lekto points the relation from the newer to the
    older."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"document_id": "01999d5e-4444-7c1e-b6a3-2f4d5e6f7a8b"}]},
    )

    document_id: UUID
