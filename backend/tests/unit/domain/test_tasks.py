from datetime import timedelta

import pytest

from lekto.core.domain.errors import InvalidTransitionError, ValidationError
from lekto.core.domain.ids import DocumentId, RuleId, UserId, WebhookId, new_id
from lekto.core.domain.pipeline import Node
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.tasks import (
    MAX_REASON,
    Task,
    TaskKind,
    TaskStatus,
    TaskStep,
    parse_answer,
    validate_timeout,
)
from tests.builders import NOW

MINUTE = timedelta(minutes=1)
GONE = because(ReasonCode.TASK_RUN_OVER)


def a_task(timeout: timedelta = 5 * MINUTE) -> Task:
    return Task.create(
        kind=TaskKind.ASK,
        document_id=DocumentId(new_id()),
        node=Node.APPLY_RULES,
        run=1,
        webhook_id=WebhookId(new_id()),
        owner_id=UserId(new_id()),
        step=TaskStep(RuleId(new_id()), 3, "Invoices", "accounting"),
        timeout=timeout,
        now=NOW,
    )


def test_a_task_waits_until_it_is_sent_and_its_deadline_starts_then() -> None:
    task = a_task()
    assert (task.status, task.deadline, task.token_hash) == (TaskStatus.QUEUED, None, None)
    task.open("hash", b"request", NOW + MINUTE)
    assert (task.status, task.deadline) == (TaskStatus.OPEN, NOW + 6 * MINUTE)
    task.delivered()
    assert task.encrypted_request is None and task.token_hash == "hash"


def test_an_answer_ends_it_and_forgets_the_request() -> None:
    task = a_task()
    task.open("hash", b"request", NOW)
    task.answered({"paid": True}, "flow", NOW + MINUTE)
    assert (task.status, task.answer, task.producer) == (
        TaskStatus.ANSWERED,
        {"paid": True},
        "flow",
    )
    assert task.encrypted_request is None and task.settled_at == NOW + MINUTE
    with pytest.raises(InvalidTransitionError):
        task.answered({}, None, NOW)
    assert not task.cancel(GONE, NOW)


def test_it_expires_only_once_the_deadline_passed() -> None:
    task = a_task()
    task.open("hash", b"request", NOW)
    no_answer = because(ReasonCode.TASK_NO_ANSWER, webhook="HA")
    assert not task.expire(no_answer, NOW + 4 * MINUTE)
    assert task.expire(no_answer, NOW + 5 * MINUTE)
    assert (task.status, task.reason) == (TaskStatus.EXPIRED, no_answer)


def test_a_queued_task_may_fail_or_be_cancelled_but_not_answered() -> None:
    task = a_task()
    with pytest.raises(InvalidTransitionError):
        task.answered({}, None, NOW)
    assert task.cancel(GONE, NOW)
    assert task.status is TaskStatus.CANCELLED and task.status.settled


def test_its_states_are_consistent() -> None:
    task = a_task()
    with pytest.raises(ValidationError, match="reason"):
        Task(**{**vars(task), "status": TaskStatus.FAILED, "settled_at": NOW})
    with pytest.raises(ValidationError, match="sent"):
        Task(**{**vars(task), "status": TaskStatus.OPEN})
    with pytest.raises(ValidationError, match="step"):
        Task(**{**vars(task), "step": None})


@pytest.mark.parametrize("seconds", [29, 24 * 3600 + 1])
def test_the_time_to_answer_is_bounded(seconds: int) -> None:
    with pytest.raises(ValidationError):
        validate_timeout(timedelta(seconds=seconds))


def test_an_answer_is_an_envelope() -> None:
    ok = parse_answer({"status": "ok", "producer": "flow 2", "answer": [1, 2]})
    assert (ok.ok, ok.answer, ok.producer) == (True, [1, 2], "flow 2")
    assert parse_answer({"status": "ok", "answer": None}).answer is None
    error = parse_answer({"status": "error", "reason": "down\nfor\tmaintenance " + "x" * 400})
    assert not error.ok and error.reason is not None
    assert error.reason.startswith("down for maintenance") and len(error.reason) == MAX_REASON


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "object"),
        ({"status": "ok"}, "'answer'"),
        ({"status": "ok", "answer": 1, "reason": "x"}, "no 'reason'"),
        ({"status": "error"}, "'reason'"),
        ({"status": "error", "reason": "x", "answer": 1}, "no 'answer'"),
        ({"status": "maybe", "answer": 1}, "status"),
        ({"status": "ok", "answer": 1, "extra": 1}, "unknown keys: extra"),
        ({"status": "ok", "answer": 1, "producer": "x" * 101}, "producer"),
        ({"status": "ok", "answer": 1, "producer": "a\nb"}, "producer"),
    ],
)
def test_an_envelope_that_is_not_valid_says_why(data: object, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        parse_answer(data)  # type: ignore[arg-type]
