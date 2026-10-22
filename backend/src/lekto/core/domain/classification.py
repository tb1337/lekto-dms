"""Results of the judge and the fields node, field by field.

Each value the signals proposed is checked against facts; a `FieldCheck` records the proposal,
the candidates with their sources, the check and its outcome. Checks are stored in the
processing log (output of the judge and the fields node), so what was proposed stays traceable
after a person corrected it; the inbox and the rules (M7) read them from there.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Self
from uuid import UUID

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import FieldId
from lekto.core.domain.json_value import (
    JsonObject,
    JsonValue,
    as_bool,
    as_int,
    as_list,
    as_number,
    as_text,
    as_texts,
)
from lekto.core.domain.labels import LabelCheck
from lekto.core.domain.locations import Location, locations_from_json, locations_to_json
from lekto.core.domain.pipeline import Outcome


class CheckField(StrEnum):
    """The names of a document's fields in checks, decisions, rule reports and the log. A
    custom field is named `field:<id>` (`field_key`, `field_id_of`)."""

    CONTACT = "contact"
    DOCUMENT_TYPE = "document_type"
    TOPIC = "topic"
    TAGS = "tags"
    DOCUMENT_DATE = "document_date"
    TITLE = "title"
    SPACE = "space"  # judged from the signals (`verdict.judge_space`), set by rules and people
    REVIEW = "review"  # a review a rule forces; no field of the document


CONTACT = CheckField.CONTACT
DOCUMENT_TYPE = CheckField.DOCUMENT_TYPE
TOPIC = CheckField.TOPIC
TAGS = CheckField.TAGS
DOCUMENT_DATE = CheckField.DOCUMENT_DATE
TITLE = CheckField.TITLE
SPACE = CheckField.SPACE
REVIEW = CheckField.REVIEW

CHANGE_FIELDS: Mapping[str, str] = {
    TITLE: "title",
    CONTACT: "contact_id",
    DOCUMENT_TYPE: "document_type_id",
    TOPIC: "topic_id",
    TAGS: "tag_ids",
    DOCUMENT_DATE: "document_date",
}
"""The fields a person sets in one change, and the attribute of `Document` and
`DocumentChanges` that holds each; custom fields are `CUSTOM_FIELDS`."""
CUSTOM_FIELDS = "fields"
"""The attribute of `Document` and `DocumentChanges` that holds the custom field values."""
CHECKS = "fields"
"""Key of the field checks (`checks_to_json`) in the output of the judge, the fields node and
the rules node."""
CONFIRMING = frozenset(
    {CHANGE_FIELDS[name] for name in (CONTACT, DOCUMENT_TYPE, TOPIC, TAGS, DOCUMENT_DATE)}
    | {CUSTOM_FIELDS}
)
"""Metadata a person confirms by changing it (as `Document.apply_changes` names it); a title
or a space alone does not, nor do tags set by hand alone (`documents.confirms`)."""
CLASSIFIER_LABELS = frozenset(CHANGE_FIELDS[name] for name in (CONTACT, DOCUMENT_TYPE, TOPIC, TAGS))
"""What the classifier learns from confirmed documents: the pipeline deriving them anew ends
the confirmation."""

_FIELD_PREFIX = "field:"


def field_key(id: FieldId) -> str:
    return f"{_FIELD_PREFIX}{id}"


def field_id_of(field: str) -> FieldId | None:
    """The field a check name `field:<id>` is about; None for the other checks (and for a
    malformed id)."""
    if not field.startswith(_FIELD_PREFIX):
        return None
    try:
        return FieldId(UUID(field.removeprefix(_FIELD_PREFIX)))
    except ValueError:
        return None


@dataclass(frozen=True, kw_only=True)
class CandidateSource:
    """What one signal says about a candidate: `names` whether it is sure enough to name it
    (it counts for the judge's rule), `score` its match, probability or share of the similar
    documents, `threshold` the score from which it names a value, `votes` of `of` similar
    documents (`documents`) that carry it and the highest `similarity` among them, the `quote`
    the language model gave, the `identifiers` (kinds) of the contact found in the text, and
    whether its name or an alias stands in the text (`named_in_text`)."""

    signal: str  # the node: signal_llm, signal_classifier, signal_neighbours, signal_facts
    names: bool = False
    score: float | None = None
    threshold: float | None = None
    similarity: float | None = None
    votes: int | None = None
    of: int | None = None
    quote: str | None = None
    identifiers: tuple[str, ...] = ()
    documents: tuple[str, ...] = ()
    named_in_text: bool = False

    def to_json(self) -> JsonObject:
        data: JsonObject = {"signal": self.signal, "names": self.names}
        for key, number in (
            ("score", self.score),
            ("threshold", self.threshold),
            ("similarity", self.similarity),
        ):
            if number is not None:
                data[key] = round(number, 4)
        for key, value in (("votes", self.votes), ("of", self.of), ("quote", self.quote)):
            if value is not None:
                data[key] = value
        if self.identifiers:
            data["identifiers"] = list(self.identifiers)
        if self.documents:
            data["documents"] = list(self.documents)
        if self.named_in_text:
            data["named_in_text"] = True
        return data

    @classmethod
    def from_json(cls, data: JsonValue) -> Self:
        if not isinstance(data, dict) or not isinstance(data.get("signal"), str):
            raise ValidationError(f"invalid candidate source {data!r}")
        return cls(
            signal=str(data["signal"]),
            names=data.get("names") is True,
            score=as_number(data.get("score")),
            threshold=as_number(data.get("threshold")),
            similarity=as_number(data.get("similarity")),
            votes=as_int(data.get("votes")),
            of=as_int(data.get("of")),
            quote=as_text(data.get("quote")),
            identifiers=as_texts(data.get("identifiers")),
            documents=as_texts(data.get("documents")),
            named_in_text=data.get("named_in_text") is True,
        )


@dataclass(frozen=True, kw_only=True)
class Candidate:
    """A value the signals proposed for a field, best first: `value` as the check's (a contact
    or type id, a tag id) or None for a name that does not exist yet (`label`), with what each
    signal said, and whether a signal named another value against it (`contradicted`)."""

    value: JsonValue
    label: str
    sources: tuple[CandidateSource, ...] = ()
    contradicted: bool = False

    def to_json(self) -> JsonObject:
        return {
            "value": self.value,
            "label": self.label,
            "sources": [source.to_json() for source in self.sources],
            "contradicted": self.contradicted,
        }

    @classmethod
    def from_json(cls, data: JsonValue) -> Self:
        if not isinstance(data, dict) or not isinstance(data.get("label"), str):
            raise ValidationError(f"invalid candidate {data!r}")
        sources = data.get("sources")
        return cls(
            value=data.get("value"),
            label=str(data["label"]),
            sources=tuple(CandidateSource.from_json(item) for item in as_list(sources)),
            contradicted=data.get("contradicted") is True,
        )


@dataclass(frozen=True, kw_only=True)
class FieldCheck:
    """One field of a model's proposal and its check.

    - `proposed`: what the model answered for the field, unchanged.
    - `evidence`: the excerpt the model quoted, if any.
    - `value`: the checked value as JSON (contact, type or topic id, tag ids, ISO date,
      field value), set if the field is OK; it was applied to the document.
    - `suggestion`: for an uncertain field, a value a person may accept as it is (an existing
      contact, a date or field value that is valid but not shown in the text).
    - `new_name`: the name of a contact or type the model proposed that does not exist; only
      an admin can create it.
    - `quote_shows_value`: whether the quoted passage itself shows the proposed value (a
      contact's name, the date, the amount), or only leads to it (a customer number for the
      contact, a passage for a yes/no field); None without a quote.
    - `locations`: where the quote stands on the pages of the archive PDF; none if it was not
      found there (or before this was recorded).
    - `candidates`: the values the signals proposed, best first, with their sources (the
      judge's checks; none in others, and in entries from before the signals).
    - `label`: the label the model gave for the value and whether the value stands by it
      (`labels.check_label`); recorded for fields the model read a value for, it changes no
      outcome (issue #55, step 1). None for other checks and entries from before it.
    """

    field: str
    outcome: Outcome
    confidence: float
    reason: str | None = None
    proposed: JsonValue = None
    evidence: str | None = None
    value: JsonValue = None
    suggestion: JsonValue = None
    new_name: str | None = None
    quote_shows_value: bool | None = None
    locations: tuple[Location, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    label: LabelCheck | None = None

    def __post_init__(self) -> None:
        if self.outcome is Outcome.FAILED:
            raise ValidationError("a field is either OK or uncertain")
        if self.outcome is Outcome.UNCERTAIN and not self.reason:
            raise ValidationError(f"uncertain field {self.field} needs a reason")
        if not 0 <= self.confidence <= 1:
            raise ValidationError(f"confidence must be between 0 and 1, got {self.confidence}")

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.OK

    def to_json(self) -> JsonObject:
        return {
            "field": self.field,
            "outcome": self.outcome.value,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "proposed": self.proposed,
            "evidence": self.evidence,
            "value": self.value,
            "suggestion": self.suggestion,
            "new_name": self.new_name,
            "quote_shows_value": self.quote_shows_value,
            "locations": locations_to_json(self.locations),
            "candidates": [candidate.to_json() for candidate in self.candidates],
            "label": None if self.label is None else self.label.to_json(),
        }

    @classmethod
    def from_json(cls, data: JsonValue) -> Self:
        if not isinstance(data, dict):
            raise ValidationError(f"invalid field check {data!r}")
        try:
            confidence = as_number(data["confidence"])
            if confidence is None:
                raise ValidationError(f"invalid confidence {data['confidence']!r}")
            return cls(
                field=str(data["field"]),
                outcome=Outcome(str(data["outcome"])),
                confidence=float(confidence),
                reason=as_text(data.get("reason")),
                proposed=data.get("proposed"),
                evidence=as_text(data.get("evidence")),
                value=data.get("value"),
                suggestion=data.get("suggestion"),
                new_name=as_text(data.get("new_name")),
                quote_shows_value=as_bool(data.get("quote_shows_value")),
                locations=locations_from_json(data.get("locations")),
                candidates=_candidates(data.get("candidates")),
                label=LabelCheck.from_json(data.get("label")),
            )
        except (KeyError, ValueError) as error:
            raise ValidationError(f"invalid field check: {error}") from None


def checks_to_json(checks: list[FieldCheck]) -> list[JsonValue]:
    return [check.to_json() for check in checks]


def checks_from_json(data: JsonValue) -> list[FieldCheck]:
    """The checks of a log entry's output (`fields`); none if there are none."""
    if not isinstance(data, list):
        return []
    return [FieldCheck.from_json(item) for item in data]


def _candidates(value: JsonValue) -> tuple[Candidate, ...]:
    return tuple(Candidate.from_json(item) for item in as_list(value))
