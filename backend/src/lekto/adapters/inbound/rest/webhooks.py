"""`/webhooks`: a user's subscriptions to document events, and the log of their deliveries."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from lekto.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.webhooks import (
    DeliveryOut,
    WebhookCreate,
    WebhookCreated,
    WebhookOut,
    WebhookPatch,
)
from lekto.core.domain.ids import DeliveryId, UserId, WebhookId
from lekto.core.ports.repository import PAGE_LIMIT, PAGE_SIZE
from lekto.core.services.webhooks.policy import TEST_REQUESTS, TEST_WINDOW

router = APIRouter(prefix="/webhooks", tags=["webhooks"], dependencies=PROTECTED)

WHO = (
    "Its owner, or an admin (who also changes, deletes and tests other users' webhooks and "
    "sees the secret only when renewing it). Other users' webhooks are not found (404)."
)


@router.get(
    "",
    summary="List webhooks",
    description=(
        "The caller's webhooks, oldest first; without the secret. Admins get everybody's, "
        "`owner` narrows them to one user."
    ),
    response_model=list[WebhookOut],
    responses=problem_responses(401, 422),
)
async def list_webhooks(
    user: CurrentUser,
    context: Context,
    owner: Annotated[UUID | None, Query(description="Only this user's (admins).")] = None,
) -> list[WebhookOut]:
    found = await context.webhooks.list_webhooks(
        user, owner=None if owner is None else UserId(owner)
    )
    return [WebhookOut.of(webhook) for webhook in found]


@router.post(
    "",
    status_code=201,
    summary="Create a webhook",
    description=(
        "Papiq sends a signed request to the URL for each event of the chosen types on "
        "documents within the owner's reach: their own, and green ones in spaces they own or "
        "that are shared with them (an admin's webhooks too; the rights of an admin do not "
        "widen them). The answer holds the secret, shown only once. A user has at most as "
        "many webhooks as `PAPIQ_WEBHOOKS_PER_USER` allows (409)."
    ),
    response_model=WebhookCreated,
    responses=problem_responses(401, 403, 409, 422),
)
async def create_webhook(
    body: WebhookCreate, user: CurrentUser, context: Context
) -> WebhookCreated:
    created = await context.webhooks.create(
        user, name=body.name, url=body.url, event_types=body.event_types, active=body.active
    )
    return WebhookCreated.created(created)


@router.get(
    "/{id}",
    summary="A webhook",
    description=WHO,
    response_model=WebhookOut,
    responses=problem_responses(401, 404, 422),
)
async def get_webhook(id: UUID, user: CurrentUser, context: Context) -> WebhookOut:
    return WebhookOut.of(await context.webhooks.get(user, WebhookId(id)))


@router.patch(
    "/{id}",
    summary="Change or switch a webhook on or off",
    description=WHO,
    response_model=WebhookOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def update_webhook(
    id: UUID, body: WebhookPatch, user: CurrentUser, context: Context
) -> WebhookOut:
    webhook = await context.webhooks.update(
        user,
        WebhookId(id),
        name=body.name,
        url=body.url,
        event_types=body.event_types,
        active=body.active,
    )
    return WebhookOut.of(webhook)


@router.delete(
    "/{id}",
    status_code=204,
    summary="Delete a webhook",
    description="With its log. " + WHO,
    responses=problem_responses(401, 403, 404, 422),
)
async def delete_webhook(id: UUID, user: CurrentUser, context: Context) -> None:
    await context.webhooks.delete(user, WebhookId(id))


@router.post(
    "/{id}/secret",
    summary="Renew the secret",
    description=(
        "A new secret, shown only now. The old one keeps signing next to it for a while "
        "(`previous_secret_valid_until`), so the receiver can switch without a gap; renewing "
        "again ends that at once. " + WHO
    ),
    response_model=WebhookCreated,
    responses=problem_responses(401, 403, 404, 422),
)
async def renew_secret(id: UUID, user: CurrentUser, context: Context) -> WebhookCreated:
    return WebhookCreated.created(await context.webhooks.renew_secret(user, WebhookId(id)))


@router.get(
    "/{id}/deliveries",
    summary="The delivery log of a webhook",
    description=(
        "Every attempt, newest first: time, event, status, duration, error. The answer of the "
        "receiver is not kept. Old entries are removed after the retention period. " + WHO
    ),
    response_model=list[DeliveryOut],
    responses=problem_responses(401, 404, 422),
)
async def list_deliveries(
    id: UUID,
    user: CurrentUser,
    context: Context,
    before: Annotated[
        UUID | None, Query(description="The `id` of the last entry of the previous page.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=PAGE_LIMIT)] = PAGE_SIZE,
) -> list[DeliveryOut]:
    found = await context.webhooks.deliveries(
        user,
        WebhookId(id),
        before=None if before is None else DeliveryId(before),
        limit=limit,
    )
    return [DeliveryOut.of(delivery) for delivery in found]


@router.post(
    "/{id}/test",
    summary="Send a test request",
    description=(
        "Sends a `webhook.test` request to the URL now, signed like any other, without "
        "repetition; works for a switched-off webhook too. The answer is the entry of the "
        "delivery log: `delivered` for a 2xx answer, else `gave_up` with status or error. "
        f"At most {TEST_REQUESTS} test requests per user in {TEST_WINDOW.total_seconds():g} "
        "seconds; beyond that `429` with `Retry-After`. " + WHO
    ),
    response_model=DeliveryOut,
    responses=problem_responses(401, 403, 404, 422, 429),
)
async def test_webhook(id: UUID, user: CurrentUser, context: Context) -> DeliveryOut:
    return DeliveryOut.of(await context.webhook_delivery.send_test(user, WebhookId(id)))
