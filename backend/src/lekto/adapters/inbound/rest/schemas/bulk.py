"""Changing many documents at once: `POST /documents/bulk`, `GET /documents/bulk/{id}`."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.adapters.inbound.rest.schemas.documents import ReprocessNode
from lekto.adapters.inbound.rest.schemas.rules import SkippedOut
from lekto.adapters.inbound.schemas import ReasonOut
from lekto.core.domain.bulk import MAX_IDS, BulkAction, BulkKind, BulkOperation, BulkStatus
from lekto.core.domain.ids import ContactId, DocumentTypeId, SpaceId, TagId
from lekto.core.domain.pipeline import Node


class BulkActionIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"kind": "change_tags", "add_tag_ids": ["01a1828b-ef26-720c-9e95-ab5d2f4396cf"]}
            ]
        },
    )

    kind: BulkKind
    add_tag_ids: list[UUID] = Field(
        default_factory=list, description="`change_tags`: the tags to add.", max_length=50
    )
    remove_tag_ids: list[UUID] = Field(
        default_factory=list, description="`change_tags`: the tags to remove.", max_length=50
    )
    contact_id: UUID | None = Field(default=None, description="`set_contact`; none: clear it.")
    document_type_id: UUID | None = Field(
        default=None, description="`set_document_type`; none: clear it."
    )
    topic_id: UUID | None = Field(default=None, description="`set_topic`; none: clear it.")
    space_id: UUID | None = Field(default=None, description="`move`: the space to move into.")
    from_node: ReprocessNode | None = Field(
        default=None, description="`reprocess`: process again from this node on."
    )

    def action(self) -> BulkAction:
        return BulkAction(
            kind=self.kind,
            add=frozenset(TagId(id) for id in self.add_tag_ids),
            remove=frozenset(TagId(id) for id in self.remove_tag_ids),
            contact=None if self.contact_id is None else ContactId(self.contact_id),
            document_type=(
                None if self.document_type_id is None else DocumentTypeId(self.document_type_id)
            ),
            topic=None if self.topic_id is None else TagId(self.topic_id),
            space=None if self.space_id is None else SpaceId(self.space_id),
            node=None if self.from_node is None else Node(self.from_node.value),
        )


class BulkRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "document_ids": ["01a1828b-ef26-720c-9e95-ab5d2f4396cf"],
                    "action": {"kind": "move", "space_id": "01a1828b-ef25-76fd-a18a-9b056a79818d"},
                },
                {"action": {"kind": "reprocess", "from_node": "ocr"}},
            ]
        },
    )

    document_ids: list[UUID] | None = Field(
        default=None,
        max_length=MAX_IDS,
        description=(
            "The documents one by one. Without: every document the query parameters find "
            "(the filter of `GET /documents`, with `q` the hits of the search)."
        ),
    )
    action: BulkActionIn


class BulkOperationOut(BaseModel):
    id: UUID
    kind: BulkKind
    status: BulkStatus
    total: int = Field(description="Selected documents.")
    done: int = Field(description="Documents worked through so far.")
    changed: int
    unchanged: int = Field(description="Were as the action wants them already.")
    skipped: list[SkippedOut] = Field(
        description="Left as they were: not writable, being processed, gone, ..."
    )
    error: str | None
    created_at: datetime
    finished_at: datetime | None

    @classmethod
    def of(cls, operation: BulkOperation) -> "BulkOperationOut":
        return cls(
            id=operation.id,
            kind=operation.action.kind,
            status=operation.status,
            total=len(operation.documents),
            done=operation.position,
            changed=operation.changed,
            unchanged=operation.unchanged,
            skipped=[
                SkippedOut(document_id=id, reason=reason.text, reasons=[ReasonOut.of(reason)])
                for id, reason in operation.skipped
            ],
            error=operation.error,
            created_at=operation.created_at,
            finished_at=operation.finished_at,
        )
