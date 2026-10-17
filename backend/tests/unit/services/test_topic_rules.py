"""Rules on topics: the condition, the action "set topic", and what they leave."""

import pytest

from papiq.core.domain.documents import DocumentChanges
from papiq.core.domain.errors import ConflictError, NotFoundError, ValidationError
from papiq.core.domain.ids import TagId, new_id
from papiq.core.domain.master_data import TagScope
from papiq.core.domain.pipeline import RULES, Lane
from papiq.core.domain.rules import Condition, ConditionField, Operator, SetSpace, SetTopic
from papiq.core.domain.spaces import ShareLevel
from tests.unit.services.conftest import World
from tests.unit.services.rules_support import (
    Classifies,
    contact_is,
    definition,
    notes,
    rule_world,
)


def topic_is(topic: TagId) -> Condition:
    return Condition(field=ConditionField.TOPIC, op=Operator.IS, value=str(topic))


async def test_a_rule_sets_a_topic_the_contact_enables(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    service = world.master_data
    work = await service.create_tag(r.admin.id, "Arbeit", scope=TagScope.TOPIC)
    health = await service.create_tag(r.admin.id, "Krankenversicherung", scope=TagScope.TOPIC)
    nord = await service.create_contact(r.admin.id, "Nord", topic_ids=[work.id])
    await r.user_rule(owner, definition("work", contact_is(nord.id), SetTopic(work.id)))
    await r.user_rule(owner, definition("health", contact_is(nord.id), SetTopic(health.id)))
    document = await r.arrive(owner, classify=Classifies(contact=nord.id))
    assert (document.topic_id, document.lane) == (work.id, Lane.GREEN)
    (entry,) = await r.rule_entries(document, RULES)
    assert ("topic", "skipped") in notes(entry.result.output)  # Nord does not enable health


async def test_a_rule_on_a_topic_the_model_set_files_into_a_shared_space_only_confirmed(
    world: World,
) -> None:
    r = await rule_world(world)
    owner, partner = await world.user(), await world.user()
    service = world.master_data
    work = await service.create_tag(r.admin.id, "Arbeit", scope=TagScope.TOPIC)
    nord = await service.create_contact(r.admin.id, "Nord", topic_ids=[work.id])
    shared = await world.spaces.create(owner.id, "Shared")
    await world.spaces.share(owner.id, shared.id, partner.id, ShareLevel.READ)
    await r.user_rule(owner, definition("file", topic_is(work.id), SetSpace(shared.id)))
    document = await r.arrive(owner, classify=Classifies(contact=nord.id, topic=work.id))
    assert (document.topic_id, document.space_id, document.lane) == (
        work.id,
        (await world.default_space(owner)).id,
        Lane.YELLOW,
    )
    (entry,) = await r.rule_entries(document, RULES)
    assert ("space", "refused") in notes(entry.result.output)


async def test_rules_refer_to_topics_where_a_topic_belongs(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    service = world.master_data
    work = await service.create_tag(r.admin.id, "Arbeit", scope=TagScope.TOPIC)
    tag = await service.create_tag(r.admin.id, "Bezahlt")
    nord = await service.create_contact(r.admin.id, "Nord")
    with pytest.raises(ValidationError, match="topic"):
        await r.user_rule(owner, definition("x", contact_is(nord.id), SetTopic(tag.id)))
    with pytest.raises(ValidationError, match="topic"):
        await r.user_rule(owner, definition("x", topic_is(tag.id), SetTopic(work.id)))
    with pytest.raises(NotFoundError):
        await r.user_rule(owner, definition("x", contact_is(nord.id), SetTopic(TagId(new_id()))))
    await r.user_rule(owner, definition("Arbeit", topic_is(work.id), SetTopic(work.id)))
    with pytest.raises(ConflictError, match="'Arbeit' is used by the rules"):
        await service.delete_tag(r.admin.id, work.id)


async def test_a_change_of_the_contact_by_a_person_runs_the_rules_on_the_topic_left(
    world: World,
) -> None:
    r = await rule_world(world)
    owner = await world.user()
    service = world.master_data
    work = await service.create_tag(r.admin.id, "Arbeit", scope=TagScope.TOPIC)
    nord = await service.create_contact(r.admin.id, "Nord", topic_ids=[work.id])
    sued = await service.create_contact(r.admin.id, "Süd", topic_ids=[work.id])
    await r.user_rule(owner, definition("Süd at work", contact_is(sued.id), SetTopic(work.id)))
    document = await r.arrive(owner)
    await r.documents.change_metadata(owner.id, document.id, DocumentChanges(contact_id=nord.id))
    change = await r.documents.change_metadata(
        owner.id, document.id, DocumentChanges(contact_id=sued.id)
    )
    assert change.document.topic_id == work.id
