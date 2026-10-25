"""Delivering events to webhooks.

Two steps, both idempotent and safe to repeat (events arrive at least once):

1. **Fan-out** (`on_event`, the event bus subscriber `webhooks.fanout`): for an event, queue one
   `webhooks.deliver` job for each active webhook that wants its type and whose owner has the
   document within their reach (`permissions.in_reach`: an admin's webhooks report what the
   admin reaches as a user, not every document; Tobi, 08.10.2026). The job's dedup key is
   `<webhook>:<event>`, so a repeated event adds no second
   job while the first is queued or running. `document.deleted` uses the readers stored in the
   event (the document is gone); `document.filed` is skipped while the document has no lane
   (the pipeline's last `filed` comes after the lane is set).
2. **Delivery** (`run_next_job`): each attempt checks the rights again against the current
   state, so a user who lost access in the meantime gets nothing (`dropped`). Then it makes the
   body (thin, full with the document as it is now, or the webhook's template rendered), signs
   it with the webhook's secret(s) if it has any, sends it with the webhook's own headers,
   writes one delivery log row and settles the job: delivered, repeated later, or given up. A
   template that cannot be rendered into JSON gives up at once (repeating would not help).

   | answer                                        | result                               |
   | --------------------------------------------- | ------------------------------------ |
   | 2xx                                           | delivered                            |
   | no answer, 5xx, 408, 425, 429                 | repeated, up to `max_attempts`       |
   | anything else (3xx, other 4xx)                | given up at once                     |

   Repetitions wait `retry_delay`, doubling, at most `max_retry_delay`. After `disable_after`
   given-up deliveries in a row the webhook is switched off (`disabled_reason` `failing`).

A task's request (`domain.tasks`, payload with `task_id`) goes the same way, with these
differences: its body was made when the task was sent and waits encrypted with the task's token
(`TaskDesk`); it carries the headers `lekto-task-id`, `lekto-callback`, `lekto-task-token` and
`lekto-deadline`; it is repeated until the task's deadline, however often; and a request that
does not arrive fails the task (its node goes on as without an answer) instead of counting
towards switching the webhook off (a webhook that takes tasks is never switched off, Tobi,
25.10.2026). Once delivered, the request and its token are forgotten.

Secrets are decrypted only for signing; neither they nor the receiver's answer are logged or
stored.
"""

import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import (
    ConcurrencyError,
    MissingValueError,
    NotFoundError,
    TooManyAttemptsError,
    ValidationError,
)
from lekto.core.domain.events import DocumentDeleted, DocumentEvent, DocumentFiled, DomainEvent
from lekto.core.domain.ids import DocumentId, EventId, TaskId, UserId, WebhookId, new_id
from lekto.core.domain.jobs import Job, RetryPolicy
from lekto.core.domain.json_value import JsonObject, as_object
from lekto.core.domain.permissions import in_reach
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.tasks import Task, TaskStatus
from lekto.core.domain.templates import RULE
from lekto.core.domain.users import User
from lekto.core.domain.webhooks import (
    RULE_SEND,
    TEST_EVENT,
    BodyFormat,
    DeliveryOutcome,
    Webhook,
    WebhookDelivery,
    event_body,
    headers_from_bytes,
    rendered_body,
    signed_headers,
)
from lekto.core.ports.clock import Clock
from lekto.core.ports.identity import DecryptionError, SecretCipher
from lekto.core.ports.templates import TemplateRenderer
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.ports.webhook_sender import WebhookRequest, WebhookResponse, WebhookSender
from lekto.core.services._access import load_actor
from lekto.core.services._jobs import JobRunner, lost
from lekto.core.services._templates import document_json, event_values, webhook_values
from lekto.core.services.tasks.settling import end_task
from lekto.core.services.webhooks.management import (
    headers_context,
    manageable_webhook,
    secret_context,
)
from lekto.core.services.webhooks.policy import WebhookPolicy

log = logging.getLogger(__name__)

SUBSCRIBER = "webhooks.fanout"
DELIVER_JOB = "webhooks.deliver"
"""Payload: `webhook_id`, `event_id`, `type`, `occurred_at` (ISO 8601) and `document_id`; a
rule's request (`RULE_SEND`) also `rule` (`id`, `name`), a task's request `task_id`."""
TASK_RETRY = RetryPolicy(
    max_attempts=1 << 30, delay=timedelta(seconds=15), max_delay=timedelta(minutes=5)
)
"""How a task's request is repeated: until its deadline, waiting 15 seconds, doubling, at most
5 minutes."""

_RETRY_STATUS = frozenset({408, 425, 429})
_RESULT_ROUNDS = 3  # tries to write the result when the webhook is changed at the same time
ATTEMPT_LEASE_MARGIN = timedelta(seconds=60)
"""Time a delivery job may take beyond the timeout of its attempt: one request needs no files,
only writing its outcome (less than `WORK_LEASE_MARGIN` of the jobs that move files)."""


class WebhookDeliveryService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        cipher: SecretCipher,
        sender: WebhookSender,
        policy: WebhookPolicy,
        templates: TemplateRenderer,
        *,
        link_base: str | None = None,
    ) -> None:
        """`templates` renders the bodies of webhooks with a template; `link_base`
        (`LEKTO_PUBLIC_URL`) makes the link to a document in the web UI."""
        self._uow = uow
        self._clock = clock
        self._cipher = cipher
        self._sender = sender
        self._policy = policy
        self._templates = templates
        self._link_base = link_base
        self._retry = RetryPolicy(
            max_attempts=self._policy.max_attempts,
            delay=self._policy.retry_delay,
            max_delay=self._policy.max_retry_delay,
        )
        self._jobs = JobRunner(uow, clock)
        # When each user sent test requests, for the limit per window (this process only; a
        # second API instance would count on its own).
        self._test_requests: dict[UserId, deque[datetime]] = {}

    # --- fan-out --------------------------------------------------------------------------------

    async def on_event(self, event: DomainEvent) -> None:
        """The event bus subscriber: queue a delivery per matching webhook."""
        if not isinstance(event, DocumentEvent):
            return
        async with self._uow() as uow:
            webhooks = await uow.webhooks.list_active_for(event.type)
            if not webhooks:
                return
            owners = await _owners_who_may_read(uow, event, {w.owner_id for w in webhooks})
            queued = 0
            for webhook in webhooks:
                if webhook.owner_id not in owners:
                    continue
                payload: JsonObject = {
                    "webhook_id": str(webhook.id),
                    "event_id": str(event.id),
                    "type": event.type,
                    "occurred_at": event.occurred_at.isoformat(),
                    "document_id": str(event.document_id),
                }
                job = await uow.jobs.enqueue(
                    DELIVER_JOB,
                    payload,
                    run_at=self._clock.now(),
                    dedup_key=f"{webhook.id}:{event.id}",
                )
                queued += job is not None
            await uow.commit()
        if queued:
            log.debug("webhook deliveries queued", extra={"event": event.type, "count": queued})

    # --- delivery -------------------------------------------------------------------------------

    async def run_next_job(self) -> bool:
        """Claim and run a due delivery. Returns False if none was due."""
        lease = self._policy.timeout + ATTEMPT_LEASE_MARGIN
        return await self._jobs.run_next([DELIVER_JOB], lease, self._run_claimed)

    async def send_test(self, actor: UserId, id: WebhookId) -> WebhookDelivery:
        """Owner or admin: send a `webhook.test` request now, once, and return the log row. Works
        for a switched-off webhook too; does not count towards switching it off. A test request
        goes to any address at once, so each user gets `policy.test_requests` per
        `policy.test_window`; beyond that TooManyAttemptsError says when the next one may go."""
        async with self._uow() as uow:
            webhook = await manageable_webhook(uow, await load_actor(uow, actor), id)
            now = self._clock.now()
            self._count_test_request(actor, now)
            event_id = EventId(new_id())
            body = await self._body(uow, webhook, event_id, TEST_EVENT, now, None)
        try:
            secrets, own = self._decrypt(webhook, now)
        except (DecryptionError, ValueError):
            response = _unusable_secret(id)
        else:
            response = (
                body
                if isinstance(body, WebhookResponse)
                else await self._send(webhook, secrets, own, event_id, body)
            )
        outcome = DeliveryOutcome.DELIVERED if _is_success(response) else DeliveryOutcome.GAVE_UP
        delivery = _row(webhook, event_id, TEST_EVENT, None, 1, now, response, outcome)
        async with self._uow() as uow:
            await uow.webhooks.add_delivery(delivery)
            await uow.commit()
        return delivery

    def _count_test_request(self, actor: UserId, now: datetime) -> None:
        window, limit = self._policy.test_window, self._policy.test_requests
        sent = self._test_requests.setdefault(actor, deque())
        while sent and sent[0] <= now - window:
            sent.popleft()
        if len(sent) >= limit:
            raise TooManyAttemptsError(sent[0] + window - now)
        sent.append(now)

    async def _run_claimed(self, job: Job) -> None:
        try:
            webhook_id = WebhookId(UUID(str(job.payload["webhook_id"])))
            event_id = EventId(UUID(str(job.payload["event_id"])))
            event_type = str(job.payload["type"])
            occurred_at = datetime.fromisoformat(str(job.payload["occurred_at"]))
            raw_document = job.payload.get("document_id")
            document_id = None if raw_document is None else DocumentId(UUID(str(raw_document)))
            rule = as_object(job.payload.get("rule"))
            raw_task = job.payload.get("task_id")
            task_id = None if raw_task is None else TaskId(UUID(str(raw_task)))
        except (KeyError, TypeError, ValueError) as error:
            await self._jobs.invalid(job, error)
            return
        try:
            if task_id is not None:
                await self._attempt_task(job, webhook_id, task_id, event_type, document_id)
            else:
                await self._attempt(
                    job, webhook_id, event_id, event_type, occurred_at, document_id, rule
                )
        except ConcurrencyError:
            lost(job)
        except Exception as error:
            log.warning("webhook job failed", extra={"job_id": str(job.id)}, exc_info=True)
            reason = f"{type(error).__name__}: {error}"
            await self._jobs.again(job, reason, self._retry.next_run(job.tries, self._clock.now()))

    async def _attempt(
        self,
        job: Job,
        webhook_id: WebhookId,
        event_id: EventId,
        event_type: str,
        occurred_at: datetime,
        document_id: DocumentId | None,
        rule: JsonObject | None = None,
    ) -> None:
        now = self._clock.now()
        async with self._uow() as uow:
            webhook = await uow.webhooks.find(webhook_id)
            if webhook is None:
                # Deleted since: nothing to log it in.
                await uow.jobs.complete(job)
                await uow.commit()
                return
            reason = await _reason_to_drop(uow, webhook, event_type, document_id)
            body = (
                None
                if reason is not None
                else await self._body(
                    uow, webhook, event_id, event_type, occurred_at, document_id, rule
                )
            )
        attempt = job.tries
        if reason is not None:
            response = WebhookResponse(status_code=None, duration_ms=0, error=reason)
            await self._settle_attempt(
                job,
                webhook_id,
                event_id,
                event_type,
                document_id,
                attempt,
                now,
                response,
                DeliveryOutcome.DROPPED,
            )
            return
        assert body is not None
        try:
            secrets, own = self._decrypt(webhook, now)
        except (DecryptionError, ValueError):
            response = _unusable_secret(webhook_id)
            outcome = DeliveryOutcome.GAVE_UP
        else:
            if isinstance(body, WebhookResponse):
                response, outcome = body, DeliveryOutcome.GAVE_UP
            else:
                response = await self._send(webhook, secrets, own, event_id, body)
                outcome = self._outcome(response, attempt)
        await self._settle_attempt(
            job, webhook_id, event_id, event_type, document_id, attempt, now, response, outcome
        )

    async def _attempt_task(
        self,
        job: Job,
        webhook_id: WebhookId,
        task_id: TaskId,
        event_type: str,
        document_id: DocumentId | None,
    ) -> None:
        """One attempt of a task's request: its webhook's headers, the task's and the body
        made when it was sent. A task that ended or was delivered meanwhile needs nothing."""
        now = self._clock.now()
        async with self._uow() as uow:
            task = await uow.tasks.find(task_id)
            webhook = await uow.webhooks.find(webhook_id)
            reason = (
                None
                if webhook is None or task is None
                else await _reason_to_drop(uow, webhook, event_type, document_id)
            )
        if task is None or task.status is not TaskStatus.OPEN or task.encrypted_request is None:
            await self._jobs.end(job)
            return
        attempt = job.tries
        if webhook is None:
            response = WebhookResponse(
                status_code=None, duration_ms=0, error="the webhook was deleted"
            )
            outcome = DeliveryOutcome.GAVE_UP
        elif reason is not None:
            response = WebhookResponse(status_code=None, duration_ms=0, error=reason)
            outcome = DeliveryOutcome.DROPPED
        else:
            try:
                secrets, own = self._decrypt(webhook, now)
                request = TaskRequestText.decrypt(self._cipher, task)
            except (DecryptionError, ValueError):
                response, outcome = _unusable_secret(webhook_id), DeliveryOutcome.GAVE_UP
            else:
                response = await self._send(
                    webhook,
                    secrets,
                    {**own, **request.headers(task)},
                    EventId(task.id),
                    request.body,
                )
                outcome = self._task_outcome(response, attempt, task)
        await self._settle_task_attempt(job, task, event_type, attempt, now, response, outcome)

    def _task_outcome(self, response: WebhookResponse, attempt: int, task: Task) -> DeliveryOutcome:
        if _is_success(response):
            return DeliveryOutcome.DELIVERED
        next_attempt = TASK_RETRY.next_run(attempt, self._clock.now())
        if (
            _is_temporary(response)
            and next_attempt is not None
            and task.deadline is not None
            and next_attempt < task.deadline
        ):
            return DeliveryOutcome.RETRYING
        return DeliveryOutcome.GAVE_UP

    async def _settle_task_attempt(
        self,
        job: Job,
        task: Task,
        event_type: str,
        attempt: int,
        started: datetime,
        response: WebhookResponse,
        outcome: DeliveryOutcome,
    ) -> None:
        """One transaction: log row (if the webhook is still there), the task (delivered, or
        failed: its node goes on as without an answer), the job. If the task changed at the
        same moment (answered at once), read it again."""
        for round_ in range(_RESULT_ROUNDS):
            now = self._clock.now()
            next_attempt = (
                TASK_RETRY.next_run(attempt, now) if outcome is DeliveryOutcome.RETRYING else None
            )
            try:
                async with self._uow() as uow:
                    webhook = await uow.webhooks.find(task.webhook_id)
                    if webhook is not None:
                        await uow.webhooks.add_delivery(
                            _row(
                                webhook,
                                EventId(task.id),
                                event_type,
                                task.document_id,
                                attempt,
                                started,
                                response,
                                outcome,
                                next_attempt,
                            )
                        )
                    current = await uow.tasks.find(task.id)
                    if current is not None and current.status is TaskStatus.OPEN:
                        if outcome is DeliveryOutcome.DELIVERED:
                            current.delivered()
                            await uow.tasks.update(current)
                        elif next_attempt is None:
                            name = webhook.name if webhook is not None else str(task.webhook_id)
                            error = response.error or _status_text(response)
                            current.fail(
                                because(ReasonCode.TASK_UNDELIVERED, webhook=name, error=error),
                                now,
                            )
                            await end_task(uow, current, now)
                    if next_attempt is not None:
                        await uow.jobs.reschedule(
                            job, run_at=next_attempt, error=response.error or _status_text(response)
                        )
                    else:
                        await uow.jobs.complete(job)
                    await uow.commit()
            except ConcurrencyError:
                if round_ + 1 == _RESULT_ROUNDS:
                    raise
                continue
            return

    def _outcome(self, response: WebhookResponse, attempt: int) -> DeliveryOutcome:
        if _is_success(response):
            return DeliveryOutcome.DELIVERED
        if _is_temporary(response) and attempt < self._policy.max_attempts:
            return DeliveryOutcome.RETRYING
        return DeliveryOutcome.GAVE_UP

    async def _body(
        self,
        uow: UnitOfWork,
        webhook: Webhook,
        event_id: EventId,
        event_type: str,
        occurred_at: datetime,
        document_id: DocumentId | None,
        rule: JsonObject | None = None,
    ) -> bytes | WebhookResponse:
        """The body of the request, made with the document as it is now (and `rule`, the rule
        that sends it); for a template that cannot be rendered into JSON the answer that gives
        up (without sending), naming why."""
        document = None
        if webhook.body is not BodyFormat.THIN and document_id is not None:
            document = await uow.documents.find(document_id)
        match webhook.body:
            case BodyFormat.THIN | BodyFormat.FULL:
                data = (
                    None
                    if document is None
                    else await document_json(uow, document, self._link_base)
                )
                return event_body(
                    event_id=event_id,
                    type=event_type,
                    occurred_at=occurred_at,
                    document_id=document_id,
                    document=data,
                    full=webhook.body is BodyFormat.FULL,
                    rule=rule,
                )
        assert webhook.body_template is not None
        values = event_values(event_id, event_type, occurred_at)
        if document is not None:
            values |= await webhook_values(uow, document, self._link_base)
        elif document_id is not None:
            values["document_id"] = str(document_id)
        if rule is not None:
            values[RULE] = {key: str(value) for key, value in rule.items() if value is not None}
        try:
            return rendered_body(self._templates.render(webhook.body_template, values))
        except MissingValueError as missing:
            error = f"the template writes a missing value: {missing.path}"
        except (ValidationError, ValueError) as invalid:
            error = str(invalid)
        return WebhookResponse(status_code=None, duration_ms=0, error=error)

    async def _send(
        self,
        webhook: Webhook,
        secrets: list[str],
        own: dict[str, str],
        event_id: EventId,
        body: bytes,
    ) -> WebhookResponse:
        """`own`: the webhook's own headers; Lekto's (content type, id, timestamp, signature)
        cannot be among them (`validate_header_names`)."""
        headers = {
            **own,
            "Content-Type": "application/json",
            **signed_headers(secrets, str(event_id), int(self._clock.now().timestamp()), body),
        }
        return await self._sender.send(
            WebhookRequest(
                url=webhook.url, headers=headers, body=body, timeout=self._policy.timeout
            )
        )

    def _decrypt(self, webhook: Webhook, now: datetime) -> tuple[list[str], dict[str, str]]:
        """The secrets that sign now, and the webhook's own headers with their values."""
        context = secret_context(webhook.id)
        secrets = [
            self._cipher.decrypt(encrypted, context=context).decode("ascii")
            for encrypted in webhook.encrypted_secrets(now)
        ]
        own: dict[str, str] = {}
        if webhook.encrypted_headers is not None:
            values = headers_from_bytes(
                self._cipher.decrypt(webhook.encrypted_headers, context=headers_context(webhook.id))
            )
            own = {name: values[name] for name in webhook.header_names}
        return secrets, own

    # --- result ---------------------------------------------------------------------------------

    async def _settle_attempt(
        self,
        job: Job,
        webhook_id: WebhookId,
        event_id: EventId,
        event_type: str,
        document_id: DocumentId | None,
        attempt: int,
        started: datetime,
        response: WebhookResponse,
        outcome: DeliveryOutcome,
    ) -> None:
        """One transaction: log row, counter of the webhook, job. If the webhook is changed at
        the same moment, read it again and retry."""
        for round_ in range(_RESULT_ROUNDS):
            now = self._clock.now()
            next_attempt = (
                self._retry.next_run(attempt, now) if outcome is DeliveryOutcome.RETRYING else None
            )
            switched_off: bool | None = None
            try:
                async with self._uow() as uow:
                    webhook = await uow.webhooks.find(webhook_id)
                    if webhook is not None:
                        delivery = _row(
                            webhook,
                            event_id,
                            event_type,
                            document_id,
                            attempt,
                            started,
                            response,
                            outcome,
                            next_attempt,
                        )
                        await uow.webhooks.add_delivery(delivery)
                        switched_off = self._count(webhook, outcome, now)
                        if switched_off is not None:
                            await uow.webhooks.update(webhook)
                    if next_attempt is not None:
                        await uow.jobs.reschedule(
                            job, run_at=next_attempt, error=response.error or _status_text(response)
                        )
                    else:
                        await uow.jobs.complete(job)
                    await uow.commit()
            except ConcurrencyError:
                if round_ + 1 == _RESULT_ROUNDS:
                    raise
                continue
            if webhook is not None and switched_off:
                log.warning(
                    "webhook switched off after repeated failures",
                    extra={"webhook_id": str(webhook_id), "owner_id": str(webhook.owner_id)},
                )
            return

    def _count(self, webhook: Webhook, outcome: DeliveryOutcome, now: datetime) -> bool | None:
        """Update the failure counter. None: nothing changed; else whether it switched the
        webhook off."""
        match outcome:
            case DeliveryOutcome.DELIVERED:
                if webhook.failed_streak == 0:
                    return None
                webhook.delivered()
                return False
            case DeliveryOutcome.GAVE_UP:
                return webhook.gave_up(disable_after=self._policy.disable_after, now=now)
            case _:
                return None


# --- a rule's request and a task's ---------------------------------------------------------------


async def queue_rule_send(
    uow: UnitOfWork,
    *,
    webhook_id: WebhookId,
    document_id: DocumentId,
    rule: JsonObject,
    now: datetime,
) -> None:
    """Queue the request a rule sends through a webhook (`rules.SendWebhook`) about a document,
    in the unit of work that stores what the rules did: it goes only if that is committed.
    `rule`: its `id` and `name`. The rights are checked again before every attempt."""
    event_id = EventId(new_id())
    payload: JsonObject = {
        "webhook_id": str(webhook_id),
        "event_id": str(event_id),
        "type": RULE_SEND,
        "occurred_at": now.isoformat(),
        "document_id": str(document_id),
        "rule": rule,
    }
    await uow.jobs.enqueue(DELIVER_JOB, payload, run_at=now, dedup_key=f"{webhook_id}:{event_id}")


async def queue_task_delivery(uow: UnitOfWork, task: Task, now: datetime) -> None:
    """Queue the delivery of a task that was just sent (`TaskDesk`), in its unit of work."""
    payload: JsonObject = {
        "webhook_id": str(task.webhook_id),
        "event_id": str(task.id),
        "type": task.kind.value,
        "occurred_at": now.isoformat(),
        "document_id": str(task.document_id),
        "task_id": str(task.id),
    }
    await uow.jobs.enqueue(DELIVER_JOB, payload, run_at=now, dedup_key=f"task:{task.id}")


@dataclass(frozen=True)
class TaskRequestText:
    """A task's request as it waits, encrypted, until it is delivered: the body, the one-time
    token, where the consumer answers and by when (the headers `lekto-*`)."""

    body: bytes
    token: str
    callback: str
    deadline: str

    def headers(self, task: Task) -> dict[str, str]:
        return {
            "lekto-task-id": str(task.id),
            "lekto-callback": self.callback,
            "lekto-task-token": self.token,
            "lekto-deadline": self.deadline,
        }

    def encrypt(self, cipher: SecretCipher, task: Task) -> bytes:
        plain = {
            "body": self.body.decode("utf-8"),
            "token": self.token,
            "callback": self.callback,
            "deadline": self.deadline,
        }
        return cipher.encrypt(json.dumps(plain).encode("utf-8"), context=_task_context(task))

    @classmethod
    def decrypt(cls, cipher: SecretCipher, task: Task) -> "TaskRequestText":
        """DecryptionError or ValueError if it cannot be read."""
        assert task.encrypted_request is not None
        data = json.loads(cipher.decrypt(task.encrypted_request, context=_task_context(task)))
        return cls(
            body=str(data["body"]).encode("utf-8"),
            token=str(data["token"]),
            callback=str(data["callback"]),
            deadline=str(data["deadline"]),
        )


def _task_context(task: Task) -> bytes:
    return f"task:{task.id}".encode()


# --- rights -------------------------------------------------------------------------------------


async def _owners_who_may_read(
    uow: UnitOfWork, event: DocumentEvent, owners: set[UserId]
) -> set[UserId]:
    """Those of `owners` who are to hear of the event."""
    if isinstance(event, DocumentDeleted):
        return owners & set(event.readers)
    document = await uow.documents.find(event.document_id)
    if document is None:
        return set()
    if isinstance(event, DocumentFiled) and document.lane is None:
        return set()
    space = await uow.spaces.get(document.space_id)
    allowed: set[UserId] = set()
    for owner in owners:
        user = await uow.users.find(owner)
        if user is not None and in_reach(user, document, space):
            allowed.add(owner)
    return allowed


DOCUMENT_UNAVAILABLE = "the document is not available to the owner"


async def _reason_to_drop(
    uow: UnitOfWork, webhook: Webhook, event_type: str, document_id: DocumentId | None
) -> str | None:
    """Why the request must not be sent now; None if it may."""
    if not webhook.active:
        return "the webhook is switched off"
    owner = await uow.users.find(webhook.owner_id)
    if owner is None or not owner.active:
        return "the owner's account is not active"
    if event_type == DocumentDeleted.type or document_id is None:
        return None  # the readers were fixed with the event
    document = await uow.documents.find(document_id)
    if document is None:
        return DOCUMENT_UNAVAILABLE
    if not await _may_read(uow, owner, document):
        return DOCUMENT_UNAVAILABLE  # the same words: gone and hidden must not be told apart
    return None


async def _may_read(uow: UnitOfWork, user: User, document: Document) -> bool:
    try:
        space = await uow.spaces.get(document.space_id)
    except NotFoundError:
        return False
    return in_reach(user, document, space)


# --- answers ------------------------------------------------------------------------------------


def _unusable_secret(webhook_id: WebhookId) -> WebhookResponse:
    """The answer of a request that was not sent: the webhook's secret or header values cannot
    be decrypted."""
    log.error("webhook secret unusable", extra={"webhook_id": str(webhook_id)})
    return WebhookResponse(
        status_code=None,
        duration_ms=0,
        error="the secret or the header values cannot be used (was the secret key changed?)",
    )


def _is_success(response: WebhookResponse) -> bool:
    return response.status_code is not None and 200 <= response.status_code < 300


def _is_temporary(response: WebhookResponse) -> bool:
    status = response.status_code
    return status is None or status >= 500 or status in _RETRY_STATUS


def _status_text(response: WebhookResponse) -> str:
    return f"HTTP {response.status_code}"


def _row(
    webhook: Webhook,
    event_id: EventId,
    event_type: str,
    document_id: DocumentId | None,
    attempt: int,
    started: datetime,
    response: WebhookResponse,
    outcome: DeliveryOutcome,
    next_attempt: datetime | None = None,
) -> WebhookDelivery:
    return WebhookDelivery.record(
        webhook_id=webhook.id,
        event_id=event_id,
        event_type=event_type,
        document_id=document_id,
        attempt=attempt,
        started_at=started,
        duration_ms=response.duration_ms,
        outcome=outcome,
        status_code=response.status_code,
        error=response.error,
        next_attempt_at=next_attempt,
    )
