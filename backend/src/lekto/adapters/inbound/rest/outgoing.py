"""The `webhooks` of the OpenAPI document: the requests Lekto sends (`schemas.outgoing`), so a
consumer can be built against the contract. Lekto never serves these routes."""

from fastapi import FastAPI

from lekto.adapters.inbound.rest.schemas.outgoing import (
    EventBody,
    ExtractContext,
    ProposeContext,
    RuleAskBody,
    RuleSendBody,
)
from lekto.core.domain.json_value import JsonObject


def _header(name: str, description: str, *, required: bool = True) -> JsonObject:
    return {
        "name": name,
        "in": "header",
        "required": required,
        "schema": {"type": "string"},
        "description": description,
    }


SIGNED = [
    _header("webhook-id", "The event's (or task's) id; the same in a repeated request."),
    _header("webhook-timestamp", "Unix seconds of the attempt."),
    _header(
        "webhook-signature",
        "With a secret only: `v1,<base64 HMAC-SHA256>` of `<id>.<timestamp>.<body>` "
        "(Standard Webhooks), several apart by spaces while a renewed secret signs too.",
        required=False,
    ),
]
TASK = [
    _header("lekto-task-id", "The task's id."),
    _header("lekto-callback", "Where to answer (`POST`)."),
    _header("lekto-task-token", "The one-time token, as `Authorization: Bearer` of the answer."),
    _header("lekto-deadline", "Until when the answer is taken (UTC)."),
]
DELIVERED = {
    "2XX": {
        "description": (
            "Taken. Other answers, or none, count as failed: an event is repeated with growing "
            "pauses, a task's request until its deadline. A task is answered at its callback, "
            "not here."
        )
    }
}
BODY_NOTE = (
    "\n\nThe body as the webhook's `body` says: `thin`, `full`, or what its own template makes "
    "(then any JSON)."
)


def describe(app: FastAPI) -> None:
    """Add the requests Lekto sends to `app`'s webhooks."""

    @app.webhooks.post(
        "events",
        operation_id="webhook_events",
        summary="An event about a document",
        description=(
            "To the webhooks that subscribed to its type (`event_types`), for the documents "
            "their owner may read; `webhook.test` on request." + BODY_NOTE
        ),
        openapi_extra={"parameters": SIGNED},
    )
    def events(body: EventBody) -> None:
        """Described only."""

    @app.webhooks.post(
        "rule.send",
        operation_id="webhook_rule_send",
        summary="A rule sends",
        description="A rule's step `send_webhook`, through its author's webhook." + BODY_NOTE,
        openapi_extra={"parameters": SIGNED},
    )
    def rule_send(body: RuleSendBody) -> None:
        """Described only."""

    @app.webhooks.post(
        "rule.ask",
        operation_id="webhook_rule_ask",
        summary="A rule asks",
        description=(
            "A rule's step `ask_webhook`: a task, answered at its callback. Template bodies see "
            "`task` too." + BODY_NOTE
        ),
        openapi_extra={"parameters": SIGNED + TASK},
    )
    def rule_ask(body: RuleAskBody) -> None:
        """Described only."""

    @app.webhooks.post(
        "external.propose",
        operation_id="webhook_external_propose",
        summary="The model call `propose`",
        description=(
            "To the admin's webhook that serves as `propose`, for every document: the context "
            "of `signal_llm`, always as this JSON, whatever the webhook's `body`. Answer with "
            "`status: ok` and `answer` after `answer_schema`; an error, an answer that does not "
            "fit (422) or none by the deadline make the document red."
        ),
        openapi_extra={"parameters": SIGNED + TASK},
    )
    def external_propose(body: ProposeContext) -> None:
        """Described only."""

    @app.webhooks.post(
        "external.extract",
        operation_id="webhook_external_extract",
        summary="The model call `extract`",
        description=(
            "To the admin's webhook that serves as `extract`, when the judge decided another "
            "type than the proposal: the fields of that type to read, always as this JSON. "
            "Answered as `external.propose`."
        ),
        openapi_extra={"parameters": SIGNED + TASK},
    )
    def external_extract(body: ExtractContext) -> None:
        """Described only."""


def delivered(schema: dict[str, object]) -> None:
    """The answers of the webhooks in `schema`: any 2xx (FastAPI's own are of a route)."""
    webhooks = schema.get("webhooks")
    if not isinstance(webhooks, dict):
        return
    for item in webhooks.values():
        for operation in item.values():
            operation["responses"] = DELIVERED
