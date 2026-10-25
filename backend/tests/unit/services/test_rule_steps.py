"""Rules whose steps ask a webhook and check its answer (Tobi, 25.10.2026): the node waits for
the answer ("running externally"), the steps after it see `steps.<name>`, and an answer that
does not come does what the step says."""

import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest

from lekto.core.domain.documents import Document, DocumentChanges
from lekto.core.domain.errors import InvalidTransitionError, NotFoundError, ValidationError
from lekto.core.domain.fields import FieldDefinition, FieldType
from lekto.core.domain.ids import TaskId
from lekto.core.domain.pipeline import RULES, Lane, Node, NodeStatus, Outcome
from lekto.core.domain.reasons import ReasonCode
from lekto.core.domain.rules import (
    Action,
    AskWebhook,
    Condition,
    ConditionField,
    ForceReview,
    Group,
    Missing,
    Operator,
    RuleScope,
    SetField,
    StepCondition,
    Trigger,
)
from lekto.core.domain.users import User
from lekto.core.domain.webhooks import BodyFormat, Webhook
from lekto.core.ports.webhook_sender import WebhookRequest
from lekto.core.services.pipeline import PipelineService
from lekto.core.services.rules.management import RuleService
from lekto.core.services.rules.running import STEPS_LOG
from tests import builders
from tests.unit.services.rules_support import (
    RuleWorld,
    add_tags,
    channel_api,
    definition,
    incoming_pdf,
    rule_world,
)
from tests.unit.services.support import World

URL = "http://node-red.lan:1880/lekto"
MINUTE = timedelta(minutes=1)
INGEST = (Trigger.INGEST,)


def paid(name: str = "flow") -> StepCondition:
    """The answer says it is paid."""
    condition = Condition(
        field=ConditionField.STEP, op=Operator.IS, value=True, path=f"{name}.paid"
    )
    return StepCondition(Group(mode="all", items=(condition,)))


@dataclass
class Steps:
    """A world with an owner, their webhook to a Node-RED flow and a text field `beleg`."""

    r: RuleWorld
    owner: User
    webhook: Webhook
    beleg: FieldDefinition
    pipeline: PipelineService

    @property
    def world(self) -> World:
        return self.r.world

    async def rule(self, *steps: Action, name: str = "Paid") -> None:
        await self.r.personal_rule(
            self.owner, definition(name, channel_api(), *steps, triggers=INGEST)
        )

    async def arrive(self) -> Document:
        received = await self.pipeline.receive(self.owner.id, incoming_pdf(), filename="a.pdf")
        await self.run()
        return await self.r.stored(received)

    async def run(self) -> None:
        delivery = self.world.webhook_delivery()
        while (
            await self.pipeline.run_next_job()
            or await delivery.run_next_job()
            or await self.world.tasks.run_next_job()
        ):
            pass

    def asked(self) -> list[WebhookRequest]:
        return [request for request in self.world.sender.requests if request.url == URL]

    async def answer(self, request: WebhookRequest, answer: object) -> None:
        body = json.dumps({"status": "ok", "producer": "node-red", "answer": answer})
        task = TaskId(UUID(request.headers["lekto-task-id"]))
        receipt = await self.world.tasks.answer(
            task, request.headers["lekto-task-token"], body.encode()
        )
        assert receipt.problem is None
        await self.run()


async def steps_world(world: World, *, body: BodyFormat = BodyFormat.FULL) -> Steps:
    r = await rule_world(world)
    owner = await world.user()
    created = await world.webhooks.create(
        owner.id, name="Node-RED", url=URL, event_types=[], signed=False, body=body
    )
    beleg = await world.master_data.create_field(r.admin.id, "Beleg", FieldType.TEXT)
    pipeline = builders.skip_classification(r.pipeline())
    return Steps(r, owner, created.webhook, beleg, pipeline)


async def test_a_rule_asks_a_flow_and_sets_a_tag_and_a_field_from_its_answer(
    world: World,
) -> None:
    s = await steps_world(world)
    tag = await s.r.tag("bezahlt")
    await s.rule(
        AskWebhook("flow", s.webhook.id),
        paid(),
        add_tags(tag.id),
        SetField(s.beleg.id, "{{ steps.flow.beleg }}"),
    )
    document = await s.arrive()
    rules = document.processing.nodes[Node.APPLY_RULES]
    assert rules.status is NodeStatus.DELEGATED and rules.deadline is not None
    (request,) = s.asked()
    body = json.loads(request.body)
    assert body["type"] == "rule.ask" and body["rule"]["name"] == "Paid"
    assert body["document"]["id"] == str(document.id)

    await s.answer(request, {"paid": True, "beleg": "B-4711"})
    document = await s.r.stored(document)
    assert document.lane is Lane.GREEN
    assert tag.id in document.tag_ids
    assert document.fields[s.beleg.id] == "B-4711"
    (entry,) = await s.r.rule_entries(document, RULES)
    (logged,) = json.loads(json.dumps(entry.result.output[STEPS_LOG]))
    assert [step["type"] for step in logged["steps"]] == ["ask_webhook", "condition"]
    assert logged["steps"][0]["answer"] == {"paid": True, "beleg": "B-4711"}
    assert logged["steps"][0]["producer"] == "node-red"


async def test_a_condition_that_does_not_hold_ends_the_rule_there(world: World) -> None:
    s = await steps_world(world)
    before, after = await s.r.tag("asked"), await s.r.tag("bezahlt")
    await s.rule(AskWebhook("flow", s.webhook.id), add_tags(before.id), paid(), add_tags(after.id))
    document = await s.arrive()
    await s.answer(s.asked()[0], {"paid": False})
    document = await s.r.stored(document)
    assert document.lane is Lane.GREEN
    assert before.id in document.tag_ids and after.id not in document.tag_ids


async def test_the_answer_s_document_shows_the_rule_s_steps_before(world: World) -> None:
    s = await steps_world(world)
    tag = await s.r.tag("first")
    await s.rule(add_tags(tag.id), AskWebhook("flow", s.webhook.id))
    await s.arrive()
    (request,) = s.asked()
    names = [item["name"] for item in json.loads(request.body)["document"]["tags"]]
    assert names == ["first"]  # the rule's own copy: not applied before the answer


@pytest.mark.parametrize(
    ("missing", "lane", "tagged"),
    [
        (Missing.RED, Lane.RED, set()),
        (Missing.YELLOW, Lane.YELLOW, {"before"}),
        (Missing.CONTINUE, Lane.GREEN, {"before", "after"}),
    ],
)
async def test_without_an_answer_the_step_does_what_it_says(
    world: World, missing: Missing, lane: Lane, tagged: set[str]
) -> None:
    s = await steps_world(world)
    before, after = await s.r.tag("before"), await s.r.tag("after")
    other = await s.r.tag("other")
    await s.rule(
        add_tags(before.id), AskWebhook("flow", s.webhook.id, missing=missing), add_tags(after.id)
    )
    await s.rule(add_tags(other.id), name="Other")
    document = await s.arrive()
    world.clock.advance(5 * MINUTE)
    await s.run()
    document = await s.r.stored(document)
    assert document.lane is lane
    names = {tag.name for tag in [before, after, other] if tag.id in document.tag_ids}
    expected = tagged | ({"other"} if missing is not Missing.RED else set())
    assert names == expected
    if missing is not Missing.CONTINUE:
        node = Node.APPLY_RULES
        assert document.processing.outcome(node) in (Outcome.FAILED, Outcome.UNCERTAIN)


async def test_two_rules_ask_side_by_side_and_are_combined_when_both_answered(
    world: World,
) -> None:
    s = await steps_world(world)
    one, two = await s.r.tag("one"), await s.r.tag("two")
    await s.rule(AskWebhook("a", s.webhook.id), add_tags(one.id), name="One")
    await s.rule(AskWebhook("b", s.webhook.id), add_tags(two.id), name="Two")
    document = await s.arrive()
    first, second = s.asked()
    await s.answer(first, {})
    stored = await s.r.stored(document)
    assert stored.processing.nodes[Node.APPLY_RULES].status is NodeStatus.DELEGATED
    assert stored.tag_ids == document.tag_ids  # nothing applied while one waits
    await s.answer(second, {})
    stored = await s.r.stored(document)
    assert {one.id, two.id} <= set(stored.tag_ids) and stored.lane is Lane.GREEN


async def test_confirming_without_a_change_does_not_ask_again(world: World) -> None:
    s = await steps_world(world)
    tag = await s.r.tag("bezahlt")
    await s.rule(AskWebhook("flow", s.webhook.id), paid(), add_tags(tag.id), ForceReview("look"))
    document = await s.arrive()
    await s.answer(s.asked()[0], {"paid": True})
    document = await s.r.stored(document)
    assert document.lane is Lane.YELLOW
    await s.pipeline.confirm(s.owner.id, document.id, DocumentChanges(), accept_suggestions=True)
    await s.run()
    document = await s.r.stored(document)
    assert document.lane is Lane.GREEN and tag.id in document.tag_ids
    assert len(s.asked()) == 1


async def test_confirming_with_a_change_asks_again(world: World) -> None:
    s = await steps_world(world)
    await s.rule(AskWebhook("flow", s.webhook.id), ForceReview("look"))
    document = await s.arrive()
    await s.answer(s.asked()[0], {})
    document = await s.r.stored(document)
    await s.pipeline.confirm(
        s.owner.id, document.id, DocumentChanges(title="Strom März"), accept_suggestions=True
    )
    await s.run()
    assert len(s.asked()) == 2
    document = await s.r.stored(document)
    assert document.processing.nodes[Node.APPLY_RULES].status is NodeStatus.DELEGATED


async def test_after_a_confirmation_a_missing_answer_is_only_reported(world: World) -> None:
    s = await steps_world(world)
    tag = await s.r.tag("after")
    await s.rule(AskWebhook("flow", s.webhook.id), add_tags(tag.id), ForceReview("look"))
    document = await s.arrive()
    await s.answer(s.asked()[0], {})
    document = await s.r.stored(document)
    await s.pipeline.confirm(
        s.owner.id, document.id, DocumentChanges(title="Neu"), accept_suggestions=True
    )
    await s.run()
    world.clock.advance(5 * MINUTE)
    await s.run()
    document = await s.r.stored(document)
    assert document.lane is Lane.GREEN and tag.id in document.tag_ids


async def test_a_rule_asks_only_through_its_author_s_webhook(world: World) -> None:
    s = await steps_world(world)
    other = await world.user()
    theirs = await world.webhooks.create(other.id, name="x", url=URL, event_types=[])
    with pytest.raises(NotFoundError):
        await s.rule(AskWebhook("flow", theirs.webhook.id))


async def test_a_webhook_whose_owner_cannot_read_the_document_holds_it(world: World) -> None:
    s = await steps_world(world)
    admin_hook = await world.webhooks.create(
        s.r.admin.id, name="Admin", url=URL, event_types=[], signed=False
    )
    await s.r.global_rule(
        definition(
            "Everything", channel_api(), AskWebhook("flow", admin_hook.webhook.id), triggers=INGEST
        )
    )
    document = await s.arrive()
    assert document.lane is Lane.YELLOW and s.asked() == []
    (entry,) = await s.r.rule_entries(document, RULES)
    assert [reason.code for reason in entry.result.reasons] == [ReasonCode.RULE_WEBHOOK_UNREADABLE]


async def test_steps_refer_only_to_steps_before_and_need_the_public_url(world: World) -> None:
    s = await steps_world(world)
    with pytest.raises(ValidationError, match=r"steps\.<name> of a step before"):
        await s.rule(
            SetField(s.beleg.id, "{{ steps.flow.beleg }}"), AskWebhook("flow", s.webhook.id)
        )
    without = RuleService(world.uow, world.clock, builders.TEMPLATES, s.r.matcher)
    with pytest.raises(ValidationError, match="LEKTO_PUBLIC_URL"):
        await without.create(
            s.owner.id,
            RuleScope.SPACE,
            definition("x", channel_api(), AskWebhook("flow", s.webhook.id), triggers=INGEST),
        )


async def test_a_rule_that_asks_is_not_applied_to_existing_documents(world: World) -> None:
    s = await steps_world(world)
    await s.rule(AskWebhook("flow", s.webhook.id))
    (rule,) = await s.r.rules.list_rules(s.owner.id)
    with pytest.raises(InvalidTransitionError):
        await s.r.applications.preview(s.owner.id, rule.id)


async def test_moved_by_hand_a_rule_does_not_ask_and_ends_there(world: World) -> None:
    s = await steps_world(world)
    before, after = await s.r.tag("before"), await s.r.tag("after")
    archive = await world.spaces.create(s.owner.id, "Archiv")
    await s.r.space_rule(
        s.owner,
        archive.id,
        definition(
            "Archive",
            channel_api(),
            add_tags(before.id),
            AskWebhook("flow", s.webhook.id),
            add_tags(after.id),
            triggers=INGEST,
        ),
    )
    document = await s.arrive()
    await s.r.documents.move(s.owner.id, document.id, archive.id)
    await s.run()
    document = await s.r.stored(document)
    assert before.id in document.tag_ids and after.id not in document.tag_ids
    assert s.asked() == []
