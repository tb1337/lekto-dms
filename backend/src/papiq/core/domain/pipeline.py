"""Ingest pipeline: steps, step results, processing state and lanes."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.ids import DocumentId
from papiq.core.domain.json_value import JsonObject
from papiq.core.domain.validation import require_utc


class Step(StrEnum):
    """Pipeline steps in their fixed order."""

    RECEIVE = "receive"
    OCR = "ocr"
    PARSE = "parse"
    CLASSIFY = "classify"
    EXTRACT_FIELDS = "extract_fields"
    APPLY_RULES = "apply_rules"
    FILE = "file"

    @property
    def position(self) -> int:
        return PIPELINE.index(self)

    @property
    def next(self) -> "Step | None":
        position = self.position + 1
        return PIPELINE[position] if position < len(PIPELINE) else None


PIPELINE: tuple[Step, ...] = tuple(Step)


class Outcome(StrEnum):
    OK = "ok"
    UNCERTAIN = "uncertain"  # a person has to confirm
    FAILED = "failed"  # after all retries; a person has to intervene


class Lane(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"

    @classmethod
    def from_outcomes(cls, outcomes: Iterable[Outcome]) -> "Lane":
        """The worst outcome decides: any failure is red, any uncertainty yellow."""
        found = set(outcomes)
        if Outcome.FAILED in found:
            return cls.RED
        if Outcome.UNCERTAIN in found:
            return cls.YELLOW
        return cls.GREEN


@dataclass(frozen=True, kw_only=True)
class StepResult:
    """What a step decided. A reason is required unless the step went through cleanly."""

    outcome: Outcome
    reason: str | None = None
    confidence: float | None = None  # 0..1, derived from verifiable facts where possible
    model_version: str | None = None
    input: JsonObject = field(default_factory=dict)
    output: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.outcome is not Outcome.OK and not (self.reason and self.reason.strip()):
            raise ValidationError(f"a {self.outcome} step result needs a reason")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValidationError(f"confidence must be between 0 and 1, got {self.confidence}")


@dataclass(frozen=True, kw_only=True)
class StepRun:
    """Processing log entry: one execution of one step for one document."""

    document_id: DocumentId
    step: Step
    run: int
    result: StepResult
    pipeline_version: str
    started_at: datetime
    duration: timedelta

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", require_utc(self.started_at, "started_at"))
        if self.duration < timedelta(0):
            raise ValidationError("duration must not be negative")
        if self.run < 1:
            raise ValidationError("run starts at 1")


# Entries that people and rules write carry these as `model_version`, in place of a model.
PERSON = "person"
"""`model_version` of a log entry in which the owner confirmed a step's results."""
RULES = "rules"
"""`model_version` of the log entry of the pipeline step `apply_rules`."""
RULES_CHANGE = "rules:change"
"""`model_version` of the `apply_rules` log entry of a metadata change by a person (with the
rules it set off)."""
RULES_APPLY = "rules:apply"
"""`model_version` of the `apply_rules` log entry of a rule applied to an existing document on
request."""
PERSON_DRAWER = "person:drawer"
"""`model_version` of a log entry in which a person chose the drawer outside the inbox (an
upload into a given drawer, a move); rules leave the drawer then."""
CHOSEN_DRAWER = "drawer_id"
"""Key of the drawer a person chose, in the input of a `PERSON_DRAWER` entry and the output of a
`PERSON` entry."""
OUTSIDE_PIPELINE = frozenset({RULES_CHANGE, RULES_APPLY, PERSON_DRAWER})
"""Log entries written outside processing; they say nothing about a step's state."""


def drawer_chooser(log: Sequence[StepRun], drawer: UUID) -> UUID | None:
    """Who last put the document into `drawer` by hand (confirming, uploading into a given
    drawer, moving), if anyone. Entries written before the drawer was recorded name none."""
    for entry in reversed(log):
        result = entry.result
        if result.model_version == PERSON_DRAWER:
            actor, chosen = result.input.get("actor"), result.input.get(CHOSEN_DRAWER)
        elif result.model_version == PERSON:
            actor, chosen = result.output.get("confirmed_by"), result.output.get(CHOSEN_DRAWER)
        else:
            continue
        if chosen == str(drawer):
            return UUID(actor) if isinstance(actor, str) else None
    return None


class ProcessingStatus(StrEnum):
    PROCESSING = "processing"  # `current_step` is due
    COMPLETED = "completed"  # all steps done
    FAILED = "failed"  # stopped at `current_step`
    REVIEW = "review"  # uncertain results; waits before `current_step` (filing) for the owner


@dataclass(kw_only=True)
class Processing:
    """Processing state of a document.

    `run` counts processing runs; it grows with every retry or reprocessing, so jobs of an
    earlier run are recognised as stale. `outcomes` holds the results of the current run.
    """

    status: ProcessingStatus
    current_step: Step | None
    run: int
    outcomes: dict[Step, Outcome] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (self.status is ProcessingStatus.COMPLETED) != (self.current_step is None):
            raise ValidationError("only completed processing has no current step")
