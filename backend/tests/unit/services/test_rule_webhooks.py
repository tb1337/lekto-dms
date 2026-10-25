"""Rules that send through webhooks (`SendWebhook`): on arrival once the document is filed,
after a change at once, applied to existing documents per document; and who may send what."""

import pytest

from lekto.core.domain.documents import DocumentChanges
from lekto.core.domain.errors import NotFoundError, ValidationError
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.pipeline import RULES, Lane, Node
from lekto.core.domain.reasons import ReasonCode
from lekto.core.domain.rules import Action, ForceReview, SendWebhook, Trigger
from lekto.core.domain.users import User
from lekto.core.domain.webhooks import RULE_SEND, Webhook
from lekto.core.services.rules.running import SENDS, SENDS_REFUSED
from lekto.core.services.webhooks import DELIVER_JOB
from tests import builders
from tests.unit.services.rules_support import (
    RuleWorld,
    add_tags,
    channel_api,
    definition,
    has_tag,
    rule_world,
)
from tests.unit.services.support import World

URL = "http://ha.lan:8123/api/webhook/lekto"


async def hook(world: World, owner: User, name: str = "HA") -> Webhook:
    created = await world.webhooks.create(owner.id, name=name, url=URL, event_types=[])
    return created.webhook


def sent(world: World) -> list[JsonObject]:
    """The payloads of the queued requests rules send."""
    return [
        job.payload
        for job in world.database.jobs.values()
        if job.kind == DELIVER_JOB and job.payload.get("type") == RULE_SEND
    ]


async def notifying(r: RuleWorld, owner: User, webhook: Webhook, *more: Action) -> None:
    """A rule of the owner's personal space that sends every upload through `webhook`."""
    await r.personal_rule(
        owner, definition("Notify", channel_api(), *more, SendWebhook(webhook.id))
    )


async def test_a_green_document_sends_when_it_is_filed(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    webhook = await hook(world, owner)
    await notifying(r, owner, webhook)
    document = await r.arrive(owner)
    assert document.lane is Lane.GREEN
    (payload,) = sent(world)
    assert payload["webhook_id"] == str(webhook.id)
    assert payload["document_id"] == str(document.id)
    rule = payload["rule"]
    assert isinstance(rule, dict) and rule["name"] == "Notify"
    (entry,) = [item for item in await r.log(document) if item.node is Node.FILE]
    assert entry.result.output[SENDS] != []


async def test_a_yellow_document_sends_once_confirmed_and_only_once(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    webhook = await hook(world, owner)
    await notifying(r, owner, webhook, ForceReview("look first"))
    document = await r.arrive(owner)
    assert document.lane is Lane.YELLOW
    assert sent(world) == []  # waiting in the inbox: nothing goes yet
    pipeline = r.pipeline()
    await pipeline.confirm(owner.id, document.id, DocumentChanges(), accept_suggestions=True)
    await world.drain(pipeline)
    assert (await r.stored(document)).lane is Lane.GREEN
    assert [payload["document_id"] for payload in sent(world)] == [str(document.id)]


async def test_a_webhook_whose_owner_cannot_read_the_document_turns_it_yellow(
    world: World,
) -> None:
    """A global rule of an admin, whose webhook reports only what the admin reaches as a user:
    another user's upload waits for a person, and after their click it is only reported."""
    r = await rule_world(world)
    owner = await world.user()
    webhook = await hook(world, r.admin)
    await r.global_rule(definition("Everything", channel_api(), SendWebhook(webhook.id)))
    document = await r.arrive(owner)
    assert document.lane is Lane.YELLOW
    (entry,) = await r.rule_entries(document, RULES)
    assert [reason.code for reason in entry.result.reasons] == [ReasonCode.RULE_WEBHOOK_UNREADABLE]
    pipeline = r.pipeline()
    await pipeline.confirm(owner.id, document.id, DocumentChanges(), accept_suggestions=True)
    await world.drain(pipeline)
    assert (await r.stored(document)).lane is Lane.GREEN
    assert sent(world) == []
    latest = (await r.rule_entries(document, RULES))[-1]
    assert latest.result.output[SENDS_REFUSED] != []


async def test_a_rule_sends_only_through_webhooks_of_whoever_saves_it(world: World) -> None:
    r = await rule_world(world)
    owner, other = await world.user(), await world.user()
    theirs = await hook(world, other)
    with pytest.raises(NotFoundError):
        await notifying(r, owner, theirs)
    mine = await hook(world, owner)
    with pytest.raises(ValidationError, match="twice"):
        await r.personal_rule(
            owner,
            definition("Twice", channel_api(), SendWebhook(mine.id), SendWebhook(mine.id)),
        )


async def test_deleting_the_webhook_disables_its_rules(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    webhook = await hook(world, owner)
    await notifying(r, owner, webhook)
    await world.webhooks.delete(owner.id, webhook.id)
    (rule,) = await r.rules.list_rules(owner.id)
    assert not rule.enabled
    assert rule.disabled_reason is not None
    assert rule.disabled_reason.code is ReasonCode.RULE_DISABLED_DELETED


async def test_a_change_rule_sends_once_the_change_is_stored(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    webhook = await hook(world, owner)
    tag = await r.tag("pay")
    await r.personal_rule(
        owner,
        definition("Pay", has_tag(tag.id), SendWebhook(webhook.id), triggers=(Trigger.CHANGE,)),
    )
    document = await r.arrive(owner)
    assert sent(world) == []
    preview = await r.documents.change_metadata(
        owner.id, document.id, DocumentChanges(tag_ids=frozenset({tag.id})), dry_run=True
    )
    assert preview.rules is not None and [send.webhook_id for send in preview.rules.sends] == [
        webhook.id
    ]
    assert sent(world) == []  # a preview sends nothing
    await r.documents.change_metadata(
        owner.id, document.id, DocumentChanges(tag_ids=frozenset({tag.id}))
    )
    assert [payload["document_id"] for payload in sent(world)] == [str(document.id)]


async def test_applying_to_existing_documents_sends_per_document(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    webhook = await hook(world, owner)
    tag = await r.tag("old")
    first, second = await r.arrive(owner), await r.arrive(owner)
    rule = await r.personal_rule(
        owner, definition("Backfill", channel_api(), add_tags(tag.id), SendWebhook(webhook.id))
    )
    world.database.jobs.clear()
    preview = await r.applications.preview(owner.id, rule.id)
    assert {
        item.document.id: [send.webhook_id for send in item.sends] for item in preview.items
    } == {
        first.id: [webhook.id],
        second.id: [webhook.id],
    }
    assert sent(world) == []
    await r.applications.start(
        owner.id, rule.id, version=1, documents=[first.id, second.id], accept_conflicts=[]
    )
    await builders.drain(r.applications)
    assert sorted(str(payload["document_id"]) for payload in sent(world)) == sorted(
        [str(first.id), str(second.id)]
    )


async def test_an_admin_s_global_rule_sends_for_documents_the_admin_reaches(world: World) -> None:
    r = await rule_world(world)
    webhook = await hook(world, r.admin)
    await r.global_rule(definition("Mine", channel_api(), SendWebhook(webhook.id)))
    document = await r.arrive(r.admin)
    assert document.lane is Lane.GREEN
    assert [payload["document_id"] for payload in sent(world)] == [str(document.id)]
