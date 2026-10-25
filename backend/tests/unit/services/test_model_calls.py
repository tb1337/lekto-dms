"""Model calls a webhook takes over: `signal_llm` and `fields` send the context as a task and
wait; the answer counts as the model's and is checked as it is; without one the document is
red. The files of the document go by signed links."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from lekto.adapters.inbound.rest.schemas.outgoing import ExtractContext, ProposeContext
from lekto.core.domain import media_types
from lekto.core.domain.documents import Document, DocumentChanges
from lekto.core.domain.errors import AuthenticationError, ConflictError, NotFoundError
from lekto.core.domain.exchanges import exchanges_from_json
from lekto.core.domain.fields import Money
from lekto.core.domain.ids import DocumentTypeId, TaskId
from lekto.core.domain.json_value import JsonObject, JsonValue
from lekto.core.domain.pipeline import Lane, Node, NodeResult, NodeStatus, Outcome
from lekto.core.domain.reasons import ReasonCode
from lekto.core.domain.tasks import TaskKind, TaskStatus
from lekto.core.domain.users import Role, User
from lekto.core.domain.webhooks import ModelCallKind, ModelCallRole, Webhook
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.ports.webhook_sender import WebhookRequest
from lekto.core.services.classification.external import (
    EXTERNAL,
    ExternalCall,
    model_call_state,
)
from lekto.core.services.classification.nodes import FieldsNode, LlmSignal
from lekto.core.services.nodes import PagesResult
from lekto.core.services.objects import exchanges_key, page_key, structure_key, text_key
from lekto.core.services.pipeline import MetadataResult, PipelineService
from lekto.core.services.tasks.files import file_link
from lekto.core.services.tasks.settling import Delegation
from tests import builders
from tests.builders import OK
from tests.unit.services.rules_support import incoming_pdf
from tests.unit.services.support import World
from tests.unit.services.test_classification import FIELDS, INVOICE, Seeded, proposal, seed

URL = "http://agent.lan:8080/lekto"
STRUCTURE = b'{"pages": []}'


@dataclass
class Parsed:
    """Reads the invoice's text and its structure."""

    world: World

    async def run(self, document: Document) -> NodeResult:
        store = self.world.object_store
        await store.put(text_key(document.id), INVOICE.encode(), content_type=media_types.TEXT)
        await store.put(structure_key(document.id), STRUCTURE, content_type=media_types.JSON)
        return OK


@dataclass
class Rendered:
    """Two page images."""

    world: World

    async def run(self, document: Document) -> PagesResult:
        for number in (1, 2):
            image = f"page {number}".encode()
            store = self.world.object_store
            await store.put(page_key(document.id, number), image, content_type=media_types.WEBP)
        return PagesResult(OK, 2)


@dataclass
class Typed:
    """The judge: the document is of `kind`."""

    kind: DocumentTypeId

    async def run(self, document: Document) -> MetadataResult:
        return MetadataResult(OK, DocumentChanges(document_type_id=self.kind))


@dataclass
class Calls:
    """A world whose admin's webhook serves as both model calls."""

    world: World
    admin: User
    seeded: Seeded
    webhooks: dict[ModelCallKind, Webhook]
    pipeline: PipelineService

    async def arrive(self) -> Document:
        received = await self.pipeline.receive(self.admin.id, incoming_pdf(), filename="a.pdf")
        await self.run()
        return await self.stored(received)

    async def run(self) -> None:
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

    def sent(self) -> list[WebhookRequest]:
        return [request for request in self.world.sender.requests if request.url == URL]

    async def answer(self, request: WebhookRequest, envelope: object) -> str | None:
        """Answer the request; why it was not taken, if it was not."""
        receipt = await self.world.tasks.answer(
            TaskId(UUID(request.headers["lekto-task-id"])),
            request.headers["lekto-task-token"],
            json.dumps(envelope).encode(),
        )
        await self.run()
        return receipt.problem

    async def node(self, document: Document, node: Node) -> NodeResult:
        async with self.world.uow() as uow:
            log = await uow.processing_log.list_for(document.id)
        return [entry for entry in log if entry.node is node][-1].result


async def calls(world: World, *kinds: ModelCallKind) -> Calls:
    admin = await world.user(role=Role.ADMIN)
    seeded = await seed(world)
    webhooks = {
        kind: (
            await world.webhooks.create(
                admin.id,
                name=f"Agent {kind}",
                url=URL,
                event_types=[],
                signed=False,
                model_call=ModelCallRole(kind, timedelta(minutes=10)),
            )
        ).webhook
        for kind in kinds or tuple(ModelCallKind)
    }
    desk, store, policy = world.desk(), world.object_store, builders.CLASSIFICATION
    pipeline = world.pipeline(
        {
            Node.PARSE: Parsed(world),
            Node.PAGES: Rendered(world),
            Node.SIGNAL_LLM: LlmSignal(world.uow, store, None, world.clock, policy, desk=desk),
            Node.JUDGE: Typed(seeded.types["Rechnung"].id),
            Node.FIELDS: FieldsNode(world.uow, store, None, world.clock, policy, desk=desk),
        }
    )
    return Calls(world, admin, seeded, webhooks, pipeline)


def body(request: WebhookRequest) -> dict[str, Any]:
    data = json.loads(request.body)
    assert isinstance(data, dict)
    return data


def ok(answer: JsonValue, producer: str = "agent 1") -> JsonObject:
    return {"status": "ok", "producer": producer, "answer": answer}


def extracted(context: dict[str, Any]) -> JsonObject:
    """The values the extract request asks for, by the keys it sent."""
    keys = {field["name"]: key for key, field in context["fields"].items()}
    values: dict[str, Any] = {
        "Fällig am": {"value": "2026-04-15", "evidence": "Zahlbar bis 15.04.2026."},
        "Rechnungsbetrag": {
            "value": {"amount": "84.20", "currency": "EUR"},
            "evidence": "Gesamtbetrag | 84,20 €",
        },
        "Rechnungsnummer": {"value": "R-2026-0815", "evidence": "Rechnung Nr. R-2026-0815"},
    }
    return {"fields": {keys[name]: value | {"label": None} for name, value in values.items()}}


async def test_a_webhook_proposes_and_extracts_and_the_lanes_come_as_with_the_model(
    world: World,
) -> None:
    f = await calls(world)
    document = await f.arrive()
    assert document.processing.nodes[Node.SIGNAL_LLM].status is NodeStatus.DELEGATED
    (request,) = f.sent()
    context = body(request)
    ProposeContext.model_validate(context)  # as the contract describes it
    assert context["contract"] == "propose-ext-1"
    task = context["task"]
    assert (task["kind"], task["document_id"], task["run"]) == (
        "external.propose",
        str(document.id),
        1,
    )
    assert task["token"] == request.headers["lekto-task-token"]
    assert task["deadline"] == "2026-10-06T12:10:00Z"
    sent = context["document"]
    assert (sent["filename"], sent["pages"], sent["text"]) == ("a.pdf", 2, INVOICE)
    assert len(sent["page_images"]) == 2 and "/files/content.json?" in sent["structure"]
    assert {item["name"] for item in context["contacts"]} >= {"Stadtwerke Musterstadt GmbH"}
    assert [item["name"] for item in context["document_types"]] == ["Rechnung", "Vertrag"]
    assert context["fields"]["a3"] == {
        "name": "Rechnungsbetrag",
        "type": "amount",
        "form": ("amount with currency"),
    }
    assert context["general_fields"] == ["a1"]
    schema = context["answer_schema"]
    assert "never the sender" in schema["properties"]["recipient"]["description"]
    assert (
        "character by character"
        in (schema["properties"]["fields"]["items"]["properties"]["evidence"]["description"])
    )

    # The proposal names another type than the judge decides: the fields are read anew.
    answer = proposal(document_type="Vertrag", fields=FIELDS)
    assert await f.answer(request, ok(answer)) is None
    llm = await f.node(document, Node.SIGNAL_LLM)
    assert (llm.outcome, llm.model_version) == (Outcome.OK, "agent 1")
    assert llm.input["contract"] == "propose-ext-1" and llm.input["webhook"] == "Agent propose"
    output: Any = llm.output
    assert output["proposal"]["document_type"] == "Vertrag"
    document = await f.stored(document)
    assert document.processing.nodes[Node.FIELDS].status is NodeStatus.DELEGATED
    asked = f.sent()[1]
    extract = body(asked)
    ExtractContext.model_validate(extract)
    assert (extract["contract"], extract["task"]["kind"]) == ("extract-ext-1", "external.extract")
    assert extract["document_type"] == "Rechnung"
    assert sorted(field["name"] for field in extract["fields"].values()) == [
        "Fällig am",
        "Rechnungsbetrag",
        "Rechnungsnummer",
    ]
    assert "fields" in extract["answer_schema"]["required"]

    assert await f.answer(asked, ok(extracted(extract), producer="agent 2")) is None
    document = await f.stored(document)
    fields = await f.node(document, Node.FIELDS)
    assert (fields.outcome, fields.model_version) == (Outcome.OK, "agent 2")
    assert document.lane is Lane.GREEN
    amount = f.seeded.fields["Rechnungsbetrag"]
    assert document.fields[amount.id] == Money(Decimal("84.20"), "EUR")

    # The context, without the task and its links, and the answer lie beside the document.
    kept = json.loads(await world.object_store.get(exchanges_key(document.id, Node.SIGNAL_LLM)))
    (run,) = exchanges_from_json(kept)
    (call,) = run.calls
    assert json.loads(call.user)["contract"] == "propose-ext-1"
    assert "task" not in json.loads(call.user) and call.model == "agent 1"
    assert json.loads(call.answer) == answer


async def test_the_links_give_the_files_until_the_deadline(world: World) -> None:
    f = await calls(world, ModelCallKind.PROPOSE)
    document = await f.arrive()
    (request,) = f.sent()
    sent = body(request)["document"]

    async def fetch(link: str, **changed: str) -> Any:
        parts = urlsplit(link)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()} | changed
        id, name = parts.path.split("/tasks/", 1)[1].split("/files/", 1)
        return await world.tasks.file(
            TaskId(UUID(id)), name, int(query["expires"]), query["signature"]
        )

    structure = await fetch(sent["structure"])
    assert (structure.data, structure.media_type) == (STRUCTURE, "application/json")
    page = await fetch(sent["page_images"][1])
    assert (page.data, page.media_type) == (b"page 2", "image/webp")
    expires = str(int(sent["structure"].split("expires=")[1].split("&")[0]) + 60)
    with pytest.raises(AuthenticationError):
        await fetch(sent["structure"], expires=expires)  # the end is signed too
    with pytest.raises(AuthenticationError):
        await fetch(sent["structure"].replace("content.json", "pages/1.webp"))
    await world.documents.delete(f.admin.id, document.id)
    with pytest.raises(ConflictError):
        await fetch(sent["page_images"][0])
    world.clock.advance(timedelta(minutes=10))
    with pytest.raises(AuthenticationError):
        await fetch(sent["structure"])


async def test_a_file_the_document_lacks_is_not_found(world: World) -> None:
    f = await calls(world, ModelCallKind.PROPOSE)
    await f.arrive()
    (request,) = f.sent()
    link = urlsplit(body(request)["document"]["structure"])
    id = TaskId(UUID(link.path.split("/tasks/", 1)[1].split("/files/", 1)[0]))
    async with world.uow() as uow:
        task = await uow.tasks.get(id)
    assert task.deadline is not None
    # Signed as Lekto signs, for a page the document does not have.
    beyond = urlsplit(file_link("https://x", world.cipher, task, "pages/3.webp", task.deadline))
    query = {key: values[0] for key, values in parse_qs(beyond.query).items()}
    with pytest.raises(NotFoundError):
        await world.tasks.file(id, "pages/3.webp", int(query["expires"]), query["signature"])


async def test_an_answer_that_does_not_fit_is_refused_and_the_document_is_red(
    world: World,
) -> None:
    f = await calls(world, ModelCallKind.PROPOSE)
    document = await f.arrive()
    (request,) = f.sent()
    unfit = proposal()
    del unfit["title"]
    assert await f.answer(request, ok(unfit)) == "the answer: missing title"
    document = await f.stored(document)
    assert document.lane is Lane.RED
    result = await f.node(document, Node.SIGNAL_LLM)
    assert result.outcome is Outcome.FAILED
    assert result.reasons[0].code is ReasonCode.TASK_INVALID
    assert result.model_version == "agent 1"


@pytest.mark.parametrize("error", [True, False])
async def test_an_error_or_no_answer_makes_the_document_red(world: World, error: bool) -> None:
    f = await calls(world, ModelCallKind.PROPOSE)
    document = await f.arrive()
    (request,) = f.sent()
    if error:
        await f.answer(request, {"status": "error", "reason": "the model is down"})
    else:
        world.clock.advance(timedelta(minutes=10))
        await f.run()
    document = await f.stored(document)
    assert document.lane is Lane.RED
    result = await f.node(document, Node.SIGNAL_LLM)
    code = ReasonCode.TASK_ERROR if error else ReasonCode.TASK_NO_ANSWER
    assert (result.outcome, result.reasons[0].code) == (Outcome.FAILED, code)
    assert result.model_version == EXTERNAL


async def test_without_a_serving_webhook_the_signal_abstains_as_before(world: World) -> None:
    f = await calls(world, ModelCallKind.PROPOSE)
    webhook = f.webhooks[ModelCallKind.PROPOSE]
    await world.webhooks.update(f.admin.id, webhook.id, active=False)
    document = await f.arrive()
    assert f.sent() == []
    result = await f.node(document, Node.SIGNAL_LLM)
    assert result.reasons == () and "abstained" in result.output


async def test_a_task_that_ends_meanwhile_lets_the_node_run_anew(world: World) -> None:
    f = await calls(world, ModelCallKind.PROPOSE)
    document = await f.arrive()
    state = await model_call_state(world.uow, world.desk(), document, TaskKind.PROPOSE)
    assert state is not None and state.sent
    async with world.uow() as uow:
        assert state.task is not None
        task = await uow.tasks.get(state.task.id)
        task.answered(proposal(), None, world.clock.now())
        await uow.tasks.update(task)
        await uow.commit()
    async with world.uow() as uow:
        stored = await uow.documents.get(document.id)
        assert await ExternalCall(state, None).apply(uow, stored, world.clock.now()) == (
            Delegation(None, again=True)
        )


@dataclass(frozen=True)
class Anew:
    async def apply(
        self, uow: UnitOfWork, document: Document, now: datetime
    ) -> NodeResult | Delegation:
        return Delegation(None, again=True)


@dataclass
class Again:
    """A node whose first run finds that its task ended meanwhile."""

    runs: int = 0

    async def run(self, document: Document) -> NodeResult | Anew:
        self.runs += 1
        return Anew() if self.runs == 1 else OK


async def test_the_pipeline_runs_a_node_anew_at_once_when_asked(world: World) -> None:
    owner = await world.user()
    again = Again()
    pipeline = builders.skip_classification(world.pipeline({Node.SIGNAL_LLM: again}))
    received = await pipeline.receive(owner.id, incoming_pdf(), filename="a.pdf")
    while await pipeline.run_next_job():
        pass
    async with world.uow() as uow:
        document = await uow.documents.get(received.id)
    assert again.runs == 2
    assert document.processing.nodes[Node.SIGNAL_LLM].outcome is Outcome.OK
    assert document.lane is Lane.GREEN


async def test_a_queued_task_whose_webhook_went_fails(world: World) -> None:
    f = await calls(world, ModelCallKind.PROPOSE)
    webhook = f.webhooks[ModelCallKind.PROPOSE]
    await world.webhooks.update(f.admin.id, webhook.id, max_open_tasks=1)
    first = await f.arrive()
    second = await f.arrive()
    async with world.uow() as uow:
        (queued,) = await uow.tasks.list_for_run(second.id, Node.SIGNAL_LLM, 1)
    assert queued.status is TaskStatus.QUEUED and len(f.sent()) == 1
    await world.webhooks.delete(f.admin.id, webhook.id)
    await f.run()
    assert (await f.stored(second)).lane is Lane.RED
    assert (await f.stored(first)).processing.nodes[Node.SIGNAL_LLM].status is (
        NodeStatus.DELEGATED
    )
