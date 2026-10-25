"""Model calls a webhook takes over (`webhooks-und-auftraege.md`, "Modellaufrufe als Auftrag").

An admin's webhook that serves as `propose` or `extract` (`ModelCallRole`,
`serving_model_call`) replaces the language model of the configuration for that request: the
node sends a task with the context, no prompt (the consumer makes its own), and waits for the
answer ("running externally"). The answer is checked as a model's is: its structure when it
comes (`check_answer`: one that does not fit is refused with 422 and fails the task), its values
by the judge and the fields node, as the model's are. An error answer, an invalid one and none
by the deadline fail the node (red); there is no second attempt.

What goes out: the text in full, the structure (`content.json`) and the page images as signed
links (`tasks.files`), the master data the prompt would list, and the answer's JSON Schema
with the rules of the system prompt as descriptions. Lekto's guard against instructions in the
text and the budget for the text are the consumer's.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import FieldDefinition, FieldType
from lekto.core.domain.ids import FieldId
from lekto.core.domain.json_value import JsonObject, JsonValue, as_object
from lekto.core.domain.master_data import one_line
from lekto.core.domain.pipeline import (
    MODEL,
    TRUNCATED,
    Node,
    NodeResult,
    Outcome,
    ProcessingStatus,
)
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.tasks import DEFAULT_TIMEOUT, Task, TaskKind, TaskStatus
from lekto.core.domain.webhooks import ModelCallKind, Webhook
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services.classification.answers import (
    AnswerError,
    Proposal,
    ProposeAnswer,
    described,
    extract_schema,
    parse_extract,
    parse_propose,
)
from lekto.core.services.classification.prompts import (
    EVIDENCE_RULE,
    EXTRACT_RULE,
    LABEL_RULE,
    NO_INVENTION,
    PROPOSE_RULES,
    VALUE_FORMS,
    WRITTEN_FORMS,
    Listed,
)
from lekto.core.services.objects import text_key
from lekto.core.services.tasks.desk import Ask, TaskDesk, TaskRequest
from lekto.core.services.tasks.files import STRUCTURE, page_file
from lekto.core.services.tasks.settling import Delegation, end_task
from lekto.core.services.webhooks.management import serving_model_call

PROPOSE_CONTRACT = "propose-ext-1"
EXTRACT_CONTRACT = "extract-ext-1"
"""The versions of the contexts a model call sends; the processing log names them where it
names the prompt of the language model."""
CONTRACT = "contract"
"""Key of the contract in the context, in `Task.context` and in the node's input."""
EXTERNAL = "external"
"""`model_version` of a node a webhook answered for without naming what answered."""

NODES: Mapping[TaskKind, Node] = {TaskKind.PROPOSE: Node.SIGNAL_LLM, TaskKind.EXTRACT: Node.FIELDS}
_ROLES: Mapping[TaskKind, ModelCallKind] = {
    TaskKind.PROPOSE: ModelCallKind.PROPOSE,
    TaskKind.EXTRACT: ModelCallKind.EXTRACT,
}
_FIELDS, _SPACES = "fields", "spaces"


# --- the context --------------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelCallContext:
    """What a model call sends (`tasks.desk.Contract`): `document` without the links,
    `lists` the master data and the answer's schema, `pages` how many page images there are to
    link, `keys` what the node needs to read the answer (the contract and the keys of fields
    and spaces)."""

    contract: str
    document: JsonObject
    lists: JsonObject
    pages: int
    keys: JsonObject

    def body(self, task: JsonObject, link: Callable[[str], str]) -> JsonObject:
        document: JsonObject = {
            **self.document,
            "structure": link(STRUCTURE),
            "page_images": [link(page_file(number)) for number in range(1, self.pages + 1)],
        }
        return {CONTRACT: self.contract, "task": task, "document": document, **self.lists}

    def logged(self) -> str:
        """The context as the document keeps it (`exchanges`): without the task and the links."""
        kept = {CONTRACT: self.contract, "document": self.document, **self.lists}
        return json.dumps(kept, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class ListedSpace:
    """A space a proposal may choose, by its key (`s1`, ...): what the prompt calls it and
    what is written about it."""

    id: UUID
    label: str
    description: str | None = None

    @property
    def prompt_label(self) -> str:
        return self.label + (f": {self.description}" if self.description else "")


def _document(document: Document, text: str) -> JsonObject:
    return {
        "filename": document.original_filename,
        "media_type": document.media_type,
        "pages": document.page_count,
        "received": document.created_at.date().isoformat(),
        "text": text,
    }


def _field(definition: FieldDefinition, forms: Mapping[FieldType, str]) -> JsonObject:
    item: JsonObject = {
        "name": definition.name,
        "type": definition.data_type.value,
        "form": forms[definition.data_type],
    }
    if definition.data_type is FieldType.CHOICE:
        item["choices"] = list(definition.choices)
    if definition.description:
        item["description"] = definition.description
    return item


_PROPOSE_DESCRIPTIONS: Mapping[str, str] = {
    "": f"The metadata proposed for the document. {NO_INVENTION}",
    **PROPOSE_RULES,
    "new_document_type": PROPOSE_RULES["document_type"],
    "new_tags": PROPOSE_RULES["tags"],
    "sender.evidence": EVIDENCE_RULE,
    "document_date.evidence": EVIDENCE_RULE,
    "fields.key": "the key of the field (`fields` of the context)",
    "fields.value": "the value as written in the document (an amount with its currency)",
    "fields.evidence": EVIDENCE_RULE,
    "fields.label": LABEL_RULE,
}


def propose_context(
    document: Document,
    text: str,
    *,
    contacts: Sequence[Listed],
    document_types: Sequence[tuple[Listed, Sequence[tuple[str, FieldDefinition]]]],
    general: Sequence[tuple[str, FieldDefinition]],
    tags: Sequence[str],
    spaces: Mapping[str, ListedSpace],
    schema: JsonObject,
) -> ModelCallContext:
    """The context of `propose` (`PROPOSE_CONTRACT`): what the prompt `propose-5` lists, as
    JSON, with the schema of the answer."""
    fields: dict[str, FieldDefinition] = {}
    for _, typed in document_types:
        fields.update(typed)
    fields.update(general)
    lists: JsonObject = {
        "contacts": [
            {"name": item.name, "aliases": list(item.aliases), "topics": list(item.topics)}
            for item in contacts
        ],
        "document_types": [
            {
                "name": listed.name,
                "description": listed.description,
                "fields": [key for key, _ in typed],
            }
            for listed, typed in document_types
        ],
        "fields": {key: _field(definition, WRITTEN_FORMS) for key, definition in fields.items()},
        "general_fields": [key for key, _ in general],
        "tags": list(tags),
        "spaces": [
            {"key": key, "label": space.label, "description": space.description}
            for key, space in spaces.items()
        ],
        "answer_schema": described(schema, _PROPOSE_DESCRIPTIONS),
    }
    keys: JsonObject = {
        CONTRACT: PROPOSE_CONTRACT,
        _FIELDS: {key: str(definition.id) for key, definition in fields.items()},
        _SPACES: {key: str(space.id) for key, space in spaces.items()},
    }
    return ModelCallContext(
        PROPOSE_CONTRACT, _document(document, text), lists, document.page_count or 0, keys
    )


def extract_context(
    document: Document,
    text: str,
    document_type: str | None,
    keys: Mapping[str, FieldDefinition],
) -> ModelCallContext:
    """The context of `extract` (`EXTRACT_CONTRACT`): the fields to read, by key, with the
    schema of the answer."""
    descriptions = {"": f"The values of the fields. {NO_INVENTION}", _FIELDS: EXTRACT_RULE}
    for key, definition in keys.items():
        about = f'"{one_line(definition.name)}"'
        if definition.description:
            about += f": {one_line(definition.description)}"
        descriptions |= {
            f"{_FIELDS}.{key}": about,
            f"{_FIELDS}.{key}.value": VALUE_FORMS[definition.data_type],
            f"{_FIELDS}.{key}.evidence": EVIDENCE_RULE,
            f"{_FIELDS}.{key}.label": LABEL_RULE,
        }
    lists: JsonObject = {
        "document_type": document_type,
        _FIELDS: {key: _field(definition, VALUE_FORMS) for key, definition in keys.items()},
        "answer_schema": described(extract_schema(dict(keys)), descriptions),
    }
    sent: JsonObject = {
        CONTRACT: EXTRACT_CONTRACT,
        _FIELDS: {key: str(definition.id) for key, definition in keys.items()},
    }
    return ModelCallContext(
        EXTRACT_CONTRACT, _document(document, text), lists, document.page_count or 0, sent
    )


# --- the answer ---------------------------------------------------------------------------------


def check_answer(task: Task, answer: JsonValue) -> None:
    """ValidationError if `answer` to a model call does not have the structure the context
    asked for (as a model's answer is checked); nothing for other tasks."""
    try:
        if task.kind is TaskKind.PROPOSE:
            _proposal(task.context, answer)
        elif task.kind is TaskKind.EXTRACT:
            _values(task.context, answer)
    except AnswerError as error:
        raise ValidationError(str(error)) from None


def proposal_of(task: Task) -> tuple[ProposeAnswer, dict[str, FieldId], dict[str, UUID]]:
    """The answered proposal, and the ids of the fields and spaces by the keys sent.
    AnswerError if it does not fit (it was checked when it came)."""
    return (
        _proposal(task.context, task.answer),
        {key: FieldId(UUID(id)) for key, id in _ids(task.context, _FIELDS).items()},
        {key: UUID(id) for key, id in _ids(task.context, _SPACES).items()},
    )


def values_of(task: Task) -> dict[FieldId, Proposal]:
    """The answered values by field id. AnswerError if they do not fit."""
    ids = _ids(task.context, _FIELDS)
    return {
        FieldId(UUID(ids[key])): value for key, value in _values(task.context, task.answer).items()
    }


def _proposal(context: JsonObject, answer: JsonValue) -> ProposeAnswer:
    return parse_propose(
        json.dumps(answer), list(_ids(context, _FIELDS)), list(_ids(context, _SPACES))
    )


def _values(context: JsonObject, answer: JsonValue) -> dict[str, Proposal]:
    return parse_extract(json.dumps(answer), list(_ids(context, _FIELDS)))


def _ids(context: JsonObject, name: str) -> dict[str, str]:
    return {
        key: value
        for key, value in (as_object(context.get(name)) or {}).items()
        if isinstance(value, str)
    }


# --- the task -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelCallState:
    """How the model call `kind` of a node stands in the document's run: its latest `task`,
    the `webhook` that serves the kind now and the name of the task's webhook (`webhook`
    without a task)."""

    kind: TaskKind
    desk: TaskDesk
    task: Task | None
    webhook: Webhook | None
    name: str

    @property
    def settled(self) -> Task | None:
        """The task, if it ended: the node reads what it brought."""
        return self.task if self.task is not None and self.task.status.settled else None

    @property
    def sent(self) -> bool:
        """Whether the task is open: it went out and the node waits."""
        return self.task is not None and self.task.status is TaskStatus.OPEN

    def input(self, document: Document, text: str) -> JsonObject:
        """The node's input for the log: the text as it went, the contract and the webhook,
        and what answered (`MODEL`)."""
        task = self.task
        assert task is not None
        input: JsonObject = {
            "text": text_key(document.id),
            "characters": len(text),
            "sent": len(text),
            TRUNCATED: False,
            CONTRACT: task.context.get(CONTRACT),
            "webhook": self.name,
            "task": str(task.id),
        }
        for name in (_FIELDS, _SPACES):
            if name in task.context:
                input[name] = task.context[name]
        if task.producer:
            input[MODEL] = task.producer
        return input

    def failed(self, input: JsonObject) -> NodeResult:
        """The node's result when the task ended without an answer (red)."""
        task = self.task
        assert task is not None and task.status is not TaskStatus.ANSWERED
        reason = task.reason or because(ReasonCode.TASK_RUN_OVER)
        return NodeResult(
            outcome=Outcome.FAILED,
            reasons=(reason,),
            model_version=task.producer or EXTERNAL,
            input=input,
        )

    def unfit(self, input: JsonObject, detail: str) -> NodeResult:
        """The node's result when the answer does not fit what was sent (red)."""
        unfit = because(ReasonCode.TASK_INVALID, webhook=self.name, detail=detail)
        return NodeResult(
            outcome=Outcome.FAILED,
            reasons=(unfit,),
            model_version=self.model_version,
            input=input,
        )

    @property
    def model_version(self) -> str:
        assert self.task is not None
        return self.task.producer or EXTERNAL


async def model_call_state(
    uow: UnitOfWorkFactory, desk: TaskDesk | None, document: Document, kind: TaskKind
) -> ModelCallState | None:
    """How the model call stands; None if no webhook answers it in the document's run (none
    serves the kind, and no task was placed): the language model of the configuration does,
    if there is one."""
    if desk is None:
        return None
    async with uow() as unit:
        task = await _latest(unit, document, kind)
        webhook = await serving_model_call(unit, _ROLES[kind])
        used = webhook if task is None else await unit.webhooks.find(task.webhook_id)
    if task is None and webhook is None:
        return None
    name = used.name if used is not None else str(task.webhook_id) if task is not None else ""
    return ModelCallState(kind, desk, task, webhook, name)


async def _latest(uow: UnitOfWork, document: Document, kind: TaskKind) -> Task | None:
    """The latest task of the model call in the document's run; one cancelled because its
    webhook serves no more does not count: the node asks anew."""
    tasks = await uow.tasks.list_for_run(document.id, NODES[kind], document.processing.run)
    return next(
        (
            task
            for task in reversed(tasks)
            if task.kind is kind and task.status is not TaskStatus.CANCELLED
        ),
        None,
    )


@dataclass(frozen=True)
class ExternalCall:
    """A node's run that hands its model call to a task (`DeferredResult`): in the transaction
    that stores it, the task is placed (sent, or waiting for room) unless it was, and the node
    waits for it. A task that ended meanwhile lets the node run anew at once. `context`: what
    to send; None while the task is open (nothing to send)."""

    state: ModelCallState
    context: ModelCallContext | None

    async def apply(
        self, uow: UnitOfWork, document: Document, now: datetime
    ) -> NodeResult | Delegation:
        kind = self.state.kind
        node = NODES[kind]
        task = await _latest(uow, document, kind)
        if task is not None and task.status.settled:
            return Delegation(None, again=True)
        if task is not None and task.status is TaskStatus.OPEN:
            return Delegation(task.deadline)
        if document.processing.status is not ProcessingStatus.PROCESSING:
            # The run failed meanwhile: the document goes out to no one.
            stopped = because(ReasonCode.TASK_RUN_STOPPED, webhook=self.state.name)
            if task is not None:  # it waited for room: it frees its place
                task.cancel(stopped, now)
                await end_task(uow, task, now, storing=document.id)
            return NodeResult(outcome=Outcome.UNCERTAIN, reasons=(stopped,))
        if self.context is None:
            return Delegation(None, again=True)  # it waits to be sent: the next run sends it
        serving = await serving_model_call(uow, _ROLES[kind])
        webhook = serving if task is None else await uow.webhooks.find(task.webhook_id)
        if webhook is None or serving is None or serving.id != webhook.id:
            # The role moved on (or the webhook went) since the node read it: it asks anew,
            # whoever answers now.
            if task is not None:
                gone = because(
                    ReasonCode.TASK_UNDELIVERED,
                    webhook=self.state.name,
                    error="the webhook serves the model call no more",
                )
                task.cancel(gone, now)
                await end_task(uow, task, now, storing=document.id)
            return Delegation(None, again=True)
        if task is None and (self.state.webhook is None or self.state.webhook.id != webhook.id):
            return Delegation(None, again=True)  # the context was made for another webhook
        role = webhook.model_call
        ask = Ask(
            kind=kind,
            step=None,
            webhook=webhook,
            timeout=task.timeout if task is not None else role.timeout if role else DEFAULT_TIMEOUT,
            request=TaskRequest(contract=self.context),
            task=task,
        )
        (placed,) = await self.state.desk.place(uow, document, node, [ask], now)
        if placed.status.settled:  # the request could not be made: the node reads why
            return Delegation(None, again=True)
        return Delegation(placed.deadline)
