"""The answer to a task."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lekto.core.domain.tasks import MAX_PRODUCER, MAX_REASON


class TaskAnswer(BaseModel):
    """The envelope of an answer to a task. Lekto reads it itself (an envelope that is not
    valid uses the token up); this model describes it."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"status": "ok", "producer": "my-flow 1.2", "answer": {"paid": True}},
                {"status": "error", "reason": "the accounting system is down"},
            ]
        },
    )

    status: Literal["ok", "error"]
    producer: str | None = Field(
        default=None, max_length=MAX_PRODUCER, description="What answered, for the log."
    )
    answer: Any = Field(
        default=None,
        description=(
            "With `status: ok`: any JSON. A rule step's answer is `steps.<name>` for the "
            "steps after it."
        ),
    )
    reason: str | None = Field(
        default=None,
        description=f"With `status: error`: why; shown as plain text, cut to {MAX_REASON} "
        "characters.",
    )
