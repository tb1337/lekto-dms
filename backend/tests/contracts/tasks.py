"""Contract suite for `TaskRepository` in the unit of work: tasks, through which nodes ask
webhooks and wait for their answers."""

from datetime import timedelta

import pytest

from lekto.core.domain.errors import ConcurrencyError, NotFoundError
from lekto.core.domain.ids import DocumentId, RuleId, UserId, WebhookId, new_id
from lekto.core.domain.pipeline import Node
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.tasks import Task, TaskKind, TaskStatus, TaskStep
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from tests.builders import HOUR, NOW

MINUTE = timedelta(minutes=1)


def a_task(
    *,
    document: DocumentId | None = None,
    webhook: WebhookId | None = None,
    run: int = 1,
    at: timedelta = timedelta(0),
    step: str = "ask",
) -> Task:
    return Task.create(
        kind=TaskKind.ASK,
        document_id=document or DocumentId(new_id()),
        node=Node.APPLY_RULES,
        run=run,
        webhook_id=webhook or WebhookId(new_id()),
        owner_id=UserId(new_id()),
        step=TaskStep(RuleId(new_id()), 2, "Invoices", step),
        timeout=5 * MINUTE,
        now=NOW + at,
    )


async def store(uow_factory: UnitOfWorkFactory, *tasks: Task) -> None:
    async with uow_factory() as uow:
        for task in tasks:
            await uow.tasks.add(task)
        await uow.commit()


class TaskRepositoryContract:
    async def test_a_task_round_trips_in_every_state(self, uow_factory: UnitOfWorkFactory) -> None:
        queued = a_task()
        sent = a_task()
        sent.open("hash", b"\x01request", NOW)
        answered = a_task()
        answered.open("hash2", b"\x01request", NOW)
        answered.answered({"paid": True, "amount": 1.5, "items": [1, None]}, "flow 1", NOW + MINUTE)
        failed = a_task()
        failed.open("hash3", b"\x01request", NOW)
        failed.fail(because(ReasonCode.TASK_ERROR, webhook="HA", reason="down"), NOW, producer="x")
        null = a_task()
        null.open("hash4", b"\x01request", NOW)
        null.answered(None, None, NOW)
        proposed = Task.create(
            kind=TaskKind.PROPOSE,
            document_id=DocumentId(new_id()),
            node=Node.SIGNAL_LLM,
            run=2,
            webhook_id=WebhookId(new_id()),
            owner_id=UserId(new_id()),
            step=None,
            timeout=10 * MINUTE,
            now=NOW,
        )
        proposed.open("hash5", b"\x01request", NOW, context={"fields": {"a1": "id"}})
        await store(uow_factory, queued, sent, answered, failed, null, proposed)
        async with uow_factory() as uow:
            for task in (queued, sent, answered, failed, null, proposed):
                assert await uow.tasks.get(task.id) == task
                assert await uow.tasks.find(task.id) == task

    async def test_a_missing_task_is_not_found(self, uow_factory: UnitOfWorkFactory) -> None:
        async with uow_factory() as uow:
            assert await uow.tasks.find(a_task().id) is None
            with pytest.raises(NotFoundError):
                await uow.tasks.get(a_task().id)

    async def test_update_checks_the_version(self, uow_factory: UnitOfWorkFactory) -> None:
        task = a_task()
        await store(uow_factory, task)
        async with uow_factory() as first, uow_factory() as second:
            one, other = await first.tasks.get(task.id), await second.tasks.get(task.id)
            one.open("hash", b"\x01request", NOW)
            await first.tasks.update(one)
            await first.commit()
            other.cancel(because(ReasonCode.TASK_RUN_OVER), NOW)
            with pytest.raises(ConcurrencyError):
                await second.tasks.update(other)
                await second.commit()
        async with uow_factory() as uow:
            stored = await uow.tasks.get(task.id)
        assert (stored.status, stored.version) == (TaskStatus.OPEN, 2)

    async def test_the_tasks_of_a_run_oldest_first(self, uow_factory: UnitOfWorkFactory) -> None:
        document = DocumentId(new_id())
        second = a_task(document=document, at=MINUTE, step="second")
        first = a_task(document=document, step="first")
        earlier_run = a_task(document=document, run=2, at=HOUR)
        other = a_task()
        await store(uow_factory, second, first, earlier_run, other)
        async with uow_factory() as uow:
            run = await uow.tasks.list_for_run(document, Node.APPLY_RULES, 1)
            assert [task.id for task in run] == [first.id, second.id]
            assert await uow.tasks.list_for_run(document, Node.FIELDS, 1) == []

    async def test_unsettled_tasks_of_a_document(self, uow_factory: UnitOfWorkFactory) -> None:
        document = DocumentId(new_id())
        queued = a_task(document=document, at=MINUTE)
        sent = a_task(document=document)
        sent.open("hash", b"\x01request", NOW)
        done = a_task(document=document, run=2)
        done.cancel(because(ReasonCode.TASK_RUN_OVER), NOW)
        await store(uow_factory, queued, sent, done, a_task())
        async with uow_factory() as uow:
            found = await uow.tasks.list_unsettled_for(document)
        assert [task.id for task in found] == [sent.id, queued.id]

    async def test_open_and_queued_tasks_of_a_webhook(self, uow_factory: UnitOfWorkFactory) -> None:
        webhook = WebhookId(new_id())
        sent = a_task(webhook=webhook)
        sent.open("hash", b"\x01request", NOW)
        later = a_task(webhook=webhook, at=2 * MINUTE)
        sooner = a_task(webhook=webhook, at=MINUTE)
        answered = a_task(webhook=webhook)
        answered.open("hash2", b"\x01request", NOW)
        answered.answered({}, None, NOW)
        await store(uow_factory, sent, later, sooner, answered, a_task())
        async with uow_factory() as uow:
            assert await uow.tasks.count_open(webhook) == 1
            assert [t.id for t in await uow.tasks.queued(webhook, limit=5)] == [
                sooner.id,
                later.id,
            ]
            assert [t.id for t in await uow.tasks.queued(webhook, limit=1)] == [sooner.id]
            assert await uow.tasks.queued(WebhookId(new_id()), limit=5) == []

    async def test_purge_removes_tasks_that_ended_before(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        old, recent, open_ = a_task(), a_task(), a_task()
        old.cancel(because(ReasonCode.TASK_RUN_OVER), NOW)
        recent.cancel(because(ReasonCode.TASK_RUN_OVER), NOW + 2 * HOUR)
        await store(uow_factory, old, recent, open_)
        async with uow_factory() as uow:
            assert await uow.tasks.purge(before=NOW + HOUR) == 1
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.tasks.find(old.id) is None
            assert await uow.tasks.find(recent.id) is not None
            assert await uow.tasks.find(open_.id) is not None
