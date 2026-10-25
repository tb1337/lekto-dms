"""Placing the tasks a node needs, in the unit of work that stores the node's run.

A task is sent at once if its webhook has room among its open tasks (`Webhook.max_open_tasks`)
and no task waits before it; otherwise it waits (`TaskStatus.QUEUED`), and its node sends it
when it runs anew because room was freed (`settling.wake_queue`). Sending it means: a one-time
token (only its hash is kept), the deadline, the request made now (thin, full or the webhook's
template, with the task's `id`, `callback`, `token` and `deadline`), kept encrypted with the
token until it is delivered, a delivery job (`webhooks.deliver`) and a job that ends the task
at its deadline. A model call's request has a fixed body (`Contract`), whatever the webhook's,
with links to the document's files (`tasks.files`).

A request that cannot be made (the template does not make JSON, `LEKTO_PUBLIC_URL` is not set)
fails the task at once, as an answer that does not come.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import MissingValueError, ValidationError
from lekto.core.domain.identity import hash_token, new_token
from lekto.core.domain.ids import EventId
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.pipeline import Node
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.tasks import TOKEN_PREFIX, Task, TaskKind, TaskStatus, TaskStep
from lekto.core.domain.templates import RULE, STEPS, TASK, TemplateValue, json_value
from lekto.core.domain.webhooks import BodyFormat, Webhook, event_body, rendered_body
from lekto.core.ports.identity import SecretCipher
from lekto.core.ports.templates import TemplateRenderer
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.services._templates import event_values
from lekto.core.services.tasks.files import file_link
from lekto.core.services.tasks.settling import end_task, wake_queue
from lekto.core.services.webhooks.delivery import TaskRequestText, queue_task_delivery

TASKS_LOCK = "tasks"
"""The name a unit of work locks while it counts a webhook's open tasks and sends one, so two
nodes never take the same room."""
EXPIRE_JOB = "tasks.expire"
"""Job kind that ends a task at its deadline if no answer came; payload: `task_id`."""
CALLBACK_PATH = "/api/v1/external/tasks/{id}/result"


def callback_url(link_base: str, task: Task) -> str:
    """Where the consumer answers the task (`LEKTO_PUBLIC_URL` and `CALLBACK_PATH`)."""
    return link_base.rstrip("/") + CALLBACK_PATH.format(id=task.id)


class Contract(Protocol):
    """A request with a fixed body, whatever the webhook's (a model call's context,
    `classification.external`)."""

    @property
    def keys(self) -> JsonObject:
        """What the node needs to read the answer (`Task.context`)."""
        ...

    def body(self, task: JsonObject, link: Callable[[str], str]) -> JsonObject:
        """The body with `task` (`id`, `kind`, `document_id`, `run`, `callback`, `token`,
        `deadline`); `link` makes the signed link to a file of the document
        (`tasks.files`)."""
        ...


@dataclass(frozen=True)
class TaskRequest:
    """What a task's request is made of, as the node that asks sees it: the document as a
    `full` body shows it (`document`) and the values a body template sees (`values`), the rule
    that asks (`id`, `name`) and what the rule's steps before brought (`steps`); or a body of
    its own (`contract`)."""

    document: JsonObject = field(default_factory=dict)
    values: Mapping[str, TemplateValue] = field(default_factory=dict)
    rule: JsonObject | None = None
    steps: JsonObject = field(default_factory=dict)
    contract: Contract | None = None


@dataclass(frozen=True)
class Ask:
    """A task a node needs: of `kind`, for `step` (a rule's), through `webhook` (its owner's
    rights), answered within `timeout` from sending, made of `request`. `task`: the task the
    node placed for it before and that still waits, if any."""

    kind: TaskKind
    step: TaskStep | None
    webhook: Webhook
    timeout: timedelta
    request: TaskRequest
    task: Task | None = None


class TaskDesk:
    def __init__(
        self, cipher: SecretCipher, templates: TemplateRenderer, *, link_base: str | None
    ) -> None:
        """`link_base`: `LEKTO_PUBLIC_URL`, where consumers answer; without it no task can be
        sent."""
        self._cipher = cipher
        self._templates = templates
        self._link_base = link_base

    async def place(
        self,
        uow: UnitOfWork,
        document: Document,
        node: Node,
        asks: Sequence[Ask],
        now: datetime,
        *,
        locked: bool = False,
    ) -> list[Task]:
        """A task for each ask in the document's current run (the one it had, or a new one),
        sent if its webhook has room and no task waits before it; in the order given. A task
        whose request cannot be made fails at once: the node reads its tasks again. Locks
        `TASKS_LOCK` (a unit of work locks one name, before its other writes), unless the
        caller did (`locked`)."""
        if not asks:
            return []
        if not locked:
            await uow.lock(TASKS_LOCK)
        placed: list[Task] = []
        for ask in asks:
            task = ask.task
            if task is None:
                task = Task.create(
                    kind=ask.kind,
                    document_id=document.id,
                    node=node,
                    run=document.processing.run,
                    webhook_id=ask.webhook.id,
                    owner_id=ask.webhook.owner_id,
                    step=ask.step,
                    timeout=ask.timeout,
                    now=now,
                )
                await uow.tasks.add(task)
            if task.status is TaskStatus.QUEUED and await _room(uow, ask.webhook):
                first = await uow.tasks.queued(ask.webhook.id, limit=1)
                if first[0].id == task.id:
                    await self._send(uow, task, ask, document, now)
                else:  # others wait longer: they go first
                    await wake_queue(uow, ask.webhook.id, now, storing=document.id)
            placed.append(task)
        return placed

    async def _send(
        self, uow: UnitOfWork, task: Task, ask: Ask, document: Document, now: datetime
    ) -> None:
        token = new_token(TOKEN_PREFIX)
        ends = now + task.timeout
        deadline = ends.strftime("%Y-%m-%dT%H:%M:%SZ")
        callback = None if self._link_base is None else callback_url(self._link_base, task)
        body = (
            "LEKTO_PUBLIC_URL is not set: the consumer would not know where to answer"
            if callback is None
            else self._body(task, ask, document, token, callback, ends, now)
        )
        if isinstance(body, str) or callback is None:
            undelivered = because(ReasonCode.TASK_UNDELIVERED, webhook=ask.webhook.name, error=body)
            task.fail(undelivered, now)
            await end_task(uow, task, now, storing=document.id)
            return
        request = TaskRequestText(body=body, token=token, callback=callback, deadline=deadline)
        contract = ask.request.contract
        task.open(
            hash_token(token),
            request.encrypt(self._cipher, task),
            now,
            context=None if contract is None else contract.keys,
        )
        await uow.tasks.update(task)
        await queue_task_delivery(uow, task, now)
        assert task.deadline is not None
        await uow.jobs.enqueue(
            EXPIRE_JOB,
            {"task_id": str(task.id)},
            run_at=task.deadline,
            dedup_key=f"{task.id}:expire",
        )

    def _body(
        self,
        task: Task,
        ask: Ask,
        document: Document,
        token: str,
        callback: str,
        ends: datetime,
        now: datetime,
    ) -> bytes | str:
        """The request's body; why not, if it cannot be made."""
        about: JsonObject = {
            "id": str(task.id),
            "callback": callback,
            "token": token,
            "deadline": ends.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        request = ask.request
        webhook = ask.webhook
        if request.contract is not None:
            assert self._link_base is not None  # there is a callback
            link_base = self._link_base
            named: JsonObject = {
                "id": about["id"],
                "kind": task.kind.value,
                "document_id": str(task.document_id),
                "run": task.run,
                "deadline": about["deadline"],
                "callback": callback,
                "token": token,
            }
            made = request.contract.body(
                named, lambda name: file_link(link_base, self._cipher, task, name, ends)
            )
            return json.dumps(made, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if webhook.body is not BodyFormat.TEMPLATE:
            return event_body(
                event_id=task.id,
                type=task.kind.value,
                occurred_at=now,
                document_id=document.id,
                document=request.document,
                full=webhook.body is BodyFormat.FULL,
                rule=request.rule,
                task=about,
                steps=request.steps,
            )
        assert webhook.body_template is not None
        values: dict[str, TemplateValue] = {
            **request.values,
            **event_values(EventId(task.id), task.kind.value, now),
            TASK: {key: str(value) for key, value in about.items()},
        }
        if request.rule is not None:
            values[RULE] = {key: str(value) for key, value in request.rule.items()}
        if (steps := json_value(request.steps)) is not None:
            values[STEPS] = steps
        try:
            return rendered_body(self._templates.render(webhook.body_template, values))
        except MissingValueError as missing:
            return f"the template writes a missing value: {missing.path}"
        except (ValidationError, ValueError) as invalid:
            return str(invalid)


async def _room(uow: UnitOfWork, webhook: Webhook) -> bool:
    """Whether the webhook has room among its open tasks."""
    return await uow.tasks.count_open(webhook.id) < webhook.max_open_tasks
