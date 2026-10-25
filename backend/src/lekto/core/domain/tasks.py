"""Tasks: requests through a webhook that expect an answer (`webhooks-und-auftraege.md`).

A node that needs something from outside (a rule step that asks) hands it to a task and waits
for its answer ("running externally", `NodeStatus.DELEGATED`). A task:

1. waits in Lekto (`QUEUED`) while its webhook has as many open tasks as it takes
   (`Webhook.max_open_tasks`);
2. is sent (`OPEN`): it gets a one-time token, only whose hash is kept, and its deadline, which
   starts now. The request with the token waits encrypted until it is delivered;
3. ends (`settled`): answered, failed (an error answer, an invalid one, not deliverable),
   expired (no answer by the deadline), or cancelled (its run is over: the document was
   processed again or deleted).

The consumer answers with `POST /api/v1/external/tasks/{id}/result`, the token as
`Authorization: Bearer`, and an envelope (`parse_answer`).
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from lekto.core.domain.errors import InvalidTransitionError, ValidationError
from lekto.core.domain.ids import DocumentId, RuleId, TaskId, UserId, WebhookId, new_id
from lekto.core.domain.json_value import JsonObject, JsonValue, as_object, as_uuid
from lekto.core.domain.pipeline import Node
from lekto.core.domain.reasons import Reason
from lekto.core.domain.validation import require_utc

TOKEN_PREFIX = "lkt_"
"""The beginning of a task's token, so a leaked one is recognised."""
MAX_ANSWER_BYTES = 1_000_000
"""The largest answer Lekto reads (1 MB); a larger one is refused (413) and counts as none."""
MAX_REASON = 300
"""The reason of an error answer is cut to this many characters (plain text)."""
MAX_PRODUCER = 100
DEFAULT_TIMEOUT = timedelta(minutes=5)
MIN_TIMEOUT = timedelta(seconds=30)
MAX_TIMEOUT = timedelta(hours=24)
"""How long a task's consumer has to answer, from sending: 30 seconds to 24 hours."""


class TaskKind(StrEnum):
    ASK = "rule.ask"  # a rule step asks a webhook (`rules.AskWebhook`)


class TaskStatus(StrEnum):
    QUEUED = "queued"  # waits for a free place among its webhook's open tasks
    OPEN = "open"  # sent or being delivered; its deadline runs
    ANSWERED = "answered"
    FAILED = "failed"  # an error answer, an invalid one, or not deliverable
    EXPIRED = "expired"  # no answer by the deadline
    CANCELLED = "cancelled"  # its run is over

    @property
    def settled(self) -> bool:
        return self not in (TaskStatus.QUEUED, TaskStatus.OPEN)


@dataclass(frozen=True)
class TaskStep:
    """The rule step a task asks for: the rule (its id, version and name) and the step's
    name, unique in the rule."""

    rule_id: RuleId
    version: int
    rule: str
    step: str

    @property
    def key(self) -> str:
        """Identifies the step among the tasks of a node's run."""
        return f"{self.rule_id}:{self.version}:{self.step}"

    def to_json(self) -> JsonObject:
        return {
            "rule_id": str(self.rule_id),
            "version": self.version,
            "rule": self.rule,
            "step": self.step,
        }

    @classmethod
    def from_json(cls, data: JsonValue) -> "TaskStep":
        item = as_object(data) or {}
        rule_id, version = as_uuid(item.get("rule_id")), item.get("version")
        rule, step = item.get("rule"), item.get("step")
        if (
            rule_id is None
            or not isinstance(version, int)
            or not isinstance(rule, str)
            or not isinstance(step, str)
        ):
            raise ValidationError(f"not a task's step: {data!r}")
        return cls(RuleId(rule_id), version, rule, step)


@dataclass(kw_only=True)
class Task:
    """A request that expects an answer, for `node` of `document_id` in processing run `run`.

    `owner_id`: whose webhook it goes through (the rights are theirs). `timeout`: how long the
    consumer has from sending. `token_hash`: of the one-time token, from sending on;
    `encrypted_request` the request with the token (`SecretCipher`), from sending until it is
    delivered or the task ends. `answer` and `producer` come with the answer; `reason` says why
    a task failed, expired or was cancelled."""

    id: TaskId
    kind: TaskKind
    document_id: DocumentId
    node: Node
    run: int
    webhook_id: WebhookId
    owner_id: UserId
    step: TaskStep | None
    timeout: timedelta
    status: TaskStatus = TaskStatus.QUEUED
    token_hash: str | None = field(default=None, repr=False)
    encrypted_request: bytes | None = field(default=None, repr=False)
    answer: JsonValue = None
    producer: str | None = None
    reason: Reason | None = None
    created_at: datetime
    opened_at: datetime | None = None
    deadline: datetime | None = None
    settled_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        self.timeout = validate_timeout(self.timeout)
        if self.run < 1:
            raise ValidationError("run starts at 1")
        if (self.kind is TaskKind.ASK) != (self.step is not None):
            raise ValidationError("exactly a rule's task names its step")
        self.created_at = require_utc(self.created_at, "created_at")
        for name in ("opened_at", "deadline", "settled_at"):
            if (value := getattr(self, name)) is not None:
                setattr(self, name, require_utc(value, name))
        if (self.opened_at is None) != (self.deadline is None) or (
            (self.opened_at is None) != (self.token_hash is None)
        ):
            raise ValidationError("a task sent has a token and a deadline, and only then")
        if self.status is TaskStatus.QUEUED and self.opened_at is not None:
            raise ValidationError("a queued task is not sent")
        if self.status is TaskStatus.OPEN and self.opened_at is None:
            raise ValidationError("an open task was sent")
        if self.status.settled != (self.settled_at is not None):
            raise ValidationError("exactly a settled task has an end")
        if self.status.settled and self.encrypted_request is not None:
            raise ValidationError("a settled task keeps no request")
        if self.status is not TaskStatus.ANSWERED and self.answer is not None:
            raise ValidationError("only an answered task has an answer")
        if self.status not in (TaskStatus.ANSWERED, TaskStatus.FAILED) and self.producer:
            raise ValidationError("only an answered or failed task names what answered")
        if self.status in (TaskStatus.FAILED, TaskStatus.EXPIRED, TaskStatus.CANCELLED) and (
            self.reason is None
        ):
            raise ValidationError(f"a {self.status} task has a reason")

    @classmethod
    def create(
        cls,
        *,
        kind: TaskKind,
        document_id: DocumentId,
        node: Node,
        run: int,
        webhook_id: WebhookId,
        owner_id: UserId,
        step: TaskStep | None,
        timeout: timedelta,
        now: datetime,
    ) -> "Task":
        """A task that waits to be sent."""
        return cls(
            id=TaskId(new_id()),
            kind=kind,
            document_id=document_id,
            node=node,
            run=run,
            webhook_id=webhook_id,
            owner_id=owner_id,
            step=step,
            timeout=timeout,
            created_at=now,
        )

    @property
    def key(self) -> str:
        """Identifies what the task asks for among the tasks of its node's run."""
        return self.kind.value if self.step is None else self.step.key

    def open(self, token_hash: str, encrypted_request: bytes, now: datetime) -> None:
        """Sent from now on: the deadline starts."""
        self._require(TaskStatus.QUEUED)
        self.status = TaskStatus.OPEN
        self.token_hash = token_hash
        self.encrypted_request = encrypted_request
        self.opened_at = require_utc(now, "opened_at")
        self.deadline = self.opened_at + self.timeout

    def delivered(self) -> None:
        """The consumer took the request: Lekto forgets it (and the token)."""
        self.encrypted_request = None

    def answered(self, answer: JsonValue, producer: str | None, now: datetime) -> None:
        self._require(TaskStatus.OPEN)
        self.answer = answer
        self.producer = producer
        self._settle(TaskStatus.ANSWERED, None, now)

    def fail(self, reason: Reason, now: datetime, *, producer: str | None = None) -> None:
        """An error answer, an invalid one, or the request could not be delivered."""
        self._require(TaskStatus.QUEUED, TaskStatus.OPEN)
        self.producer = producer
        self._settle(TaskStatus.FAILED, reason, now)

    def expire(self, reason: Reason, now: datetime) -> bool:
        """No answer by the deadline; False (and nothing changes) if it has not passed or the
        task is not open."""
        if self.status is not TaskStatus.OPEN or self.deadline is None or now < self.deadline:
            return False
        self._settle(TaskStatus.EXPIRED, reason, now)
        return True

    def cancel(self, reason: Reason, now: datetime) -> bool:
        """Its run is over; False if it had ended already."""
        if self.status.settled:
            return False
        self._settle(TaskStatus.CANCELLED, reason, now)
        return True

    def _settle(self, status: TaskStatus, reason: Reason | None, now: datetime) -> None:
        self.status = status
        self.reason = reason
        self.encrypted_request = None
        self.settled_at = require_utc(now, "settled_at")

    def _require(self, *statuses: TaskStatus) -> None:
        if self.status not in statuses:
            raise InvalidTransitionError(f"task {self.id} is {self.status}")


def validate_timeout(value: timedelta) -> timedelta:
    """ValidationError outside `MIN_TIMEOUT` to `MAX_TIMEOUT`."""
    if not MIN_TIMEOUT <= value <= MAX_TIMEOUT:
        raise ValidationError(
            f"a task's time: {int(MIN_TIMEOUT.total_seconds())} seconds to "
            f"{int(MAX_TIMEOUT.total_seconds() // 3600)} hours"
        )
    return value


# --- the answer ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskAnswer:
    """The envelope of an answer: `ok` with `answer` (any JSON), or an error with `reason`;
    `producer` names what answered (for the log)."""

    ok: bool
    answer: JsonValue = None
    reason: str | None = None
    producer: str | None = None


_ENVELOPE = frozenset({"status", "producer", "answer", "reason"})
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def parse_answer(data: JsonValue) -> TaskAnswer:
    """The envelope of an answer, checked strictly: an object with `status` `ok` and `answer`,
    or `status` `error` and `reason` (a text, cut to `MAX_REASON` characters, control
    characters turned into spaces); `producer` optional, a text of at most `MAX_PRODUCER`
    characters without control characters. ValidationError naming what is wrong."""
    item = as_object(data)
    if item is None:
        raise ValidationError("the answer is a JSON object")
    unknown = sorted(set(item) - _ENVELOPE)
    if unknown:
        raise ValidationError(f"unknown keys: {', '.join(unknown)}")
    producer = item.get("producer")
    if producer is not None and (
        not isinstance(producer, str)
        or not producer.strip()
        or len(producer) > MAX_PRODUCER
        or _CONTROL.search(producer) is not None
    ):
        raise ValidationError(f"producer: a text of 1 to {MAX_PRODUCER} characters")
    match item.get("status"):
        case "ok":
            if "answer" not in item:
                raise ValidationError("an answer with status 'ok' has 'answer'")
            if "reason" in item:
                raise ValidationError("an answer with status 'ok' has no 'reason'")
            return TaskAnswer(ok=True, answer=item["answer"], producer=producer)
        case "error":
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValidationError("an answer with status 'error' has a 'reason' text")
            if "answer" in item:
                raise ValidationError("an answer with status 'error' has no 'answer'")
            text = _CONTROL.sub(" ", reason).strip()[:MAX_REASON]
            return TaskAnswer(ok=False, reason=text, producer=producer)
    raise ValidationError("status: 'ok' or 'error'")
