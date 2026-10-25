"""Delivering events to webhooks: who is told, signing, answers, repetition, switching off."""

import base64
import hashlib
import hmac
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from lekto.adapters.inbound.rest.schemas.outgoing import EventBody
from lekto.core.domain.documents import Document
from lekto.core.domain.errors import NotFoundError, TooManyAttemptsError
from lekto.core.domain.events import (
    DocumentDeleted,
    DocumentFiled,
    DocumentReceived,
    LaneChanged,
)
from lekto.core.domain.fields import FieldDefinition, FieldType, Money
from lekto.core.domain.ids import DocumentId, WebhookId, new_id
from lekto.core.domain.jobs import Job, JobStatus
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.master_data import Contact, DocumentType
from lekto.core.domain.pipeline import Lane
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import Role, User
from lekto.core.domain.webhooks import (
    DISABLED_FAILING,
    RULE_SEND,
    TEST_EVENT,
    BodyFormat,
    DeliveryOutcome,
    Webhook,
    WebhookDelivery,
)
from lekto.core.ports.webhook_sender import WebhookRequest
from lekto.core.services.webhooks import DELIVER_JOB, WebhookDeliveryService
from lekto.core.services.webhooks.delivery import queue_rule_send
from tests import builders
from tests.builders import NOW
from tests.unit.services.support import World

URL = "http://n8n.lan:5678/webhook/lekto"


async def hook(world: World, owner: User, *types: str, url: str = URL) -> tuple[Webhook, str]:
    created = await world.webhooks.create(owner.id, name="n8n", url=url, event_types=types or ["*"])
    assert created.secret is not None
    return created.webhook, created.secret


async def seed(
    world: World, owner: User, space: Space | None = None, *, green: bool = True
) -> Document:
    """A document of the owner; green, or still in processing."""
    space = space or await world.personal_space(owner)
    document = builders.processed(owner, space) if green else builders.document(owner, space)
    async with world.uow() as uow:
        await uow.documents.add(document)
        await uow.commit()
    return document


def lane_changed(document: Document) -> LaneChanged:
    return LaneChanged(occurred_at=NOW, document_id=document.id, old=None, new=Lane.GREEN)


def deliveries(world: World) -> list[Job]:
    return [j for j in world.database.jobs.values() if j.kind == DELIVER_JOB]


async def log(world: World, webhook: Webhook) -> list[WebhookDelivery]:
    async with world.uow() as uow:
        rows = await uow.webhooks.deliveries(webhook.id)
    # Ids order only to the millisecond.
    return sorted(rows, key=lambda row: (row.started_at, row.attempt))


async def run_all(service: WebhookDeliveryService) -> int:
    return await builders.drain(service)


# --- fan-out ------------------------------------------------------------------------------------


async def test_an_event_is_queued_for_each_webhook_that_wants_its_type(world: World) -> None:
    user = await world.user()
    document = await seed(world, user)
    await hook(world, user, "document.lane_changed")
    await hook(world, user)  # all types
    await hook(world, user, "document.updated")
    off, _ = await hook(world, user)
    await world.webhooks.update(user.id, off.id, active=False)
    await world.webhook_delivery().on_event(lane_changed(document))
    assert len(deliveries(world)) == 2


async def test_only_those_who_may_read_the_document_are_told(world: World) -> None:
    owner, friend, stranger = await world.user(), await world.user(), await world.user()
    shared = builders.space(owner, "shared")
    shared.set_member(friend.id, SpaceRole.READ)
    async with world.uow() as uow:
        await uow.spaces.add(shared)
        await uow.commit()
    in_shared = await seed(world, owner, shared)
    private = await seed(world, owner)
    yellow = await seed(world, owner, shared, green=False)
    service = world.webhook_delivery()
    await hook(world, owner)
    await hook(world, friend)
    await hook(world, stranger)

    await service.on_event(lane_changed(in_shared))  # owner and friend
    assert len(deliveries(world)) == 2
    await service.on_event(lane_changed(private))  # owner only
    assert len(deliveries(world)) == 3
    await service.on_event(lane_changed(yellow))  # not green: owner only
    assert len(deliveries(world)) == 4


async def test_an_admins_webhooks_report_their_reach_only(world: World) -> None:
    """Tobi, 08.10.2026: admins read everything, but their webhooks report only what they reach
    as a user: their own documents and green ones in their spaces and shares."""
    admin, user = await world.user(role=Role.ADMIN), await world.user()
    shared = builders.space(user, "shared")
    shared.set_member(admin.id, SpaceRole.READ)
    async with world.uow() as uow:
        await uow.spaces.add(shared)
        await uow.commit()
    foreign = await seed(world, user)
    in_share = await seed(world, user, shared)
    unfinished = await seed(world, user, shared, green=False)
    own = await seed(world, admin)
    webhook, _ = await hook(world, admin)
    service = world.webhook_delivery()
    for document in (foreign, in_share, unfinished, own):
        await service.on_event(lane_changed(document))
    queued = {job.payload["document_id"] for job in deliveries(world)}
    assert queued == {str(in_share.id), str(own.id)}

    # A deletion is reported to the readers named in the event only: no admin was named.
    await service.on_event(DocumentDeleted(occurred_at=NOW, document_id=foreign.id, readers=()))
    assert len(deliveries(world)) == 2

    # The rights are checked again when sending: still the reach, although the admin may
    # read the document.
    await world.spaces.remove_member(user.id, shared.id, admin.id)
    assert await run_all(service) == 2
    rows = await log(world, webhook)
    dropped = [row.document_id for row in rows if row.outcome is DeliveryOutcome.DROPPED]
    assert dropped == [in_share.id]


async def test_a_deactivated_owner_is_not_told(world: World) -> None:
    admin, user = await world.user(role=Role.ADMIN), await world.user()
    document = await seed(world, user)
    await hook(world, user)
    await world.users.update(admin.id, user.id, active=False)
    await world.webhook_delivery().on_event(lane_changed(document))
    assert deliveries(world) == []


async def test_filed_is_skipped_while_the_document_has_no_lane(world: World) -> None:
    user = await world.user()
    await hook(world, user, "document.filed")
    service = world.webhook_delivery()
    space = await world.personal_space(user)
    early = await seed(world, user, green=False)
    await service.on_event(DocumentFiled(occurred_at=NOW, document_id=early.id, space_id=space.id))
    assert deliveries(world) == []
    done = await seed(world, user)
    await service.on_event(DocumentFiled(occurred_at=NOW, document_id=done.id, space_id=space.id))
    assert len(deliveries(world)) == 1


async def test_a_deleted_document_is_reported_to_the_readers_named_in_the_event(
    world: World,
) -> None:
    owner, friend, stranger = await world.user(), await world.user(), await world.user()
    for user in (owner, friend, stranger):
        await hook(world, user, "document.deleted")
    gone = DocumentId(new_id())
    await world.webhook_delivery().on_event(
        DocumentDeleted(
            occurred_at=NOW,
            document_id=gone,
            readers=(owner.id, friend.id),
        )
    )
    assert len(deliveries(world)) == 2


async def test_an_event_delivered_twice_queues_one_job(world: World) -> None:
    user = await world.user()
    document = await seed(world, user)
    await hook(world, user)
    service = world.webhook_delivery()
    event = lane_changed(document)
    await service.on_event(event)
    await service.on_event(event)
    assert len(deliveries(world)) == 1


async def test_events_without_a_document_or_for_a_vanished_one_queue_nothing(
    world: World,
) -> None:
    user = await world.user()
    await hook(world, user)
    await world.webhook_delivery().on_event(
        DocumentReceived(occurred_at=NOW, document_id=DocumentId(new_id()))
    )
    assert deliveries(world) == []


# --- delivery -----------------------------------------------------------------------------------


def expected_signature(secret: str, request: WebhookRequest) -> str:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    message = request.headers["webhook-id"], request.headers["webhook-timestamp"]
    content = f"{message[0]}.{message[1]}.".encode() + request.body
    return "v1," + base64.b64encode(hmac.new(key, content, hashlib.sha256).digest()).decode()


async def queue(world: World, document: Document, service: WebhookDeliveryService) -> LaneChanged:
    event = lane_changed(document)
    await service.on_event(event)
    return event


async def test_a_delivery_is_signed_sent_and_logged(world: World) -> None:
    user = await world.user()
    document = await seed(world, user)
    webhook, secret = await hook(world, user)
    service = world.webhook_delivery()
    event = await queue(world, document, service)

    assert await service.run_next_job()
    (request,) = world.sender.requests
    assert request.url == URL
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["webhook-id"] == str(event.id)
    assert request.headers["webhook-signature"] == expected_signature(secret, request)
    assert json.loads(request.body) == {
        "id": str(event.id),
        "type": "document.lane_changed",
        "occurred_at": "2026-10-06T12:00:00Z",
        "document_id": str(document.id),
    }
    (row,) = await log(world, webhook)
    assert (row.outcome, row.status_code, row.attempt) == (DeliveryOutcome.DELIVERED, 200, 1)
    assert row.event_id == event.id and row.document_id == document.id
    assert [j.status for j in deliveries(world)] == [JobStatus.DONE]
    assert not await service.run_next_job()


async def test_a_renewed_secret_signs_next_to_the_new_one_during_the_grace_period(
    world: World,
) -> None:
    user = await world.user()
    document = await seed(world, user)
    webhook, old = await hook(world, user)
    new = (await world.webhooks.renew_secret(user.id, webhook.id)).secret
    assert new is not None
    service = world.webhook_delivery()
    await queue(world, document, service)
    await service.run_next_job()
    request = world.sender.requests[0]
    assert request.headers["webhook-signature"] == " ".join(
        expected_signature(secret, request) for secret in (new, old)
    )
    # After the grace period only the new one signs.
    world.clock.advance(timedelta(hours=25))
    await queue(world, document, service)
    await service.run_next_job()
    request = world.sender.requests[1]
    assert request.headers["webhook-signature"] == expected_signature(new, request)


@pytest.mark.parametrize("status", [500, 503, 408, 425, 429, "unreachable"])
async def test_temporary_failures_are_repeated_with_a_growing_delay(
    world: World, status: int | str
) -> None:
    world.sender.answers = [status, status, 204]
    user = await world.user()
    document = await seed(world, user)
    webhook, _ = await hook(world, user)
    service = world.webhook_delivery()
    await queue(world, document, service)

    await service.run_next_job()
    assert not await service.run_next_job()  # waits for the retry
    world.clock.advance(timedelta(seconds=30))
    await service.run_next_job()
    world.clock.advance(timedelta(seconds=59))
    assert not await service.run_next_job()
    world.clock.advance(timedelta(seconds=1))  # 60 s after the second failure
    await service.run_next_job()

    rows = await log(world, webhook)
    assert [(r.attempt, r.outcome) for r in rows] == [
        (1, DeliveryOutcome.RETRYING),
        (2, DeliveryOutcome.RETRYING),
        (3, DeliveryOutcome.DELIVERED),
    ]
    assert rows[0].next_attempt_at == NOW + timedelta(seconds=30)
    assert rows[1].next_attempt_at == NOW + timedelta(seconds=30 + 60)
    assert rows[0].status_code == (None if status == "unreachable" else status)
    assert (rows[0].error is not None) == (status == "unreachable")


async def test_it_gives_up_after_the_last_attempt(world: World) -> None:
    world.sender.answers = [500]
    user = await world.user()
    document = await seed(world, user)
    webhook, _ = await hook(world, user)
    service = world.webhook_delivery(replace(builders.WEBHOOKS, max_attempts=3))
    await queue(world, document, service)
    for _ in range(3):
        await service.run_next_job()
        world.clock.advance(timedelta(hours=2))
    assert not await service.run_next_job()
    assert [r.outcome for r in await log(world, webhook)] == [
        DeliveryOutcome.RETRYING,
        DeliveryOutcome.RETRYING,
        DeliveryOutcome.GAVE_UP,
    ]
    assert len(world.sender.requests) == 3
    assert (await world.webhooks.get(user.id, webhook.id)).failed_streak == 1


@pytest.mark.parametrize("status", [301, 302, 400, 401, 404, 410, 422])
async def test_redirects_and_client_errors_are_final(world: World, status: int) -> None:
    world.sender.answers = [status]
    user = await world.user()
    document = await seed(world, user)
    webhook, _ = await hook(world, user)
    service = world.webhook_delivery()
    await queue(world, document, service)
    await service.run_next_job()
    world.clock.advance(timedelta(days=1))
    assert not await service.run_next_job()
    (row,) = await log(world, webhook)
    assert (row.outcome, row.status_code) == (DeliveryOutcome.GAVE_UP, status)
    assert len(world.sender.requests) == 1


async def test_a_webhook_is_switched_off_after_repeated_failures_and_success_resets(
    world: World,
) -> None:
    user = await world.user()
    document = await seed(world, user)
    webhook, _ = await hook(world, user)
    service = world.webhook_delivery(replace(builders.WEBHOOKS, disable_after=3))

    async def deliver(answer: int) -> None:
        world.sender.answers = [answer]
        await service.on_event(lane_changed(document))
        await service.run_next_job()

    await deliver(404)
    await deliver(404)
    await deliver(200)  # resets the count
    assert (await world.webhooks.get(user.id, webhook.id)).failed_streak == 0
    await deliver(404)
    await deliver(404)
    assert (await world.webhooks.get(user.id, webhook.id)).active
    await deliver(404)
    off = await world.webhooks.get(user.id, webhook.id)
    assert (off.active, off.disabled_reason, off.failed_streak) == (False, DISABLED_FAILING, 3)
    # Switched off: nothing is queued any more.
    before = len(deliveries(world))
    await service.on_event(lane_changed(document))
    assert len(deliveries(world)) == before


async def test_own_headers_go_with_the_request_and_an_unsigned_one_has_no_signature(
    world: World,
) -> None:
    user = await world.user()
    document = await seed(world, user)
    created = await world.webhooks.create(
        user.id,
        name="HA",
        url=URL,
        event_types=["*"],
        signed=False,
        headers={"Authorization": "Bearer t0ken", "User-Agent": "Mine"},
    )
    service = world.webhook_delivery()
    await queue(world, document, service)
    await service.run_next_job()
    request = world.sender.requests[0]
    assert request.headers["Authorization"] == "Bearer t0ken"
    assert request.headers["User-Agent"] == "Mine"
    assert request.headers["Content-Type"] == "application/json"
    assert {"webhook-id", "webhook-timestamp"} <= set(request.headers)
    assert "webhook-signature" not in request.headers
    assert [row.outcome for row in await log(world, created.webhook)] == [DeliveryOutcome.DELIVERED]


async def test_header_values_that_cannot_be_decrypted_give_up_without_sending(
    world: World,
) -> None:
    user = await world.user()
    document = await seed(world, user)
    created = await world.webhooks.create(
        user.id, name="HA", url=URL, event_types=["*"], headers={"X-Token": "a"}
    )
    async with world.uow() as uow:
        webhook = await uow.webhooks.get(created.webhook.id)
        webhook.encrypted_headers = b"garbage"
        await uow.webhooks.update(webhook)
        await uow.commit()
    service = world.webhook_delivery()
    await queue(world, document, service)
    await service.run_next_job()
    assert world.sender.requests == []
    (row,) = await log(world, created.webhook)
    assert row.outcome is DeliveryOutcome.GAVE_UP and "header values" in (row.error or "")


async def described(world: World, owner: User) -> Document:
    """A green document of the owner with a contact, a type and an amount."""
    contact = Contact.create(name="Stadtwerke", now=NOW)
    kind = DocumentType.create(name="Rechnung", now=NOW)
    amount = FieldDefinition.create(
        name="Betrag", data_type=FieldType.AMOUNT, document_type_ids=[kind.id], now=NOW
    )
    document = builders.processed(owner, await world.personal_space(owner))
    document.title = "Strom März"
    document.contact_id, document.document_type_id = contact.id, kind.id
    document.fields = {amount.id: Money(Decimal("120.50"), "EUR")}
    async with world.uow() as uow:
        await uow.contacts.add(contact)
        await uow.document_types.add(kind)
        await uow.fields.add(amount)
        await uow.documents.add(document)
        await uow.commit()
    return document


async def test_a_full_body_carries_the_document_as_it_is(world: World) -> None:
    user = await world.user()
    document = await described(world, user)
    await world.webhooks.create(
        user.id, name="HA", url=URL, event_types=["*"], signed=False, body=BodyFormat.FULL
    )
    service = world.webhook_delivery()
    event = await queue(world, document, service)
    await service.run_next_job()
    body = json.loads(world.sender.requests[0].body)
    assert body["id"] == str(event.id) and body["document_id"] == str(document.id)
    shown = body["document"]
    assert shown["title"] == "Strom März"
    assert shown["contact"]["name"] == "Stadtwerke"
    assert shown["document_type"]["name"] == "Rechnung"
    assert shown["fields"] == {"betrag": {"amount": "120.50", "currency": "EUR"}}
    assert shown["lane"] == "green"
    assert shown["link"] == f"https://lekto.example.org/ui/documents/{document.id}"
    EventBody.model_validate(body)  # as the contract describes it


async def test_a_template_body_is_what_the_template_makes(world: World) -> None:
    user = await world.user()
    document = await described(world, user)
    template = (
        '{"message": {{ title | json }}, "amount": {{ field.betrag.amount | json }}, '
        '"from": {{ contact | json }}, "event": {{ event.type | json }}, '
        '"topic": {{ topic | default: nil | json }}, "open": {{ link | json }}}'
    )
    await world.webhooks.create(
        user.id,
        name="HA",
        url=URL,
        event_types=["*"],
        signed=False,
        body=BodyFormat.TEMPLATE,
        body_template=template,
    )
    service = world.webhook_delivery()
    await queue(world, document, service)
    await service.run_next_job()
    assert json.loads(world.sender.requests[0].body) == {
        "message": "Strom März",
        "amount": "120.50",
        "from": "Stadtwerke",
        "event": "document.lane_changed",
        "topic": None,
        "open": f"https://lekto.example.org/ui/documents/{document.id}",
    }


@pytest.mark.parametrize(
    ("template", "error"),
    [
        ('{"t": {{ topic | json }}}', "the template writes a missing value: topic"),
        ('{"t": {{ title }}}', "the template does not make JSON"),
    ],
)
async def test_a_template_that_makes_no_json_gives_up_without_sending(
    world: World, template: str, error: str
) -> None:
    user = await world.user()
    document = await described(world, user)
    created = await world.webhooks.create(
        user.id,
        name="HA",
        url=URL,
        event_types=["*"],
        body=BodyFormat.TEMPLATE,
        body_template=template,
    )
    service = world.webhook_delivery()
    await queue(world, document, service)
    await service.run_next_job()
    assert world.sender.requests == []
    (row,) = await log(world, created.webhook)
    assert row.outcome is DeliveryOutcome.GAVE_UP
    assert (row.error or "").startswith(error)


async def test_a_rule_s_request_names_the_rule(world: World) -> None:
    user = await world.user()
    document = await seed(world, user)
    thin = (await world.webhooks.create(user.id, name="thin", url=URL, event_types=[])).webhook
    templated = (
        await world.webhooks.create(
            user.id,
            name="template",
            url=URL,
            event_types=[],
            body=BodyFormat.TEMPLATE,
            body_template='{"by": {{ rule.name | json }}, "type": {{ event.type | json }}}',
        )
    ).webhook
    rule: JsonObject = {"id": "r1", "name": "Notify"}
    async with world.uow() as uow:
        for webhook in (thin, templated):
            await queue_rule_send(
                uow, webhook_id=webhook.id, document_id=document.id, rule=rule, now=NOW
            )
        await uow.commit()
    service = world.webhook_delivery()
    await run_all(service)
    bodies = sorted(
        (json.loads(request.body) for request in world.sender.requests), key=lambda body: len(body)
    )
    assert bodies[0] == {"by": "Notify", "type": RULE_SEND}
    assert bodies[1]["rule"] == rule and bodies[1]["type"] == RULE_SEND
    assert bodies[1]["document_id"] == str(document.id)


# --- rights at the time of the attempt ----------------------------------------------------------


async def test_a_lost_right_drops_the_delivery_without_sending(world: World) -> None:
    owner, friend = await world.user(), await world.user()
    shared = builders.space(owner, "shared")
    shared.set_member(friend.id, SpaceRole.READ)
    async with world.uow() as uow:
        await uow.spaces.add(shared)
        await uow.commit()
    document = await seed(world, owner, shared)
    webhook, _ = await hook(world, friend)
    service = world.webhook_delivery()
    await queue(world, document, service)
    await world.spaces.remove_member(owner.id, shared.id, friend.id)

    assert await service.run_next_job()
    assert world.sender.requests == []
    (row,) = await log(world, webhook)
    assert (row.outcome, row.status_code) == (DeliveryOutcome.DROPPED, None)
    assert row.error == "the document is not available to the owner"
    assert (await world.webhooks.get(friend.id, webhook.id)).failed_streak == 0
    assert not await service.run_next_job()


async def test_a_switched_off_webhook_or_deactivated_owner_or_vanished_document_is_dropped(
    world: World,
) -> None:
    admin = await world.user(role=Role.ADMIN)
    a, b, c = await world.user(), await world.user(), await world.user()
    service = world.webhook_delivery()
    docs, hooks = [], []
    for owner in (a, b, c):
        document = await seed(world, owner)
        docs.append(document)
        hooks.append((await hook(world, owner))[0])
        await queue(world, document, service)
    await world.webhooks.update(a.id, hooks[0].id, active=False)
    await world.users.update(admin.id, b.id, active=False)
    async with world.uow() as uow:
        await uow.documents.remove(docs[2].id)
        await uow.commit()

    assert await run_all(service) == 3
    assert world.sender.requests == []
    reasons = [(await log(world, h))[0].error for h in hooks]
    assert reasons == [
        "the webhook is switched off",
        "the owner's account is not active",
        "the document is not available to the owner",
    ]


async def test_a_deleted_webhook_ends_its_queued_deliveries(world: World) -> None:
    user = await world.user()
    document = await seed(world, user)
    webhook, _ = await hook(world, user)
    service = world.webhook_delivery()
    await queue(world, document, service)
    await world.webhooks.delete(user.id, webhook.id)
    assert await service.run_next_job()
    assert world.sender.requests == []
    assert [j.status for j in deliveries(world)] == [JobStatus.DONE]


async def test_a_deleted_document_is_delivered_without_checking_the_rights_again(
    world: World,
) -> None:
    user = await world.user()
    webhook, _ = await hook(world, user, "document.deleted")
    service = world.webhook_delivery()
    document_id = DocumentId(new_id())
    await service.on_event(
        DocumentDeleted(occurred_at=NOW, document_id=document_id, readers=(user.id,))
    )
    await service.run_next_job()
    (row,) = await log(world, webhook)
    assert row.outcome is DeliveryOutcome.DELIVERED and row.document_id == document_id


async def test_an_unusable_secret_gives_up(world: World) -> None:
    user = await world.user()
    document = await seed(world, user)
    webhook, _ = await hook(world, user)
    async with world.uow() as uow:
        stored = await uow.webhooks.get(webhook.id)
        stored.encrypted_secret = b"garbage" * 8
        await uow.webhooks.update(stored)
        await uow.commit()
    service = world.webhook_delivery()
    await queue(world, document, service)
    await service.run_next_job()
    (row,) = await log(world, webhook)
    assert row.outcome is DeliveryOutcome.GAVE_UP and "secret" in (row.error or "")
    assert world.sender.requests == []


# --- test request -------------------------------------------------------------------------------


async def test_the_test_request_is_sent_once_and_logged(world: World) -> None:
    user = await world.user()
    webhook, secret = await hook(world, user, "document.filed")
    service = world.webhook_delivery()
    row = await service.send_test(user.id, webhook.id)
    (request,) = world.sender.requests
    assert json.loads(request.body)["type"] == TEST_EVENT
    assert json.loads(request.body)["document_id"] is None
    assert request.headers["webhook-signature"] == expected_signature(secret, request)
    assert (row.outcome, row.event_type, row.document_id) == (
        DeliveryOutcome.DELIVERED,
        TEST_EVENT,
        None,
    )
    assert await log(world, webhook) == [row]

    world.sender.answers = [500]
    failed = await service.send_test(user.id, webhook.id)
    assert (failed.outcome, failed.status_code, failed.next_attempt_at) == (
        DeliveryOutcome.GAVE_UP,
        500,
        None,
    )
    assert len(world.sender.requests) == 2  # no repetition
    assert (await world.webhooks.get(user.id, webhook.id)).failed_streak == 0


async def test_a_test_request_with_an_unusable_secret_is_logged_as_given_up(world: World) -> None:
    """2-04 (M13): like a delivery, not a 500."""
    user = await world.user()
    webhook, _ = await hook(world, user)
    async with world.uow() as uow:
        stored = await uow.webhooks.get(webhook.id)
        stored.encrypted_secret = b"garbage" * 8
        await uow.webhooks.update(stored)
        await uow.commit()
    row = await world.webhook_delivery().send_test(user.id, webhook.id)
    assert row.outcome is DeliveryOutcome.GAVE_UP and "secret" in (row.error or "")
    assert world.sender.requests == []
    assert await log(world, webhook) == [row]


async def test_the_owner_and_admins_test_a_webhook(world: World) -> None:
    admin, owner, other = await world.user(role=Role.ADMIN), await world.user(), await world.user()
    webhook, _ = await hook(world, owner)
    service = world.webhook_delivery()
    with pytest.raises(NotFoundError):
        await service.send_test(other.id, webhook.id)
    with pytest.raises(NotFoundError):
        await service.send_test(owner.id, WebhookId(new_id()))
    assert world.sender.requests == []
    await service.send_test(admin.id, webhook.id)
    assert len(world.sender.requests) == 1


async def test_test_requests_are_limited_per_user_and_window(world: World) -> None:
    owner, admin = await world.user(), await world.user(role=Role.ADMIN)
    webhook, _ = await hook(world, owner)
    policy = replace(builders.WEBHOOKS, test_requests=2, test_window=timedelta(minutes=1))
    service = world.webhook_delivery(policy)
    await service.send_test(owner.id, webhook.id)
    world.clock.advance(timedelta(seconds=20))
    await service.send_test(owner.id, webhook.id)
    with pytest.raises(TooManyAttemptsError) as refused:
        await service.send_test(owner.id, webhook.id)
    assert refused.value.retry_after == timedelta(seconds=40)
    assert len(world.sender.requests) == 2
    # Another user has a window of their own; an unknown webhook does not count.
    await service.send_test(admin.id, webhook.id)
    with pytest.raises(NotFoundError):
        await service.send_test(owner.id, WebhookId(new_id()))
    world.clock.advance(timedelta(seconds=40))
    await service.send_test(owner.id, webhook.id)
    assert len(world.sender.requests) == 4
