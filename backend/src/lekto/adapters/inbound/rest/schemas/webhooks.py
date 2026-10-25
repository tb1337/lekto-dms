"""Webhooks and the log of their deliveries."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.core.domain.validation import MAX_URL_LENGTH
from lekto.core.domain.webhooks import (
    ALL_EVENTS,
    MAX_BODY_TEMPLATE,
    MAX_HEADER_VALUE,
    MAX_HEADERS,
    MAX_NAME_LENGTH,
    BodyFormat,
    DeliveryOutcome,
    Webhook,
    WebhookDelivery,
    event_type_names,
)
from lekto.core.services.webhooks import CreatedWebhook

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
    "`document_id`, `lane` and `link`; the filter `json` writes a value as JSON "
    "(`{{ title | json }}`), `| default: nil` a missing one as `null`."
)


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
    event_types: list[str] = Field(min_length=1, description=EVENT_TYPES_HELP)
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


class WebhookPatch(BaseModel):
    """Fields left out stay as they are."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"active": False}]})

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    url: str | None = Field(default=None, max_length=MAX_URL_LENGTH)
    event_types: list[str] | None = Field(default=None, min_length=1, description=EVENT_TYPES_HELP)
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

    @classmethod
    def of(cls, delivery: WebhookDelivery) -> "DeliveryOut":
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
        )
