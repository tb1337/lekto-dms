"""What follows when a task ends, or when a task that waits may be sent.

A node that handed work to tasks waits for their answers (`Delegation`,
`NodeStatus.DELEGATED`). Whenever one of its tasks ends, it runs anew: it reads what its tasks
brought and either goes on, or waits again for those still open. A task that waits for room
among its webhook's open tasks is sent by its node too, when it runs anew because room was
freed. So nothing but the node decides what its tasks mean, and a run that read its tasks
before they changed stores nothing (`Document.resume_node` touches the document).
"""

from dataclasses import dataclass
from datetime import datetime

from lekto.core.domain.ids import DocumentId, WebhookId
from lekto.core.domain.pipeline import Node
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.tasks import Task
from lekto.core.domain.webhooks import DEFAULT_OPEN_TASKS, Webhook
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.services._jobs import enqueue_nodes


@dataclass(frozen=True)
class Delegation:
    """What a node's run gives instead of a result when it waits for answers to its tasks
    ("running externally"); it runs anew when one of them ends. `deadline`: when the last of
    its open tasks ends at the latest (None while they wait to be sent). `again`: a task ended
    after the node's work read it (outside the transaction that stores this): the node runs
    anew at once and reads what it brought."""

    deadline: datetime | None
    again: bool = False


async def end_task(
    uow: UnitOfWork, task: Task, now: datetime, *, storing: DocumentId | None = None
) -> None:
    """Store `task`, which just ended (answered, failed, expired, cancelled), in the unit of
    work: its node runs anew, and its webhook's room goes to the tasks that wait longest.
    `storing`: the document whose node's run the unit of work stores; that run reads its tasks
    itself, so its node is left alone."""
    await uow.tasks.update(task)
    if task.document_id != storing:
        await wake_node(uow, task.document_id, task.node, task.run, now)
    await wake_queue(uow, task.webhook_id, now, storing=storing)


async def wake_node(
    uow: UnitOfWork, document_id: DocumentId, node: Node, run: int, now: datetime
) -> None:
    """Let `node` of the document run anew if it waits for its tasks in `run`."""
    document = await uow.documents.find(document_id)
    if document is None:
        return
    if document.resume_node(node, run, now):
        await enqueue_nodes(uow, document, [node], now)
    await uow.documents.update(document)
    await uow.outbox.add(document.pull_events())


async def wake_queue(
    uow: UnitOfWork, webhook_id: WebhookId, now: datetime, *, storing: DocumentId | None = None
) -> None:
    """Give the room the webhook has among its open tasks to the tasks that wait longest:
    their nodes run anew and send them. A waiting task whose run is over is cancelled.
    `storing`: as `end_task`."""
    webhook = await uow.webhooks.find(webhook_id)
    room = (
        DEFAULT_OPEN_TASKS if webhook is None else webhook.max_open_tasks
    ) - await uow.tasks.count_open(webhook_id)
    if room <= 0:
        return
    for task in await uow.tasks.queued(webhook_id, limit=room):
        document = await uow.documents.find(task.document_id)
        if document is None or document.processing.run != task.run:
            task.cancel(because(ReasonCode.TASK_RUN_OVER), now)
            await uow.tasks.update(task)
        elif task.document_id != storing:
            await wake_node(uow, task.document_id, task.node, task.run, now)


async def cancel_tasks(uow: UnitOfWork, document_id: DocumentId, now: datetime) -> None:
    """The document's run is over (processed again, deleted; the unit of work stores the
    document): its tasks that wait or are open end, and their webhooks' room goes to others.
    A late answer is refused as stale."""
    for task in await uow.tasks.list_unsettled_for(document_id):
        if task.cancel(because(ReasonCode.TASK_RUN_OVER), now):
            await uow.tasks.update(task)
            await wake_queue(uow, task.webhook_id, now, storing=document_id)


async def drop_queued(uow: UnitOfWork, webhook: Webhook, now: datetime) -> None:
    """The webhook goes: its tasks that wait to be sent never will; they fail, and their
    nodes go on as without an answer. Its open tasks run to their deadline."""
    while queued := await uow.tasks.queued(webhook.id, limit=100):
        for task in queued:
            gone = because(
                ReasonCode.TASK_UNDELIVERED, webhook=webhook.name, error="the webhook was deleted"
            )
            task.fail(gone, now)
            await uow.tasks.update(task)
            await wake_node(uow, task.document_id, task.node, task.run, now)
