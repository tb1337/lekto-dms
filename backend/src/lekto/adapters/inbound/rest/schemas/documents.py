"""Documents: upload, details, changes, processing."""

from collections.abc import Mapping
from datetime import date, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, Json, field_validator

from lekto.adapters.inbound.rest.schemas.spaces import MemberOut
from lekto.adapters.inbound.schemas import FieldJson, RuleReportOut, field_json
from lekto.core.domain.documents import MAX_TITLE, Channel, Document
from lekto.core.domain.exchanges import ModelCall, RunExchange
from lekto.core.domain.imports import MAX_REVIEW_REASON, MAX_REVIEWS
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.pipeline import (
    Lane,
    Node,
    NodeRun,
    NodeState,
    NodeStatus,
    Outcome,
    ProcessingStatus,
)
from lekto.core.domain.reading import DocumentReading, VisionAdvice
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.services.documents import DocumentFacets
from lekto.core.services.objects import EXCHANGE_NODES

ReprocessNode = StrEnum(  # type: ignore[misc]
    "ReprocessNode", {node.name: node.value for node in Node if node is not Node.RECEIVE}
)
"""Nodes processing can restart from; receiving cannot be repeated."""

ExchangeNode = StrEnum(  # type: ignore[misc]
    "ExchangeNode", {node.name: node.value for node in EXCHANGE_NODES}
)
"""Nodes that ask a language model (OCR: the vision language model)."""


class DocumentAccepted(BaseModel):
    id: UUID
    status_url: str = Field(description="Where to follow the processing.")


class NodeStateOut(BaseModel):
    node: Node
    status: NodeStatus = Field(
        description=(
            "`waiting`: not run yet (it runs once the nodes it needs are done); `running`: a "
            "worker is at it; `done`: has an outcome; `skipped`: left out in this run."
        )
    )
    outcome: Outcome | None = Field(description="Set once the node is done.")
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def of(cls, node: Node, state: NodeState) -> "NodeStateOut":
        return cls(
            node=node,
            status=state.status,
            outcome=state.outcome,
            started_at=state.started_at,
            finished_at=state.finished_at,
        )


class Processing(BaseModel):
    status: ProcessingStatus = Field(
        description=(
            "`processing`: nodes are due or running; `review`: stopped before filing until the "
            "uncertain fields are confirmed; `completed`; `failed`: a node failed (nodes still "
            "running finish, nothing new starts)."
        )
    )
    run: int = Field(description="Grows with every retry or reprocessing.")
    nodes: list[NodeStateOut] = Field(
        description=(
            "The state of every node of the graph in the current run, in graph order: every "
            "node after the nodes it needs."
        )
    )
    vision: bool = Field(
        description=(
            "A person asked that this run read the pages with the vision language model "
            "(`POST /documents/{id}/vision`): the OCR node sends every page to it."
        )
    )


# A document as the API shows it, for the examples of the schemas.
_DOCUMENT_EXAMPLE: dict[str, Any] = {
    "id": "01999d5e-8a7f-7c1e-b6a3-2f4d5e6f7a8b",
    "title": "Electricity bill March",
    "original_filename": "scan_0042.pdf",
    "media_type": "application/pdf",
    "channel": "web",
    "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "uploaded_by": "01999d5e-1111-7c1e-b6a3-2f4d5e6f7a8b",
    "space_id": "01999d5e-2222-7c1e-b6a3-2f4d5e6f7a8b",
    "access": "edit",
    "contact_id": "01999d5e-3333-7c1e-b6a3-2f4d5e6f7a8b",
    "document_type_id": None,
    "topic_id": None,
    "tag_ids": [],
    "document_date": "2026-03-31",
    "fields": {
        "01999d5e-4444-7c1e-b6a3-2f4d5e6f7a8b": {
            "amount": "84.20",
            "currency": "EUR",
        }
    },
    "lane": "green",
    "first_lane": "green",
    "page_count": 2,
    "confirmed_at": None,
    "space_confirmed_at": None,
    "processing": {
        "status": "completed",
        "run": 1,
        "vision": False,
        "nodes": [
            {
                "node": "receive",
                "status": "done",
                "outcome": "ok",
                "started_at": "2026-04-02T08:15:00Z",
                "finished_at": "2026-04-02T08:15:00Z",
            },
            {
                "node": "ocr",
                "status": "done",
                "outcome": "ok",
                "started_at": "2026-04-02T08:15:01Z",
                "finished_at": "2026-04-02T08:15:40Z",
            },
        ],
    },
    "created_at": "2026-04-02T08:15:00Z",
    "updated_at": "2026-04-02T08:16:10Z",
}


class DocumentDetails(BaseModel):
    """A document's metadata and processing state, with the caller's access."""

    model_config = ConfigDict(json_schema_extra={"examples": [_DOCUMENT_EXAMPLE]})

    id: UUID
    title: str
    original_filename: str
    media_type: str = Field(examples=["application/pdf"])
    channel: Channel = Field(
        description="How the document arrived: `web` (web UI), `api`, `migration`."
    )
    sha256: str = Field(
        description="SHA-256 of the original file, in lower-case hex.",
        examples=["9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"],
    )
    uploaded_by: UUID | None = Field(
        description=(
            "Who put the document into Lekto; information only, no rights come with it. Null "
            "once their account is deleted."
        )
    )
    space_id: UUID = Field(description="The space it lies in: its members have the rights.")
    access: SpaceRole = Field(
        description=(
            "What the caller may do: `read`, or `edit` (change, confirm, move, delete); admins "
            "edit every document."
        )
    )
    contact_id: UUID | None
    document_type_id: UUID | None
    topic_id: UUID | None = Field(
        description="A topic (tag of scope `topic`) the contact enables; at most one."
    )
    tag_ids: list[UUID]
    document_date: date | None
    fields: dict[UUID, FieldJson] = Field(description="Values by field id.")
    lane: Lane | None = Field(description="None while processing runs.")
    first_lane: Lane | None = Field(
        description=(
            "The lane the document's first processing run ended in by itself, where it first "
            "stopped: `green` went through without a review, `yellow` needed one, `red` failed. "
            "It never changes afterwards, neither by a confirmation nor by a later run. Null "
            "while the first run is still processing, and for older documents whose processing "
            "log does not tell."
        ),
    )
    page_count: int | None = Field(
        description="Pages of the document, once its page images are rendered (`pages` node)."
    )
    confirmed_at: datetime | None = Field(
        description=(
            "When a person last set or confirmed the metadata (in the inbox, or by changing "
            "contact, type, topic, tags, date or fields; adding or removing tags set by hand "
            "alone does not count), or it was taken over with the source system's; null while "
            "it is the pipeline's own. Confirmed documents train the classifier."
        )
    )
    space_confirmed_at: datetime | None = Field(
        default=None,
        description=(
            "When a person last decided the space: confirming in the inbox (also keeping it), "
            "moving or handing the document over, choosing it on upload, or a migration; null "
            "while the pipeline or rules placed it. Such documents teach the classifier the "
            "space."
        ),
    )
    processing: Processing
    created_at: datetime = Field(
        description=(
            "When the document came in: when Lekto received it, unless a migration took over "
            "the source system's date or it was set since (`PATCH`). `sort=created_at` orders "
            "by it."
        )
    )
    updated_at: datetime

    @classmethod
    def of(cls, document: Document, access: SpaceRole) -> "DocumentDetails":
        state = document.processing
        return cls(
            id=document.id,
            title=document.title,
            original_filename=document.original_filename,
            media_type=document.media_type,
            channel=document.channel,
            sha256=document.sha256.hex,
            uploaded_by=document.uploaded_by,
            space_id=document.space_id,
            access=access,
            contact_id=document.contact_id,
            document_type_id=document.document_type_id,
            topic_id=document.topic_id,
            tag_ids=sorted(document.tag_ids),
            document_date=document.document_date,
            fields={key: field_json(value) for key, value in sorted(document.fields.items())},
            lane=document.lane,
            first_lane=document.first_lane,
            page_count=document.page_count,
            confirmed_at=document.confirmed_at,
            space_confirmed_at=document.space_confirmed_at,
            processing=Processing(
                status=state.status,
                run=state.run,
                nodes=[NodeStateOut.of(node, item) for node, item in state.nodes.items()],
                vision=state.vision,
            ),
            created_at=document.created_at,
            updated_at=document.updated_at,
        )


class ListedDocument(DocumentDetails):
    """A document of a list or a search, with whether it stands in the caller's inbox."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{**_DOCUMENT_EXAMPLE, "in_inbox": True}]}
    )

    in_inbox: bool = Field(
        description=(
            "It stands open in the caller's inbox (`GET /inbox`; with `all_users`, in every "
            "user's): in processing, yellow, red, or new and not seen by the caller."
        )
    )

    @classmethod
    def listed(cls, document: Document, access: SpaceRole, in_inbox: bool) -> "ListedDocument":
        return cls(**DocumentDetails.of(document, access).model_dump(), in_inbox=in_inbox)


class DocumentPage(BaseModel):
    items: list[ListedDocument]
    next_cursor: str | None = Field(
        description="Pass as `cursor` for the next page; null on the last page."
    )


class ValueCount(BaseModel):
    id: UUID | None = Field(description="The contact, type, topic or tag; null: without one.")
    count: int


class MonthCount(BaseModel):
    month: str = Field(description="ISO 8601, `2026-09`.", examples=["2026-09"])
    count: int


class YearCount(BaseModel):
    year: int
    count: int
    months: list[MonthCount] = Field(description="Its months with documents, newest first.")


class DocumentFacetsOut(BaseModel):
    """How many documents of the filter have each value, for the filters of the document view.
    Contacts, types, groups, topics and the period combine as either-or and count without
    their own choice (what one more would add); tags count with the whole filter."""

    total: int = Field(description="The documents of the whole filter.")
    contacts: list[ValueCount] = Field(description="Most first; null: without a contact.")
    document_types: list[ValueCount] = Field(description="Most first; null: without a type.")
    contact_groups: list[ValueCount] = Field(
        description="Most first; a group counts the documents of its contacts and those below."
    )
    document_type_groups: list[ValueCount] = Field(
        description="Most first; a group counts the documents of its types and those below."
    )
    topics: list[ValueCount] = Field(
        description="Most first; a topic counts the documents with it or one below it."
    )
    tags: list[ValueCount] = Field(
        description="Most first; a tag counts the documents with it or one below it."
    )
    years: list[YearCount] = Field(description="By document date, newest first.")
    undated: int = Field(description="Documents without a document date.")

    @classmethod
    def of(cls, facets: DocumentFacets) -> "DocumentFacetsOut":
        def counted(counts: Mapping[Any, int]) -> list[ValueCount]:
            ranked = sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))
            return [ValueCount(id=id, count=count) for id, count in ranked]

        years: dict[int, list[MonthCount]] = {}
        for month, count in sorted(facets.months.items(), reverse=True):
            years.setdefault(int(month[:4]), []).append(MonthCount(month=month, count=count))
        return cls(
            total=facets.total,
            contacts=counted(facets.contacts),
            document_types=counted(facets.document_types),
            contact_groups=counted(facets.contact_groups),
            document_type_groups=counted(facets.document_type_groups),
            topics=counted(facets.topics),
            tags=counted(facets.tags),
            years=[
                YearCount(year=year, count=sum(month.count for month in months), months=months)
                for year, months in years.items()
            ],
            undated=facets.undated,
        )


class DocumentPatch(BaseModel):
    """Fields left out stay as they are; null removes a value. A new contact that does not
    enable the document's topic removes the topic; a topic given must be one the contact
    enables (422), unless an admin gives it: it is then enabled at the contact."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "title": "Electricity bill March",
                    "contact_id": "01999d5e-3333-7c1e-b6a3-2f4d5e6f7a8b",
                    "tag_ids": ["01999d5e-2222-7c1e-b6a3-2f4d5e6f7a8b"],
                    "document_date": "2026-03-31",
                    "fields": {
                        "01999d5e-4444-7c1e-b6a3-2f4d5e6f7a8b": {
                            "amount": "84.20",
                            "currency": "EUR",
                        }
                    },
                }
            ]
        },
    )

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    contact_id: UUID | None = None
    document_type_id: UUID | None = None
    topic_id: UUID | None = None
    tag_ids: list[UUID] | None = Field(default=None, max_length=500)
    document_date: date | None = None
    fields: dict[UUID, Any] | None = Field(
        default=None,
        description="Values by field id, in the form of `fields` above; null removes.",
    )
    created_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "When the document came in, with a time zone; not in the future, not null. Changed "
            "alone, it confirms nothing and the rules do not run."
        ),
    )


class ImportedReviewIn(BaseModel):
    """Why a person should look at a document taken over from another system."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=MAX_REVIEW_REASON)
    field: str | None = Field(
        default=None,
        description=(
            "The field the reason is about (`contact`, `document_type`, `topic`, `tags`, "
            "`document_date`, `title` or `field:<id>`); it is open in the inbox and, without "
            "a value, needs a decision. Null: the document as a whole."
        ),
    )


class ImportedMetadataIn(BaseModel):
    """The metadata a document taken over from another system comes with (form field
    `metadata` of `POST /documents`, as JSON)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "title": "Electricity bill March",
                    "contact_id": "01999d5e-3333-7c1e-b6a3-2f4d5e6f7a8b",
                    "tag_ids": ["01999d5e-2222-7c1e-b6a3-2f4d5e6f7a8b"],
                    "document_date": "2026-03-31",
                    "fields": {"01999d5e-4444-7c1e-b6a3-2f4d5e6f7a8b": "84.20"},
                    "created_at": "2026-04-02T09:15:00+02:00",
                }
            ]
        },
    )

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    contact_id: UUID | None = None
    document_type_id: UUID | None = None
    tag_ids: list[UUID] = Field(default_factory=list, max_length=500)
    document_date: date | None = None
    fields: dict[UUID, Any] = Field(
        default_factory=dict, description="Values by field id, as in `PATCH /documents/{id}`."
    )
    created_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "When the document came in at the source system (Paperless-ngx: `added`), with a "
            "time zone; not in the future. It becomes the document's `created_at`."
        ),
    )
    review: list[ImportedReviewIn] = Field(
        default_factory=list,
        max_length=MAX_REVIEWS,
        description=(
            "Reasons to have a person look at the document: it waits in the inbox (yellow) "
            "with the values applied, and is filed once confirmed."
        ),
    )


METADATA_LIMIT = 48 * 1024  # bytes of the metadata field


class UploadFields(BaseModel):
    """The text fields of the form of `POST /documents`; a blank one counts as not given. The
    form's field names, their OpenAPI schema (`form_schema`) and size limits (`LIMITS`) are
    taken from here."""

    model_config = ConfigDict(extra="forbid")

    LIMITS: ClassVar[Mapping[str, int]] = {"metadata": METADATA_LIMIT}
    """Bytes a field may have; the others up to 1 KiB (`read_upload`)."""

    space_id: UUID | None = Field(
        default=None,
        description=("Target space, one the caller edits; default: the uploader's personal space."),
        json_schema_extra={"format": "uuid"},
    )
    channel: Literal["migration"] | None = Field(
        default=None,
        description=(
            "The intake channel, for rules. Default: `web` with a session, `api` with an "
            "API token; `migration` for imports from another system."
        ),
        json_schema_extra={"enum": [Channel.MIGRATION.value]},
    )
    uploaded_by: UUID | None = Field(
        default=None,
        description=(
            "Admins only: the active user named as the document's uploader. Default: the "
            "caller. Without `space_id` the document goes to their personal space."
        ),
        json_schema_extra={"format": "uuid"},
    )
    metadata: Json[ImportedMetadataIn] | None = Field(
        default=None,
        description=(
            "Admins only, with `channel=migration`: JSON of the metadata the document comes "
            f"with (up to {METADATA_LIMIT // 1024} KiB), as `ImportedMetadataIn`. "
            "Classification and field extraction apply it instead of asking the language "
            "model; the other nodes and the rules run as usual."
        ),
    )

    @classmethod
    def form_schema(cls) -> dict[str, JsonObject]:
        """The OpenAPI schema of each field (`upload_body`): text, as a form sends it."""
        schemas: dict[str, JsonObject] = {}
        for name, field in cls.model_fields.items():
            extra = field.json_schema_extra
            assert extra is None or isinstance(extra, dict)
            schemas[name] = {"type": "string", **(extra or {}), "description": field.description}
        return schemas

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class MoveRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"space_id": "01999d5e-3333-7c1e-b6a3-2f4d5e6f7a8b"}]},
    )

    space_id: UUID


class DocumentTextOut(BaseModel):
    """A piece of the text read from the archive; offsets and lengths count characters."""

    text: str
    offset: int
    total_length: int
    next_offset: int | None = Field(description="Where the next piece starts; null at the end.")


class LogEntry(BaseModel):
    """One execution of one node."""

    node: Node
    run: int
    outcome: Outcome
    reason: str | None
    confidence: float | None = Field(
        description=(
            "The judge's and the fields node's summary of their checks, not a probability: the "
            "lowest of their fields' (`FieldCheckOut.confidence`)."
        )
    )
    model_version: str | None = Field(examples=["ocrmypdf 17.13.0, tesseract 5.5.0"])
    input: dict[str, Any]
    output: dict[str, Any]
    pipeline_version: str
    started_at: datetime
    duration_ms: float

    @classmethod
    def of(cls, run: NodeRun) -> "LogEntry":
        result = run.result
        return cls(
            node=run.node,
            run=run.run,
            outcome=result.outcome,
            reason=result.reason,
            confidence=result.confidence,
            model_version=result.model_version,
            input=dict(result.input),
            output=dict(result.output),
            pipeline_version=run.pipeline_version,
            started_at=run.started_at,
            duration_ms=run.duration.total_seconds() * 1000,
        )


class ModelCallOut(BaseModel):
    """One request to the language model and its answer."""

    system: str = Field(description="The system message.")
    user: str = Field(description="The user message, with the document's text.")
    answer: str = Field(description="The model's text as it came.")
    model: str = Field(examples=["qwen3:8b"])
    usage: dict[str, Any] = Field(
        description=(
            "The endpoint's usage report as it sent it: `prompt_tokens`, `completion_tokens`, "
            "with some endpoints (Ollama through OpenWebUI) durations and speeds; empty if "
            "none."
        )
    )

    @classmethod
    def of(cls, call: ModelCall) -> "ModelCallOut":
        return cls(
            system=call.system,
            user=call.user,
            answer=call.answer,
            model=call.model,
            usage=dict(call.usage),
        )


class RunExchangeOut(BaseModel):
    """What a node sent to the language model in one processing run."""

    run: int
    calls: list[ModelCallOut] = Field(
        description="One call, or two after an answer that did not fit the schema."
    )

    @classmethod
    def of(cls, exchange: RunExchange) -> "RunExchangeOut":
        return cls(run=exchange.run, calls=[ModelCallOut.of(call) for call in exchange.calls])


class ReprocessRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"from_node": "judge"}]}
    )

    from_node: ReprocessNode = Field(
        description="Discard the results from this node on and process again from there."
    )


class DocumentChanged(DocumentDetails):
    rules: list[RuleReportOut] | None = Field(
        default=None,
        description=(
            "For editors: the rules the change set off (they hold now and did not before) "
            "and what they did. Nothing turns yellow; what could not be applied is listed."
        ),
    )


class DocumentOutOfReach(BaseModel):
    """After a change: the rules filed the document where the caller can no longer read it.
    The change is stored; nothing else about the document is shown."""

    id: UUID
    access: None = Field(default=None, description="The caller can no longer read the document.")


class VisibilityOut(BaseModel):
    """Who sees the document: the members of its space; readers only once it is green."""

    space_id: UUID
    members: list[MemberOut] = Field(
        description="The space's members with their roles; readers see the document once green."
    )

    @classmethod
    def of(cls, document: Document, space: Space) -> "VisibilityOut":
        return cls(
            space_id=space.id,
            members=[
                MemberOut(user_id=user, role=role) for user, role in sorted(space.members.items())
            ],
        )


class DocumentPreviewOut(BaseModel):
    """What a change would do; nothing is stored."""

    document: DocumentDetails | None = Field(
        description="The document after the change; null if the caller could not read it then."
    )
    changed: list[str] = Field(
        description="Fields that would change: `title`, `contact`, `document_type`, `topic`, "
        "`tags`, `document_date`, `field:<id>`, `space`."
    )
    rules: list[RuleReportOut] | None = Field(
        description="For editors: the rules the change would set off, and what they would do."
    )
    visibility: VisibilityOut | None = Field(
        description="Who would see the document; null if the caller could not read it then."
    )


class PageReadingOut(BaseModel):
    page: int = Field(description="From 1.")
    words: int = Field(description="The words recognised on the page.")
    unsure: int = Field(
        description=(
            "Of them, those the reader was unsure of: below 60 % of Tesseract's confidence, "
            "or what the vision language model could not read."
        )
    )
    content: int | None = Field(
        description=(
            "Of the words, those that are content: not dot leaders, rules, stray marks of one "
            "or two characters, or small print. Null where content was not counted (read "
            "before it was, or by the vision language model)."
        )
    )
    content_unsure: int | None = Field(
        description="Of the content words, those the reader was unsure of; null with `content`."
    )
    poor: bool = Field(
        description=(
            "The page counts as poorly read (`LEKTO_POOR_READING_THRESHOLD`): by its content "
            "words where counted, else by all."
        )
    )


class ReadingOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "vision": False,
                    "pages": [
                        {
                            "page": 1,
                            "words": 50,
                            "unsure": 6,
                            "content": 42,
                            "content_unsure": 4,
                            "poor": True,
                        }
                    ],
                    "advice": "poor_page",
                }
            ]
        }
    )

    vision: bool = Field(description="The archive's text was read by the vision language model.")
    pages: list[PageReadingOut] = Field(
        description=(
            "Each page the reader recognised, by the archive's latest OCR; none for pages "
            "with text of their own, and for documents read before the readings were logged."
        )
    )
    advice: VisionAdvice | None = Field(
        description=(
            "Why reading the document with the vision language model is advised, if it is: "
            "`no_text`, the OCR found no text (red); `poor_page`, it waits for a person and a "
            "page was read poorly. None once the model has read it."
        )
    )

    @classmethod
    def of(cls, reading: DocumentReading) -> "ReadingOut":
        return cls(
            vision=reading.vision,
            pages=[
                PageReadingOut(
                    page=page.page,
                    words=page.words,
                    unsure=page.unsure,
                    content=page.content,
                    content_unsure=page.content_unsure,
                    poor=page.page in reading.poor,
                )
                for page in reading.pages
            ],
            advice=reading.advice,
        )
