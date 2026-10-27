"""Webhooks and the log of their deliveries."""

from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.core.domain.documents import UNSET, Unset
from lekto.core.domain.tasks import DEFAULT_TIMEOUT, MAX_TIMEOUT, MIN_TIMEOUT
from lekto.core.domain.validation import MAX_URL_LENGTH
from lekto.core.domain.webhooks import (
    ALL_EVENTS,
    DEFAULT_OPEN_TASKS,
    MAX_BODY_TEMPLATE,
    MAX_HEADER_VALUE,
    MAX_HEADERS,
    MAX_NAME_LENGTH,
    MAX_OPEN_TASKS,
    BodyFormat,
    DeliveryOutcome,
    ModelCallKind,
    ModelCallRole,
    Webhook,
    WebhookDelivery,
    event_type_names,
)
from lekto.core.services._access import DocumentRef
from lekto.core.services.webhooks import CreatedWebhook
from lekto.core.services.webhooks.management import (
    DeliveriesPage,
    DeliverySummary,
    DeliveryView,
)

EVENT_TYPES_HELP = (
    f"Event types: {', '.join(f'`{name}`' for name in event_type_names())}, or `{ALL_EVENTS}` "
    "for all, also future ones."
)
HEADERS_HELP = (
    f"Headers of the webhook's own, sent with every request (at most {MAX_HEADERS}), e.g. "
    "`Authorization` for a token the receiver checks. Lekto sets `content-type`, "
    "`content-length`, `host`, `connection`, `transfer-encoding` and the headers beginning "
    "with `webhook-` or `lekto-` itself; those are refused. The values are stored encrypted "
    "and never shown again; the names are."
)


BODY_HELP = (
    "What a request carries: `thin`, the event (`id`, `type`, `occurred_at`, `document_id`); "
    "`full`, the event and `document` as it is when the request goes (title, contact, type, "
    "topic, tags, date, space, lane, the fields with a value by key, `link` into the web UI); "
    "`template`, the JSON `body_template` makes of them."
)
BODY_TEMPLATE_HELP = (
    "For `body: template`: Liquid that makes JSON. It sees what a rule's template sees "
    "(`title`, `contact`, `field.<key>`, ...), `event` (`type`, `id`, `occurred_at`), "
    "`document_id`, `lane` and `link`; in a rule's request `rule` (`id`, `name`), in a task's "
    "also `task` (`id`, `callback`, `token`, `deadline`) and `steps.<name>`. The filter `json` "
    "writes a value as JSON (`{{ title | json }}`), `| default: nil` a missing one as `null`."
)
OPEN_TASKS_HELP = (
    f"How many tasks (requests that expect an answer, e.g. a rule step that asks) the webhook "
    f"takes at the same time, 1 to {MAX_OPEN_TASKS}; more wait in Lekto, and their time to "
    "answer starts when they are sent."
)


MODEL_CALL_HELP = (
    "The request to the language model the webhook takes over, for every document: `propose` "
    "(the proposal of `signal_llm`) or `extract` (the values of the fields the proposal did not "
    "give, in `fields`). Lekto sends it as a task with a fixed contract (`external.propose`, "
    "`external.extract` under `webhooks`), whatever `body` says. Only an admin gives it to an "
    "admin's webhook; of the active webhooks at most one serves each kind (409). null: none."
)


class WebhookModelCallIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ModelCallKind
    timeout_seconds: int = Field(
        default=int(DEFAULT_TIMEOUT.total_seconds()),
        ge=int(MIN_TIMEOUT.total_seconds()),
        le=int(MAX_TIMEOUT.total_seconds()),
        description="How long the consumer has to answer, from sending.",
    )

    def role(self) -> ModelCallRole:
        return ModelCallRole(self.kind, timedelta(seconds=self.timeout_seconds))


class WebhookModelCallOut(BaseModel):
    kind: ModelCallKind
    timeout_seconds: int

    @classmethod
    def of(cls, role: ModelCallRole | None) -> "WebhookModelCallOut | None":
        if role is None:
            return None
        return cls(kind=role.kind, timeout_seconds=int(role.timeout.total_seconds()))


class HeaderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100, examples=["Authorization"])
    value: str = Field(
        min_length=1,
        max_length=MAX_HEADER_VALUE,
        repr=False,
        description="Without line breaks or other control characters.",
        examples=["Bearer <token>"],
    )


class HeaderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100, examples=["Authorization"])
    value: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_HEADER_VALUE,
        repr=False,
        description="Left out or null: the header keeps the value it has (a new header needs one).",
    )


class WebhookCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "n8n",
                    "url": "http://n8n.lan:5678/webhook/lekto",
                    "event_types": ["document.lane_changed", "document.filed"],
                }
            ]
        },
    )

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH, description="Shown in lists.")
    url: str = Field(
        max_length=MAX_URL_LENGTH,
        description=(
            "Where Lekto sends the events (POST). `http` or `https`; targets in the own "
            "network are fine. Redirects are not followed."
        ),
    )
    event_types: list[str] = Field(
        default=[], description=EVENT_TYPES_HELP + " None: the webhook serves rules only."
    )
    active: bool = True
    signed: bool = Field(
        default=True,
        description=(
            "With a secret that signs every request (`webhook-signature`, Standard Webhooks), "
            "shown once in the answer. Without: no signature, e.g. for a receiver that checks "
            "a header instead."
        ),
    )
    headers: list[HeaderIn] = Field(default=[], max_length=MAX_HEADERS, description=HEADERS_HELP)
    body: BodyFormat = Field(default=BodyFormat.THIN, description=BODY_HELP)
    body_template: str | None = Field(
        default=None, max_length=MAX_BODY_TEMPLATE, description=BODY_TEMPLATE_HELP
    )
    max_open_tasks: int = Field(
        default=DEFAULT_OPEN_TASKS, ge=1, le=MAX_OPEN_TASKS, description=OPEN_TASKS_HELP
    )
    model_call: WebhookModelCallIn | None = Field(default=None, description=MODEL_CALL_HELP)


class WebhookPatch(BaseModel):
    """Fields left out stay as they are."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"active": False}]})

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    url: str | None = Field(default=None, max_length=MAX_URL_LENGTH)
    event_types: list[str] | None = Field(
        default=None, description=EVENT_TYPES_HELP + " Empty: the webhook serves rules only."
    )
    active: bool | None = Field(
        default=None, description="Switching on clears the failure count and the reason."
    )
    headers: list[HeaderPatch] | None = Field(
        default=None,
        max_length=MAX_HEADERS,
        description="All of the webhook's own headers from now on (empty: none). " + HEADERS_HELP,
    )
    body: BodyFormat | None = Field(
        default=None, description=BODY_HELP + " Left out: body and template stay."
    )
    body_template: str | None = Field(
        default=None,
        max_length=MAX_BODY_TEMPLATE,
        description=BODY_TEMPLATE_HELP + " Only together with `body`.",
    )
    max_open_tasks: int | None = Field(
        default=None, ge=1, le=MAX_OPEN_TASKS, description=OPEN_TASKS_HELP
    )
    model_call: WebhookModelCallIn | None = Field(
        default=None, description=MODEL_CALL_HELP + " Left out: it stays."
    )

    def model_call_change(self) -> ModelCallRole | Unset | None:
        """The model call from now on; UNSET if it was left out."""
        if "model_call" not in self.model_fields_set:
            return UNSET
        return None if self.model_call is None else self.model_call.role()


class WebhookOut(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    url: str
    event_types: list[str]
    active: bool
    signed: bool = Field(description="Whether requests carry a `webhook-signature`.")
    headers: list[str] = Field(description="The names of the webhook's own headers, in order.")
    body: BodyFormat = Field(description=BODY_HELP)
    body_template: str | None = Field(description=BODY_TEMPLATE_HELP)
    max_open_tasks: int = Field(description=OPEN_TASKS_HELP)
    model_call: WebhookModelCallOut | None = Field(description=MODEL_CALL_HELP)
    disabled_reason: str | None = Field(
        description="`failing`: Lekto switched the webhook off after repeated failed deliveries."
    )
    failed_streak: int = Field(description="Deliveries given up in a row since the last success.")
    previous_secret_valid_until: datetime | None = Field(
        description=(
            "After renewing the secret: until then requests carry a second signature made with "
            "the old secret."
        )
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, webhook: Webhook) -> "WebhookOut":
        return cls(
            id=webhook.id,
            owner_id=webhook.owner_id,
            name=webhook.name,
            url=webhook.url,
            event_types=sorted(webhook.event_types),
            active=webhook.active,
            signed=webhook.signed,
            headers=list(webhook.header_names),
            body=webhook.body,
            body_template=webhook.body_template,
            max_open_tasks=webhook.max_open_tasks,
            model_call=WebhookModelCallOut.of(webhook.model_call),
            disabled_reason=webhook.disabled_reason,
            failed_streak=webhook.failed_streak,
            previous_secret_valid_until=webhook.previous_valid_until,
            created_at=webhook.created_at,
            updated_at=webhook.updated_at,
        )


class WebhookCreated(WebhookOut):
    secret: str | None = Field(
        repr=False,
        description=(
            "The signing secret (`whsec_…`); shown only now. Receivers verify the "
            "`webhook-signature` header with it. null for a webhook created without one."
        ),
        examples=["whsec_<secret shown once>"],
    )

    @classmethod
    def created(cls, created: CreatedWebhook) -> "WebhookCreated":
        return cls(**WebhookOut.of(created.webhook).model_dump(), secret=created.secret)


class DeliveryDocumentOut(BaseModel):
    id: UUID
    title: str


class DeliveryOut(BaseModel):
    id: UUID
    webhook_id: UUID
    event_id: UUID = Field(description="As `webhook-id` and `id` in the request.")
    event_type: str
    document_id: UUID | None
    attempt: int = Field(description="1 for the first try of this event.")
    started_at: datetime
    duration_ms: int
    outcome: DeliveryOutcome = Field(
        description=(
            "`delivered`: answered with 2xx. `retrying`: failed, another attempt follows at "
            "`next_attempt_at`. `gave_up`: failed for good. `dropped`: not sent, because the "
            "owner may no longer see the document or the webhook is off."
        )
    )
    status_code: int | None = Field(description="The receiver's HTTP status, if it answered.")
    error: str | None = Field(description="Why the attempt failed; the answer body is not kept.")
    next_attempt_at: datetime | None
    document: DeliveryDocumentOut | None = Field(
        description="The document of the event, if the caller may read it."
    )
    document_hidden: bool = Field(
        description="It is about a document the caller may not read (or one deleted since)."
    )

    @classmethod
    def of_view(cls, view: DeliveryView) -> "DeliveryOut":
        return cls.of(view.delivery, view.document, hidden=view.document_hidden)

    @classmethod
    def of(
        cls,
        delivery: WebhookDelivery,
        document: DocumentRef | None = None,
        *,
        hidden: bool = False,
    ) -> "DeliveryOut":
        return cls(
            id=delivery.id,
            webhook_id=delivery.webhook_id,
            event_id=delivery.event_id,
            event_type=delivery.event_type,
            document_id=delivery.document_id,
            attempt=delivery.attempt,
            started_at=delivery.started_at,
            duration_ms=delivery.duration_ms,
            outcome=delivery.outcome,
            status_code=delivery.status_code,
            error=delivery.error,
            next_attempt_at=delivery.next_attempt_at,
            document=(
                None
                if document is None
                else DeliveryDocumentOut(id=document.id, title=document.title)
            ),
            document_hidden=hidden,
        )


class DeliveryPageOut(BaseModel):
    items: list[DeliveryOut]
    total: int = Field(description="How many entries match in all.")
    next_offset: int | None = Field(
        description="Pass as `offset` for the next page; null on the last page."
    )

    @classmethod
    def of(cls, page: DeliveriesPage, offset: int) -> "DeliveryPageOut":
        end = offset + len(page.deliveries)
        return cls(
            items=[DeliveryOut.of_view(view) for view in page.deliveries],
            total=page.total,
            next_offset=end if page.deliveries and end < page.total else None,
        )


class DeliverySummaryOut(BaseModel):
    delivered: int = Field(description="Entries answered with 2xx.")
    retrying: int = Field(description="Entries whose attempt failed, another one follows.")
    gave_up: int = Field(description="Entries that failed for good.")
    dropped: int = Field(description="Entries not sent (document out of reach, webhook off).")
    event_types: list[str] = Field(description="The event types the log holds, by name.")
    kept_since: datetime = Field(description="Older entries are removed (the retention period).")

    @classmethod
    def of(cls, summary: DeliverySummary) -> "DeliverySummaryOut":
        def count(outcome: DeliveryOutcome) -> int:
            return summary.counts.get(outcome, 0)

        return cls(
            delivered=count(DeliveryOutcome.DELIVERED),
            retrying=count(DeliveryOutcome.RETRYING),
            gave_up=count(DeliveryOutcome.GAVE_UP),
            dropped=count(DeliveryOutcome.DROPPED),
            event_types=list(summary.event_types),
            kept_since=summary.kept_since,
        )
