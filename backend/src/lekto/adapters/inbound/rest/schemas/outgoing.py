"""What Lekto sends to webhooks (`webhooks` of the OpenAPI document): the events, a rule's
request, a rule step's task and the model calls. Lekto makes these bodies itself
(`domain.webhooks.event_body`, `classification.external`); the models only describe them."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.core.domain.fields import FieldType
from lekto.core.domain.webhooks import RULE_ASK, RULE_SEND, TEST_EVENT, event_type_names
from lekto.core.services.classification.external import EXTRACT_CONTRACT, PROPOSE_CONTRACT


class Sent(BaseModel):
    """What Lekto sends has exactly these keys: a key more is a change of the contract."""

    model_config = ConfigDict(extra="forbid")


EventType = Literal[tuple([*event_type_names(), TEST_EVENT])]  # type: ignore[valid-type]


class Named(Sent):
    id: UUID
    name: str


class SentDocument(Sent):
    """The document as it is when the request goes (body `full`)."""

    id: UUID
    title: str
    original_filename: str
    contact: Named | None
    document_type: Named | None
    topic: Named | None
    tags: list[Named]
    document_date: date | None
    added: date = Field(description="When it came in.")
    space: Named | None
    lane: Literal["green", "yellow", "red"] | None
    channel: str
    pages: int | None
    fields: dict[str, Any] = Field(
        description="The fields with a value, by key, each in its JSON form."
    )
    link: str | None = Field(
        description="Into the web UI (`LEKTO_PUBLIC_URL`); null without a public URL."
    )


class SentRule(Sent):
    id: UUID
    name: str


class SentTask(Sent):
    """A task: answer it at `callback` with `token` as `Authorization: Bearer` by `deadline`
    (`POST /api/v1/external/tasks/{id}/result`)."""

    id: UUID
    callback: str
    token: str = Field(description="One-time token (`lkt_…`).")
    deadline: datetime


class EventBody(Sent):
    """An event (body `thin`), with the document for body `full`."""

    id: UUID = Field(
        description="The event's id, also in `webhook-id`: a repeated request has it too."
    )
    type: EventType  # type: ignore[valid-type]
    occurred_at: datetime
    document_id: UUID | None = Field(description="null for `webhook.test`.")
    document: SentDocument | None = Field(
        default=None,
        description="Body `full` only; null when the document is gone (`document.deleted`).",
    )


class RuleSendBody(Sent):
    """A rule's request (`rule.send`), when the document is filed (on arrival) or when the
    rule is applied to existing documents."""

    id: UUID
    type: Literal["rule.send"] = RULE_SEND  # type: ignore[assignment]
    occurred_at: datetime
    document_id: UUID
    rule: SentRule
    document: SentDocument | None = Field(default=None, description="Body `full` only.")


class RuleAskBody(Sent):
    """A rule step that asks (`rule.ask`): a task. Its answer (`answer` of the envelope, any
    JSON) is `steps.<name>` for the steps after it."""

    id: UUID = Field(description="The task's id.")
    type: Literal["rule.ask"] = RULE_ASK  # type: ignore[assignment]
    occurred_at: datetime
    document_id: UUID
    rule: SentRule
    task: SentTask
    document: SentDocument | None = Field(default=None, description="Body `full` only.")
    steps: dict[str, Any] | None = Field(
        default=None, description="Body `full` only: what the rule's steps before brought."
    )


class ModelCallTask(SentTask):
    kind: Literal["external.propose", "external.extract"]
    document_id: UUID
    run: int = Field(description="The document's processing run; a later run refuses the answer.")


class ModelCallDocument(Sent):
    filename: str
    media_type: str
    pages: int | None
    received: date
    text: str = Field(
        description="The text read from the document, in full; pages apart by form feeds."
    )
    structure: str = Field(
        description=(
            "Signed link to `content.json`: the pages, lines and words of the text with their "
            "boxes. Valid until the deadline."
        )
    )
    page_images: list[str] = Field(
        description=(
            "Signed links to the page images (WebP), page 1 first. Valid until the deadline."
        )
    )


class ListedContact(Sent):
    name: str
    aliases: list[str] = Field(description="Other names it is written as.")
    topics: list[str] = Field(description="The topics the contact enables (for `topic`).")


class ListedDocumentType(Sent):
    name: str
    description: str | None
    fields: list[str] = Field(description="The keys of its fields (`fields`).")


class ListedField(Sent):
    name: str
    type: FieldType
    form: str = Field(description="How the answer writes the value.")
    choices: list[str] | None = Field(default=None, description="For `choice` only.")
    description: str | None = Field(default=None, description="What belongs in the field.")


class ListedSpace(Sent):
    key: str = Field(description="What `space` of the answer names (`s1`, …).")
    label: str
    description: str | None


ANSWER_SCHEMA = (
    "The JSON Schema of `answer` (strict: every property required, nothing else allowed, "
    "null for what the document does not show), built from the master data of the moment; "
    "the rules for each value are its `description`. Usable as structured output."
)


class ProposeContext(Sent):
    """`signal_llm`'s request (`external.propose`): the context to propose the document's
    metadata from. No prompt: the consumer makes its own. Lekto checks the answer as a
    language model's: its structure at once (422), its values against the text and the other
    signals; a contact turns green only with a second signal or hard evidence."""

    contract: Literal["propose-ext-1"] = PROPOSE_CONTRACT  # type: ignore[assignment]
    task: ModelCallTask
    document: ModelCallDocument
    contacts: list[ListedContact] = Field(description="The 20 contacts the text names most.")
    document_types: list[ListedDocumentType]
    fields: dict[str, ListedField] = Field(description="The fields that may be read, by key.")
    general_fields: list[str] = Field(description="The keys of the fields of every document.")
    tags: list[str]
    spaces: list[ListedSpace] = Field(description="Empty with fewer than two spaces to choose.")
    answer_schema: dict[str, Any] = Field(description=ANSWER_SCHEMA)


class ExtractContext(Sent):
    """`fields`' request (`external.extract`) for the fields the proposal did not give (the
    judge decided another type, or there is no proposal). Lekto checks the answer as a
    language model's."""

    contract: Literal["extract-ext-1"] = EXTRACT_CONTRACT  # type: ignore[assignment]
    task: ModelCallTask
    document: ModelCallDocument
    document_type: str | None
    fields: dict[str, ListedField] = Field(description="The fields to read, by key.")
    answer_schema: dict[str, Any] = Field(description=ANSWER_SCHEMA)
