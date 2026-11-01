"""The inbox: its tabs and summary, open fields, review and confirmation."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.adapters.inbound.rest.schemas.documents import DocumentDetails, DocumentPatch
from lekto.adapters.inbound.schemas import ReasonOut
from lekto.core.domain.classification import Candidate, CandidateSource, FieldCheck
from lekto.core.domain.inbox import Departure, Done, InboxTab
from lekto.core.domain.labels import LABEL_LINES, LabelCheck, LabelOutcome
from lekto.core.domain.locations import Box, Location
from lekto.core.domain.pipeline import Lane, Node, Outcome
from lekto.core.services.inbox import (
    InboxItem,
    InboxSummary,
    NodeReview,
    OpenNode,
    Review,
)

ResumeNode = StrEnum(  # type: ignore[misc]
    "ResumeNode", {node.name: node.value for node in (Node.FIELDS, Node.APPLY_RULES)}
)
"""Nodes processing can resume with after a confirmation."""


class BoxOut(BaseModel):
    """A rectangle on the page as shown (rotation applied), in fractions of its width and
    height from the top left corner."""

    x: float
    y: float
    width: float
    height: float

    @classmethod
    def of(cls, box: Box) -> "BoxOut":
        return cls(x=box.x, y=box.y, width=box.width, height=box.height)


class LocationOut(BaseModel):
    """Where a quote stands in the archive PDF."""

    page: int = Field(description="From 1.")
    boxes: list[BoxOut] = Field(description="One per line the quote covers.")

    @classmethod
    def of(cls, location: Location) -> "LocationOut":
        return cls(page=location.page, boxes=[BoxOut.of(box) for box in location.boxes])


class LabelCheckOut(BaseModel):
    """The label the model gave for a field's value, and whether the value stands by it."""

    text: str | None = Field(
        description="The label as the model copied it from the document; null for none."
    )
    outcome: LabelOutcome = Field(
        description=(
            "`beside`: the value stands on the label's line to its right, or below it in its "
            f"column within {LABEL_LINES} lines; `apart`: the label stands in the text, the "
            "value not by it; `label_missing`: the label is not in the text (as whole words); "
            "`no_label`: the model gave none; `unknown`: no words with boxes, the value not "
            "found, or a type that is not checked (only amounts, numbers, dates and periods "
            "are)."
        )
    )

    @classmethod
    def of(cls, check: LabelCheck) -> "LabelCheckOut":
        return cls(text=check.text, outcome=check.outcome)


class Signal(StrEnum):
    LLM = Node.SIGNAL_LLM.value
    CLASSIFIER = Node.SIGNAL_CLASSIFIER.value
    NEIGHBOURS = Node.SIGNAL_NEIGHBOURS.value
    FACTS = Node.SIGNAL_FACTS.value


class CandidateSourceOut(BaseModel):
    """What one signal says about a candidate."""

    signal: Signal
    names: bool = Field(
        description="Sure enough to name the value: it counts for the judge's rule."
    )
    score: float | None = Field(
        default=None,
        description=(
            "`signal_llm`: how well the name the model read matches the contact (the model "
            "gives no probability of its own); `signal_classifier`: the probability; "
            "`signal_neighbours`: the share of the similar documents that carry the value."
        ),
    )
    threshold: float | None = Field(
        default=None,
        description=(
            "The score from which the signal names a value (`signal_llm`: "
            "`LEKTO_CONFIDENCE_THRESHOLD`; `signal_classifier`: `LEKTO_CLASSIFIER_THRESHOLD`). "
            "The similar documents name a value by their votes instead."
        ),
    )
    similarity: float | None = Field(
        default=None,
        description=(
            "`signal_neighbours`: the highest similarity of the similar documents that carry "
            "the value, as the search index measures it."
        ),
    )
    votes: int | None = Field(
        default=None, description="`signal_neighbours`: similar documents that carry it."
    )
    found: int | None = Field(
        default=None, description="`signal_neighbours`: similar documents found."
    )
    quote: str | None = Field(default=None, description="`signal_llm`: the quoted passage.")
    identifiers: list[str] = Field(
        default_factory=list,
        description="`signal_facts`: kinds of the contact's identifiers found in the text.",
    )
    documents: list[UUID] = Field(
        default_factory=list,
        description="`signal_neighbours`: the similar documents that carry the value.",
    )
    named_in_text: bool = Field(
        default=False,
        description="`signal_facts`: the contact's name or an alias stands in the text.",
    )
    recipient: bool = Field(
        default=False,
        description=(
            "`signal_llm`, a space: the model proposes the personal space of another user, and "
            "its recipient is that user by their display name (the judge suggests the hand-over)."
        ),
    )

    @classmethod
    def of(cls, source: CandidateSource) -> "CandidateSourceOut":
        return cls(
            signal=Signal(source.signal),
            names=source.names,
            score=None if source.score is None else round(source.score, 4),
            threshold=None if source.threshold is None else round(source.threshold, 4),
            similarity=None if source.similarity is None else round(source.similarity, 4),
            votes=source.votes,
            found=source.of,
            quote=source.quote,
            identifiers=list(source.identifiers),
            documents=[UUID(document) for document in source.documents],
            named_in_text=source.named_in_text,
            recipient=source.recipient,
        )


class CandidateOut(BaseModel):
    """A value the signals proposed for a field."""

    value: Any = Field(
        description=(
            "As the check's value (a contact, type or tag id); null for a name that does not "
            "exist yet."
        )
    )
    label: str = Field(description="The contact's, type's or tag's name, or the name read.")
    sources: list[CandidateSourceOut]
    contradicted: bool = Field(description="A signal named another value against it.")

    @classmethod
    def of(cls, candidate: Candidate) -> "CandidateOut":
        return cls(
            value=candidate.value,
            label=candidate.label,
            sources=[CandidateSourceOut.of(source) for source in candidate.sources],
            contradicted=candidate.contradicted,
        )


class FieldCheckOut(BaseModel):
    """A field the model proposed, and its check."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "field": "contact",
                    "outcome": "uncertain",
                    "confidence": 0.5,
                    "reason": "'Stadtwerke' does not appear in the text",
                    "proposed": "Stadtwerke",
                    "evidence": None,
                    "value": None,
                    "suggestion": "01999d5e-3333-7c1e-b6a3-2f4d5e6f7a8b",
                    "new_name": None,
                }
            ]
        }
    )

    field: str = Field(
        description=(
            "`contact`, `document_type`, `topic`, `tags`, `document_date`, or `field:<id>`. The "
            "topic, as the tags, is never uncertain: one not set comes as a `suggestion`."
        )
    )
    outcome: Outcome = Field(description="`ok` or `uncertain`.")
    confidence: float = Field(
        description=(
            "0 to 1, the rule's summary, not a probability: 1 for a value the judge or the "
            "checks accept, at most 0.89 for an uncertain one. The measured values are in "
            "`candidates` (their `sources`)."
        )
    )
    reason: str | None = Field(
        description=(
            "Why the field is uncertain (for the topic: why it was not set), in English; "
            "several reasons are joined by `; `."
        )
    )
    reasons: list[ReasonOut] = Field(
        default_factory=list, description="The reasons with their codes, in the same order."
    )
    proposed: Any = Field(description="What the model answered, unchanged.")
    evidence: str | None = Field(description="The excerpt the model quoted.")
    value: Any = Field(
        description=(
            "The checked value, applied to the document (`ok` only): an id, a list of tag ids, "
            "a date, or a field value."
        )
    )
    suggestion: Any = Field(
        description="A value that can be accepted as it is (uncertain fields, and the topic)."
    )
    new_name: str | None = Field(
        description="A contact or document type that does not exist; an admin can create it."
    )
    quote_shows_value: bool | None = Field(
        default=None,
        description=(
            "Whether the quote itself shows the proposed value (the contact's name, the date, "
            "the amount); false if it only leads to it (a customer number for the contact); "
            "null without a quote."
        ),
    )
    locations: list[LocationOut] = Field(
        default_factory=list,
        description=(
            "Where the quote stands in the archive PDF: at most a few places, in page order; "
            "empty if it was not found there or the check is older than this."
        ),
    )
    candidates: list[CandidateOut] = Field(
        default_factory=list,
        description=(
            "Contact, document type, topic and tags: the values the signals proposed, best "
            "first, with what each signal said; empty for other fields and older checks."
        ),
    )

    label: LabelCheckOut | None = Field(
        default=None,
        description=(
            "Fields the model read a value for: its label and whether the value stands by it. "
            "Recorded only, it changes no outcome; null for other checks and older ones."
        ),
    )
    unseen_by: list[UUID] = Field(
        default_factory=list,
        description=(
            "`space` only: the users the document names (by an identifier, their birth date or "
            "as the model's recipient) who would not see it where the check leads: the "
            "suggestion, the space it moves to, or the one it lies in. A warning, it changes "
            "no outcome; ids only, as names are the users' own."
        ),
    )

    @classmethod
    def of(cls, check: FieldCheck) -> "FieldCheckOut":
        return cls(
            field=check.field,
            outcome=check.outcome,
            confidence=round(check.confidence, 4),
            reason=check.reason,
            reasons=[ReasonOut.of(reason) for reason in check.reasons],
            proposed=check.proposed,
            evidence=check.evidence,
            value=check.value,
            suggestion=check.suggestion,
            new_name=check.new_name,
            quote_shows_value=check.quote_shows_value,
            locations=[LocationOut.of(location) for location in check.locations],
            candidates=[CandidateOut.of(candidate) for candidate in check.candidates],
            label=None if check.label is None else LabelCheckOut.of(check.label),
            unseen_by=[UUID(user) for user in check.unseen_by],
        )


class OpenNodeOut(BaseModel):
    """A node that was uncertain or failed, with the fields left to decide."""

    node: Node
    outcome: Outcome
    reason: str | None = Field(description="Why, in English; several reasons joined by `; `.")
    reasons: list[ReasonOut] = Field(
        default_factory=list, description="The reasons with their codes, in the same order."
    )
    fields: list[FieldCheckOut] = Field(
        description=(
            "Uncertain fields of classification, field extraction and the rules (also "
            "`space`, `title`, `review`), and of filing (`space`)."
        )
    )

    @classmethod
    def of(cls, item: OpenNode) -> "OpenNodeOut":
        return cls(
            node=item.node,
            outcome=item.outcome,
            reason=item.reason,
            reasons=[ReasonOut.of(reason) for reason in item.reasons],
            fields=[FieldCheckOut.of(check) for check in item.fields],
        )


class InboxDoneOut(BaseModel):
    """How a document left the caller's inbox."""

    how: Departure = Field(
        description=(
            "`confirmed`: a person confirmed it out of yellow or red (it left every inbox); "
            "`seen`: the caller saw it."
        )
    )
    at: datetime
    by: UUID = Field(
        description=(
            "The user who confirmed it, or who saw it (the caller); the account may be gone."
        )
    )
    via_token: str | None = Field(
        None,
        description=(
            "The name of the API token they confirmed or saw it through, as it was then; null "
            "in the web UI."
        ),
    )

    @classmethod
    def of(cls, done: Done) -> "InboxDoneOut":
        via = None if done.via is None else done.via.name
        return cls(how=done.how, at=done.at, by=done.by, via_token=via)


class InboxItemOut(BaseModel):
    document: DocumentDetails
    tab: InboxTab = Field(
        description=(
            "Where it stands: `new` (green by itself, not seen by the caller since it became "
            "new), `review` (yellow), `intervene` (red), `processing` (no lane yet), `done` "
            "(left the caller's inbox in the last 14 days)."
        )
    )
    open: list[OpenNodeOut]
    done: InboxDoneOut | None = Field(description="How it left the inbox; `done` only.")

    @classmethod
    def of(cls, item: InboxItem) -> "InboxItemOut":
        done = item.state.done
        return cls(
            document=DocumentDetails.of(item.document, item.access),
            tab=item.state.tab,
            open=[OpenNodeOut.of(node) for node in item.open],
            done=None if done is None else InboxDoneOut.of(done),
        )


class InboxPage(BaseModel):
    items: list[InboxItemOut]
    next_cursor: str | None = Field(
        description="Pass as `cursor` for the next page; null on the last page."
    )


class InboxSummaryOut(BaseModel):
    """How many documents stand under each tab of the caller's inbox."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "new": 3,
                    "review": 1,
                    "intervene": 0,
                    "processing": 2,
                    "done": 12,
                    "open": 6,
                    "worst_lane": "yellow",
                }
            ]
        }
    )

    new: int
    review: int
    intervene: int
    processing: int
    done: int
    open: int = Field(description="Everything open: all tabs but `done`.")
    worst_lane: Lane | None = Field(
        description=(
            "The worst lane among the open documents, `red` before `yellow` before `green` "
            "(new ones); null with only documents in processing, or none."
        )
    )

    @classmethod
    def of(cls, summary: InboxSummary) -> "InboxSummaryOut":
        counts = summary.counts
        return cls(
            **{tab.value: counts.get(tab, 0) for tab in InboxTab},
            open=summary.open,
            worst_lane=summary.worst_lane,
        )


class InboxSeenOut(BaseModel):
    marked: int = Field(description="The documents marked as seen.")


class NodeReviewOut(BaseModel):
    """The latest run of classification or field extraction by the model."""

    node: Node
    run: int
    outcome: Outcome
    reason: str | None
    reasons: list[ReasonOut] = Field(
        default_factory=list, description="The reasons with their codes (`reason` in English)."
    )
    model_version: str | None = Field(examples=["qwen3:8b"])
    truncated: bool | None = Field(description="Whether a part of the text was left out.")
    fields: list[FieldCheckOut]

    @classmethod
    def of(cls, review: NodeReview) -> "NodeReviewOut":
        return cls(
            node=review.node,
            run=review.run,
            outcome=review.outcome,
            reason=review.reason,
            reasons=[ReasonOut.of(reason) for reason in review.reasons],
            model_version=review.model_version,
            truncated=review.truncated,
            fields=[FieldCheckOut.of(check) for check in review.fields],
        )


class ReviewOut(BaseModel):
    document: DocumentDetails
    open: list[OpenNodeOut]
    nodes: list[NodeReviewOut]

    @classmethod
    def of(cls, review: Review) -> "ReviewOut":
        return cls(
            document=DocumentDetails.of(review.document, review.access),
            open=[OpenNodeOut.of(node) for node in review.open],
            nodes=[NodeReviewOut.of(node) for node in review.nodes],
        )


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "changes": {"document_date": "2026-03-31"},
                    "accept_suggestions": True,
                    "resume_at": "apply_rules",
                }
            ]
        },
    )

    changes: DocumentPatch = Field(
        default_factory=DocumentPatch,
        description="A metadata change as with PATCH; decides the fields it sets.",
    )
    accept_suggestions: bool = Field(
        default=False,
        description=(
            "Take the suggestion of every open field that is neither in `changes` nor set on "
            "the document; for an open `space` with a suggestion, that space: the document "
            "moves there (which may show it to more people, as the suggestion says), unless "
            "`space_id` chooses another."
        ),
    )
    resume_at: ResumeNode = Field(
        default=ResumeNode.APPLY_RULES,  # type: ignore[attr-defined]
        description=(
            "`fields` after correcting the document type, so the fields of the new type are read."
        ),
    )
    space_id: UUID | None = Field(
        default=None,
        description=(
            "Move the document into this space (one the caller edits, or another user's "
            "personal space); decides the "
            "rules' open field `space`. Default: it stays where it is."
        ),
    )
