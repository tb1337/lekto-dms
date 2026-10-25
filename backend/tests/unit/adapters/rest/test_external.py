"""`/external/tasks/{id}/result`: the consumer of a task answers it with the task's token;
`/external/tasks/{id}/files/{name}`: a file of its document by a signed link."""

from datetime import timedelta
from uuid import UUID

from lekto.adapters.inbound.rest import PREFIX
from lekto.core.domain.identity import hash_token
from lekto.core.domain.ids import DocumentId, RuleId, TaskId, WebhookId, new_id
from lekto.core.domain.pipeline import Node
from lekto.core.domain.tasks import MAX_ANSWER_BYTES, Task, TaskKind, TaskStatus, TaskStep
from lekto.core.services.objects import structure_key
from lekto.core.services.tasks.files import file_link
from tests.api import auth, bearer
from tests.unit.adapters.rest.support import Api, upload

TOKEN = "lkt_the-token-of-the-task"


async def a_task(api: Api) -> Task:
    """An open task of a document, whose token is `TOKEN`."""
    user = await api.user()
    document = DocumentId(UUID(await upload(api, auth(user))))
    task = Task.create(
        kind=TaskKind.ASK,
        document_id=document,
        node=Node.APPLY_RULES,
        run=1,
        webhook_id=WebhookId(new_id()),
        owner_id=user.id,
        step=TaskStep(RuleId(new_id()), 1, "Invoices", "accounting"),
        timeout=timedelta(minutes=5),
        now=api.clock.now(),
    )
    task.open(hash_token(TOKEN), b"\x01request", api.clock.now())
    async with api.container.unit_of_work() as uow:
        await uow.tasks.add(task)
        await uow.commit()
    return task


def url(task: Task | TaskId) -> str:
    id = task.id if isinstance(task, Task) else task
    return f"{PREFIX}/external/tasks/{id}/result"


async def stored(api: Api, task: Task) -> Task:
    async with api.container.unit_of_work() as uow:
        return await uow.tasks.get(task.id)


async def test_an_answer_with_the_task_s_token_is_taken_once(api: Api) -> None:
    task = await a_task(api)
    answer = {"status": "ok", "producer": "flow", "answer": {"paid": True}}
    response = await api.client.post(url(task), json=answer, headers=bearer(TOKEN))
    assert (response.status_code, response.content) == (204, b"")
    assert (await stored(api, task)).answer == {"paid": True}
    again = await api.client.post(url(task), json=answer, headers=bearer(TOKEN))
    assert again.status_code == 409, again.text


async def test_without_the_right_token_nothing_happens(api: Api) -> None:
    task = await a_task(api)
    answer = {"status": "ok", "answer": 1}
    for headers in ({}, bearer("lkt_wrong"), auth(await api.user())):
        response = await api.client.post(url(task), json=answer, headers=headers)
        assert response.status_code == 401, response.text
    unknown = await api.client.post(url(TaskId(new_id())), json=answer, headers=bearer(TOKEN))
    assert unknown.status_code == 401
    api.clock.advance(timedelta(minutes=5))
    late = await api.client.post(url(task), json=answer, headers=bearer(TOKEN))
    assert late.status_code == 401
    assert (await stored(api, task)).status is TaskStatus.OPEN


async def test_an_envelope_that_is_not_valid_uses_the_token_up(api: Api) -> None:
    task = await a_task(api)
    response = await api.client.post(
        url(task), json={"status": "ok", "answer": 1, "extra": 2}, headers=bearer(TOKEN)
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "unknown keys: extra"
    assert (await stored(api, task)).status is TaskStatus.FAILED
    again = await api.client.post(
        url(task), json={"status": "ok", "answer": 1}, headers=bearer(TOKEN)
    )
    assert again.status_code == 409


async def test_a_too_large_answer_is_not_read(api: Api) -> None:
    task = await a_task(api)
    body = b'{"status": "ok", "answer": "' + b"x" * MAX_ANSWER_BYTES + b'"}'
    response = await api.client.post(
        url(task),
        content=body,
        headers={**bearer(TOKEN), "content-type": "application/json"},
    )
    assert response.status_code == 413, response.text
    assert (await stored(api, task)).status is TaskStatus.FAILED


async def test_a_file_of_the_document_by_its_signed_link(api: Api) -> None:
    task = await a_task(api)
    assert task.deadline is not None
    await api.container.object_store.put(
        structure_key(task.document_id), b'{"pages": []}', content_type="application/json"
    )
    link = file_link(
        "https://lekto.example.org", api.container.cipher, task, "content.json", task.deadline
    )
    path = link.removeprefix("https://lekto.example.org")
    response = await api.client.get(path)
    assert (response.status_code, response.content) == (200, b'{"pages": []}')
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    altered = await api.client.get(path.replace("content.json", "pages/1.webp"))
    assert altered.status_code == 401
    unsigned = await api.client.get(path.split("?")[0])
    assert unsigned.status_code == 401
