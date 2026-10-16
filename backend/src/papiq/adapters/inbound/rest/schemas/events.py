"""The event stream."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class EventMessage(BaseModel):
    """A domain event, thin: fetch the document for details. Fields beyond `type`, `id`,
    `occurred_at` and `document_id` depend on the type (`classifier.trained`: `number` and
    `examples` of the new model)."""

    model_config = {"extra": "allow"}

    type: str = Field(examples=["document.node_completed"])
    id: UUID
    occurred_at: datetime
    document_id: UUID | None = Field(
        default=None, description="The document; absent from `classifier.trained`."
    )
