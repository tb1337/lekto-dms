"""Trained classifiers: one model for everyone, trained anew from the confirmed documents."""

from dataclasses import dataclass, field
from datetime import datetime

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import ClassifierModelId, new_id
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.validation import require_utc

KEPT_MODELS = 3
"""Models kept; older ones and their files are removed after training."""


@dataclass(kw_only=True)
class ClassifierModel:
    """The `number`-th model, trained at `trained_at` from `examples` confirmed documents, the
    latest of them confirmed at `examples_until`. The model itself is a file in the object
    store (`object_key`); `summary` says what it learned."""

    id: ClassifierModelId
    number: int
    trained_at: datetime
    examples: int
    examples_until: datetime | None
    object_key: str
    summary: JsonObject = field(default_factory=dict)
    version: int = 1

    def __post_init__(self) -> None:
        self.trained_at = require_utc(self.trained_at, "trained_at")
        if self.examples_until is not None:
            self.examples_until = require_utc(self.examples_until, "examples_until")
        if self.number < 1 or self.examples < 0:
            raise ValidationError("a model's number starts at 1, its examples at 0")

    @classmethod
    def create(
        cls,
        *,
        number: int,
        now: datetime,
        examples: int,
        examples_until: datetime | None,
        object_key: str,
        summary: JsonObject,
    ) -> "ClassifierModel":
        return cls(
            id=ClassifierModelId(new_id()),
            number=number,
            trained_at=now,
            examples=examples,
            examples_until=examples_until,
            object_key=object_key,
            summary=summary,
        )
