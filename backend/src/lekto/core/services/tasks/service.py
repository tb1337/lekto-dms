"""The consumer's answer to a task, and the end of a task at its deadline.

| answer                                              | the task           | the API |
| --------------------------------------------------- | ------------------ | ------- |
| valid (`status` `ok` or `error`)                    | answered or failed | 204     |
| not JSON, or an envelope that is not valid          | failed             | 422     |
| larger than `MAX_ANSWER_BYTES`                      | failed             | 413     |
| answered before, or its run is over                 | unchanged          | 409     |
| unknown task or token, or the deadline has passed   | unchanged          | 401     |

`status: error` and an answer that is not taken count as none: the node goes on as the step
says for a missing answer. The token is used up with the first answer that is read.
"""

import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from lekto.core.domain.errors import AuthenticationError, ConflictError, ValidationError
from lekto.core.domain.identity import hash_token
from lekto.core.domain.ids import TaskId
from lekto.core.domain.jobs import Job
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.tasks import MAX_ANSWER_BYTES, Task, TaskStatus, parse_answer
from lekto.core.ports.clock import Clock
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._jobs import LEASE, STORE_ATTEMPTS, JobRunner, retrying
from lekto.core.services.tasks.desk import EXPIRE_JOB
from lekto.core.services.tasks.settling import end_task

log = logging.getLogger(__name__)

UNKNOWN_TOKEN = "unknown task or token, or its time is up"
STALE = "the task was answered already, or its document was processed again or deleted"


@dataclass(frozen=True)
class AnswerReceipt:
    """How an answer was taken: `problem` is None if it was; otherwise why it counts as none
    (the token is used up), and `too_large` if it was not read for its size."""

    problem: str | None = None
    too_large: bool = False


class TaskService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock
        self._jobs = JobRunner(uow, clock)

    async def answer(self, id: TaskId, token: str, body: bytes | None) -> AnswerReceipt:
        """The consumer answers task `id` with its token; `body` None: it was larger than
        `MAX_ANSWER_BYTES` and not read. AuthenticationError for an unknown task or token or a
        deadline that has passed, ConflictError for a task answered before or whose run is
        over; see the module."""

        async def take() -> AnswerReceipt:
            now = self._clock.now()
            async with self._uow() as uow:
                task = await uow.tasks.find(id)
                if task is None or not _token_matches(task, token):
                    raise AuthenticationError(UNKNOWN_TOKEN)
                if task.status is TaskStatus.EXPIRED or (
                    task.deadline is not None and now >= task.deadline
                ):
                    raise AuthenticationError(UNKNOWN_TOKEN)
                if task.status is not TaskStatus.OPEN:
                    raise ConflictError(STALE)
                document = await uow.documents.find(task.document_id)
                if document is None or document.processing.run != task.run:
                    task.cancel(because(ReasonCode.TASK_RUN_OVER), now)
                    await end_task(uow, task, now)
                    await uow.commit()
                    raise ConflictError(STALE)
                receipt = await _take(uow, task, body, now)
                await end_task(uow, task, now)
                await uow.commit()
            return receipt

        receipt = await retrying(take, attempts=STORE_ATTEMPTS, backoff=True)
        log.info(
            "task answered",
            extra={"task_id": str(id), "taken": receipt.problem is None},
        )
        return receipt

    # --- deadlines ------------------------------------------------------------------------------

    async def run_next_job(self) -> bool:
        """Claim and run a due job that ends a task at its deadline. False if none was due."""
        return await self._jobs.run_next([EXPIRE_JOB], LEASE, self._expire)

    async def _expire(self, job: Job) -> None:
        try:
            id = TaskId(UUID(str(job.payload["task_id"])))
        except (KeyError, ValueError) as error:
            await self._jobs.invalid(job, error)
            return

        async def expire() -> None:
            now = self._clock.now()
            async with self._uow() as uow:
                task = await uow.tasks.find(id)
                if task is not None and task.status is TaskStatus.OPEN:
                    assert task.deadline is not None
                    if now < task.deadline:  # claimed early: the deadline decides
                        await uow.jobs.reschedule(job, run_at=task.deadline, error="early")
                        await uow.commit()
                        return
                    webhook = await uow.webhooks.find(task.webhook_id)
                    name = str(task.webhook_id) if webhook is None else webhook.name
                    task.expire(because(ReasonCode.TASK_NO_ANSWER, webhook=name), now)
                    await end_task(uow, task, now)
                await uow.jobs.complete(job)
                await uow.commit()

        await self._jobs.storing(job, expire)


def _token_matches(task: Task, token: str) -> bool:
    return task.token_hash is not None and hmac.compare_digest(task.token_hash, hash_token(token))


async def _take(uow: UnitOfWork, task: Task, body: bytes | None, now: datetime) -> AnswerReceipt:
    """Answer or fail `task` from `body`; how it was taken."""
    webhook = await uow.webhooks.find(task.webhook_id)
    name = str(task.webhook_id) if webhook is None else webhook.name
    if body is None:
        task.fail(because(ReasonCode.TASK_TOO_LARGE, webhook=name, limit=MAX_ANSWER_BYTES), now)
        return AnswerReceipt(f"the answer is larger than {MAX_ANSWER_BYTES} bytes", True)
    try:
        envelope = parse_answer(json.loads(body))
    except (ValueError, ValidationError) as error:
        detail = str(error) if isinstance(error, ValidationError) else "the answer is not JSON"
        task.fail(because(ReasonCode.TASK_INVALID, webhook=name, detail=detail), now)
        return AnswerReceipt(detail)
    if envelope.ok:
        task.answered(envelope.answer, envelope.producer, now)
    else:
        failed = because(ReasonCode.TASK_ERROR, webhook=name, reason=envelope.reason)
        task.fail(failed, now, producer=envelope.producer)
    return AnswerReceipt()
