"""Tasks: a node asks a webhook and waits ("running externally"); the answer, its absence, the
room of a webhook, and the end of a run."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import pytest

from lekto.adapters.inbound.rest.schemas.outgoing import RuleAskBody
from lekto.core.domain.documents import Document
from lekto.core.domain.errors import AuthenticationError, ConflictError
from lekto.core.domain.ids import RuleId, TaskId, WebhookId, new_id
from lekto.core.domain.pipeline import Node, NodeResult, NodeStatus, Outcome
from lekto.core.domain.reasons import ReasonCode
from lekto.core.domain.tasks import MAX_ANSWER_BYTES, Task, TaskKind, TaskStatus, TaskStep
from lekto.core.domain.users import User
from lekto.core.domain.webhooks import BodyFormat, Webhook
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.ports.webhook_sender import WebhookRequest
from lekto.core.services.pipeline import PipelineService
from lekto.core.services.tasks.desk import Ask, TaskDesk, TaskRequest
from lekto.core.services.tasks.settling import Delegation
from tests import builders
from tests.unit.services.rules_support import incoming_pdf
from tests.unit.services.support import LINK_BASE, World

URL = "http://flow.lan:1880/ask"
MINUTE = timedelta(minutes=1)
STEP = TaskStep(RuleId(new_id()), 1, "Invoices", "accounting")


@dataclass
class Asking:
    """The rules node of these tests: asks `webhook` once per run and goes on with the answer,
    uncertain without one."""

    desk: TaskDesk
    webhook: WebhookId

    async def run(self, document: Document) -> "AskingResult":
        return AskingResult(self)


@dataclass(frozen=True)
class AskingResult:
    node: Asking

    async def apply(
        self, uow: UnitOfWork, document: Document, now: datetime
    ) -> NodeResult | Delegation:
        run = document.processing.run
        tasks = await uow.tasks.list_for_run(document.id, Node.APPLY_RULES, run)
        task = tasks[0] if tasks else None
        if task is None or task.status is TaskStatus.QUEUED:
            webhook = await uow.webhooks.get(self.node.webhook)
            ask = Ask(
                kind=TaskKind.ASK,
                step=STEP,
                webhook=webhook,
                timeout=5 * MINUTE,
                request=TaskRequest(
                    document={"id": str(document.id), "title": document.title},
                    values={"title": document.title},
                    rule={"id": str(STEP.rule_id), "name": STEP.rule},
                ),
                task=task,
            )
            (task,) = await self.node.desk.place(uow, document, Node.APPLY_RULES, [ask], now)
        if task.status is TaskStatus.ANSWERED:
            return NodeResult(outcome=Outcome.OK, output={"answer": task.answer})
        if task.status.settled:
            assert task.reason is not None
            return NodeResult(outcome=Outcome.UNCERTAIN, reasons=(task.reason,))
        return Delegation(task.deadline)


@dataclass
class Flow:
    """A world whose rules node asks a webhook."""

    world: World
    owner: User
    webhook: Webhook
    pipeline: PipelineService

    async def arrive(self) -> Document:
        received = await self.pipeline.receive(self.owner.id, incoming_pdf(), filename="a.pdf")
        await self.run()
        return await self.stored(received)

    async def run(self) -> None:
        """Run the due jobs: the nodes, the deliveries and the ends of tasks."""
        delivery = self.world.webhook_delivery()
        while (
            await self.pipeline.run_next_job()
            or await delivery.run_next_job()
            or await self.world.tasks.run_next_job()
        ):
            pass

    async def stored(self, document: Document) -> Document:
        async with self.world.uow() as uow:
            return await uow.documents.get(document.id)

    async def tasks(self, document: Document) -> list[Task]:
        async with self.world.uow() as uow:
            return [
                task
                for run in range(1, (await uow.documents.get(document.id)).processing.run + 1)
                for task in await uow.tasks.list_for_run(document.id, Node.APPLY_RULES, run)
            ]

    def asked(self) -> list[WebhookRequest]:
        return [request for request in self.world.sender.requests if request.url == URL]


async def flow(
    world: World,
    *,
    link_base: str | None = None,
    max_open_tasks: int = 4,
    body: BodyFormat = BodyFormat.THIN,
    body_template: str | None = None,
) -> Flow:
    owner = await world.user()
    created = await world.webhooks.create(
        owner.id,
        name="Flow",
        url=URL,
        event_types=[],
        signed=False,
        max_open_tasks=max_open_tasks,
        body=body,
        body_template=body_template,
    )
    asking = Asking(world.desk(link_base), created.webhook.id)
    pipeline = builders.skip_classification(world.pipeline({Node.APPLY_RULES: asking}))
    return Flow(world, owner, created.webhook, pipeline)


def task_of(request: WebhookRequest) -> TaskId:
    return TaskId(UUID(request.headers["lekto-task-id"]))


def token_of(request: WebhookRequest) -> str:
    return request.headers["lekto-task-token"]


def body_of(request: WebhookRequest) -> dict[str, object]:
    data = json.loads(request.body)
    assert isinstance(data, dict)
    return data


async def answer(
    f: Flow, request: WebhookRequest, data: object, *, token: str | None = None
) -> None:
    body = json.dumps(data).encode()
    task = task_of(request)
    receipt = await f.world.tasks.answer(task, token or token_of(request), body)
    assert receipt.problem is None


async def test_the_node_waits_running_externally_until_the_answer_comes(world: World) -> None:
    f = await flow(world)
    document = await f.arrive()
    state = document.processing.nodes[Node.APPLY_RULES]
    assert state.status is NodeStatus.DELEGATED
    assert state.deadline == builders.NOW + 5 * MINUTE
    assert "document.node_delegated" in world.event_types()
    (request,) = f.asked()
    RuleAskBody.model_validate(body_of(request))  # as the contract describes it
    task = body_of(request)["task"]
    assert isinstance(task, dict)
    assert request.headers["lekto-task-id"] == task["id"]
    assert request.headers["lekto-callback"] == (
        f"{LINK_BASE}/api/v1/external/tasks/{task['id']}/result"
    )
    assert request.headers["lekto-deadline"] == task["deadline"] == "2026-10-06T12:05:00Z"
    assert token_of(request) == task["token"] and str(task["token"]).startswith("lkt_")
    assert "webhook-signature" not in request.headers
    (stored,) = await f.tasks(document)
    assert stored.encrypted_request is None  # delivered: the token is forgotten
    assert stored.token_hash is not None and task["token"] not in stored.token_hash

    await answer(f, request, {"status": "ok", "producer": "flow 1", "answer": {"paid": True}})
    await f.run()
    document = await f.stored(document)
    assert document.processing.nodes[Node.APPLY_RULES].outcome is Outcome.OK
    assert document.lane is not None
    (stored,) = await f.tasks(document)
    assert (stored.status, stored.answer, stored.producer) == (
        TaskStatus.ANSWERED,
        {"paid": True},
        "flow 1",
    )


async def test_the_token_holds_for_one_answer_until_the_deadline(world: World) -> None:
    f = await flow(world)
    await f.arrive()
    (request,) = f.asked()
    task = task_of(request)
    with pytest.raises(AuthenticationError):
        await world.tasks.answer(task, "lkt_wrong", b"{}")
    with pytest.raises(AuthenticationError):
        await world.tasks.answer(TaskId(new_id()), token_of(request), b"{}")
    await answer(f, request, {"status": "ok", "answer": 1})
    with pytest.raises(ConflictError):
        await world.tasks.answer(task, token_of(request), b'{"status": "ok", "answer": 2}')


async def test_an_answer_that_is_not_taken_counts_as_none(world: World) -> None:
    f = await flow(world)
    first, second, third = await f.arrive(), await f.arrive(), await f.arrive()
    requests = f.asked()
    tasks = [task_of(request) for request in requests]
    invalid = await world.tasks.answer(tasks[0], token_of(requests[0]), b'{"status": "maybe"}')
    assert invalid.problem == "status: 'ok' or 'error'" and not invalid.too_large
    not_json = await world.tasks.answer(tasks[1], token_of(requests[1]), b"<html>")
    assert not_json.problem == "the answer is not JSON"
    error = await world.tasks.answer(
        tasks[2], token_of(requests[2]), b'{"status": "error", "reason": "the books are closed"}'
    )
    assert error.problem is None
    await f.run()
    reasons = []
    for document in (first, second, third):
        stored = await f.stored(document)
        assert stored.processing.nodes[Node.APPLY_RULES].outcome is Outcome.UNCERTAIN
        (task,) = await f.tasks(document)
        assert task.status is TaskStatus.FAILED and task.reason is not None
        reasons.append(task.reason.code)
    assert reasons == [ReasonCode.TASK_INVALID, ReasonCode.TASK_INVALID, ReasonCode.TASK_ERROR]


async def test_a_too_large_answer_counts_as_none(world: World) -> None:
    f = await flow(world)
    document = await f.arrive()
    (request,) = f.asked()
    task = task_of(request)
    receipt = await world.tasks.answer(task, token_of(request), None)
    assert receipt.too_large and str(MAX_ANSWER_BYTES) in (receipt.problem or "")
    (stored,) = await f.tasks(document)
    assert stored.reason is not None and stored.reason.code is ReasonCode.TASK_TOO_LARGE


async def test_without_an_answer_the_task_ends_at_its_deadline(world: World) -> None:
    f = await flow(world)
    document = await f.arrive()
    world.clock.advance(4 * MINUTE)
    await f.run()
    assert (await f.stored(document)).processing.nodes[Node.APPLY_RULES].status is (
        NodeStatus.DELEGATED
    )
    world.clock.advance(MINUTE)
    await f.run()
    stored = await f.stored(document)
    assert stored.processing.nodes[Node.APPLY_RULES].outcome is Outcome.UNCERTAIN
    (task,) = await f.tasks(document)
    assert task.status is TaskStatus.EXPIRED
    (request,) = f.asked()
    with pytest.raises(AuthenticationError):  # too late
        await world.tasks.answer(task.id, token_of(request), b'{"status": "ok", "answer": 1}')


async def test_an_unreachable_consumer_gets_the_request_again_until_the_deadline(
    world: World,
) -> None:
    world.sender.answers = ["connection refused"]
    f = await flow(world)
    document = await f.arrive()
    for _ in range(12):
        world.clock.advance(30 * timedelta(seconds=1))
        await f.run()
    stored = await f.stored(document)
    assert stored.processing.nodes[Node.APPLY_RULES].outcome is Outcome.UNCERTAIN
    (task,) = await f.tasks(document)
    assert task.status is TaskStatus.FAILED and task.reason is not None
    assert task.reason.code is ReasonCode.TASK_UNDELIVERED
    tokens = {token_of(request) for request in f.asked()}
    assert len(f.asked()) > 2 and len(tokens) == 1  # the same request each time
    async with world.uow() as uow:
        webhook = await uow.webhooks.get(f.webhook.id)
    assert webhook.active and webhook.failed_streak == 0  # never switched off


async def test_a_refused_request_fails_the_task_at_once(world: World) -> None:
    world.sender.answers = [404]
    f = await flow(world)
    document = await f.arrive()
    (task,) = await f.tasks(document)
    assert task.status is TaskStatus.FAILED
    assert len(f.asked()) == 1


async def test_more_tasks_than_the_webhook_takes_wait_their_turn(world: World) -> None:
    f = await flow(world, max_open_tasks=1)
    first, second = await f.arrive(), await f.arrive()
    (task,) = await f.tasks(second)
    assert (task.status, task.deadline) == (TaskStatus.QUEUED, None)
    assert (await f.stored(second)).processing.nodes[Node.APPLY_RULES].deadline is None
    world.clock.advance(2 * MINUTE)
    (request,) = f.asked()
    await answer(f, request, {"status": "ok", "answer": "one"})
    await f.run()
    (task,) = await f.tasks(second)
    assert task.status is TaskStatus.OPEN
    assert task.deadline == builders.NOW + 7 * MINUTE  # its time starts when it is sent
    assert (await f.stored(first)).processing.nodes[Node.APPLY_RULES].outcome is Outcome.OK


async def test_more_room_lets_waiting_tasks_go(world: World) -> None:
    f = await flow(world, max_open_tasks=1)
    await f.arrive()
    second = await f.arrive()
    await world.webhooks.update(f.owner.id, f.webhook.id, max_open_tasks=2)
    await f.run()
    (task,) = await f.tasks(second)
    assert task.status is TaskStatus.OPEN and len(f.asked()) == 2


async def test_deleting_the_document_ends_its_tasks_and_frees_their_room(world: World) -> None:
    f = await flow(world, max_open_tasks=1)
    first, second = await f.arrive(), await f.arrive()
    await world.documents.delete(f.owner.id, first.id)
    async with world.uow() as uow:
        (cancelled,) = await uow.tasks.list_for_run(first.id, Node.APPLY_RULES, 1)
    assert cancelled.status is TaskStatus.CANCELLED
    with pytest.raises(ConflictError):  # the consumer learns it only now
        await answer(f, f.asked()[0], {"status": "ok", "answer": 1})
    await f.run()
    (task,) = await f.tasks(second)
    assert task.status is TaskStatus.OPEN and len(f.asked()) == 2


async def test_a_deleted_webhook_fails_the_tasks_waiting_for_it(world: World) -> None:
    f = await flow(world, max_open_tasks=1)
    first, second = await f.arrive(), await f.arrive()
    await world.webhooks.delete(f.owner.id, f.webhook.id)
    await f.run()
    (waiting,) = await f.tasks(second)
    assert waiting.status is TaskStatus.FAILED
    assert (await f.stored(second)).processing.nodes[Node.APPLY_RULES].outcome is (
        Outcome.UNCERTAIN
    )
    (open_,) = await f.tasks(first)
    assert open_.status is TaskStatus.OPEN  # runs to its deadline; an answer is still taken
    await answer(f, f.asked()[0], {"status": "ok", "answer": 1})
    await f.run()
    assert (await f.stored(first)).processing.nodes[Node.APPLY_RULES].outcome is Outcome.OK


async def test_a_template_body_sees_the_task(world: World) -> None:
    f = await flow(
        world,
        body=BodyFormat.TEMPLATE,
        body_template='{"ask": {{ title | json }}, "reply": {{ task.callback | json }}, '
        '"key": {{ task.token | json }}}',
    )
    await f.arrive()
    (request,) = f.asked()
    data = body_of(request)
    assert data["key"] == token_of(request)
    assert str(data["reply"]).startswith(f"{LINK_BASE}/api/v1/external/tasks/")


async def test_a_body_that_cannot_be_made_fails_the_task_at_once(world: World) -> None:
    f = await flow(world, body=BodyFormat.TEMPLATE, body_template='{"x": {{ title }}}')
    document = await f.arrive()
    (task,) = await f.tasks(document)
    assert task.status is TaskStatus.FAILED and f.asked() == []
    stored = await f.stored(document)
    assert stored.processing.nodes[Node.APPLY_RULES].outcome is Outcome.UNCERTAIN


async def test_without_a_public_url_no_task_can_be_sent(world: World) -> None:
    f = await flow(world)
    desk = TaskDesk(world.cipher, builders.TEMPLATES, link_base=None)
    f.pipeline.replace_executor(Node.APPLY_RULES, Asking(desk, f.webhook.id))
    document = await f.arrive()
    (task,) = await f.tasks(document)
    assert task.status is TaskStatus.FAILED and task.reason is not None
    assert "LEKTO_PUBLIC_URL" in task.reason.text
