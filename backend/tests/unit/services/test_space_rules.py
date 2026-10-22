"""The rules of the spaces a document enters: on arrival in the pipeline, after a person's
move, after a rule applied to existing documents; each space at most once in a chain."""

from lekto.core.domain.pipeline import RULES, RULES_CHANGE, Lane, Node
from lekto.core.domain.rules import RuleDefinition, SetSpace, Trigger
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import User
from lekto.core.services.rules.changes import ChangeRules
from lekto.core.services.rules.running import Prepared
from tests import builders
from tests.builders import TEMPLATES
from tests.unit.services.rules_support import (
    MAX_TEXT,
    RuleWorld,
    add_tags,
    channel_api,
    definition,
    reports,
    rule_world,
)
from tests.unit.services.support import World


async def household(rules: RuleWorld) -> tuple[User, User, Space]:
    """Tobi and Anna edit "Haushalt"."""
    world = rules.world
    tobi, anna = await world.user("tobi"), await world.user("anna")
    space = await world.spaces.create(tobi.id, "Haushalt")
    space = await world.spaces.set_member(tobi.id, space.id, anna.id, SpaceRole.EDIT)
    return tobi, anna, space


def files_into(space: Space, name: str = "File") -> RuleDefinition:
    return definition(name, channel_api(), SetSpace(space.id), triggers=(Trigger.INGEST,))


async def test_the_rules_of_the_space_a_rule_files_into_run_next(world: World) -> None:
    rules = await rule_world(world)
    tobi, anna, shared = await household(rules)
    tag = await rules.tag("Haushalt")
    home = await world.personal_space(tobi)
    await rules.personal_rule(tobi, files_into(shared))
    await rules.space_rule(
        anna,
        shared.id,
        definition("Tag", channel_api(), add_tags(tag.id), triggers=(Trigger.INGEST,)),
    )
    document = await rules.arrive(tobi)
    assert document.space_id == shared.id
    assert tag.id in document.tag_ids
    assert document.lane is Lane.GREEN
    (entry,) = await rules.rule_entries(document, RULES)
    assert entry.result.output["spaces"] == [str(home.id), str(shared.id)]
    assert len(reports(entry.result.output)) == 2


async def test_rules_that_move_it_back_stop_the_chain(world: World) -> None:
    rules = await rule_world(world)
    tobi, anna, shared = await household(rules)
    home = await world.personal_space(tobi)
    await rules.personal_rule(tobi, files_into(shared))
    await rules.space_rule(tobi, shared.id, files_into(home, "Back"))
    document = await rules.arrive(tobi)
    assert document.space_id == shared.id  # the move back is not applied
    assert document.lane is Lane.YELLOW
    (entry,) = await rules.rule_entries(document, RULES)
    assert "rules move it back and forth: tobi → Haushalt → tobi" in (entry.result.reason or "")
    del anna


async def test_a_person_s_move_runs_the_target_s_rules_which_leave_the_space(
    world: World,
) -> None:
    """As change rules: nothing turns yellow, and the space the person chose stays."""
    rules = await rule_world(world)
    tobi, anna, shared = await household(rules)
    tag = await rules.tag("Haushalt")
    annas = await world.personal_space(anna)
    await rules.space_rule(
        anna,
        shared.id,
        definition(
            "Tag and hand over",
            channel_api(),
            add_tags(tag.id),
            SetSpace(annas.id),
            triggers=(Trigger.INGEST,),
        ),
    )
    document = await rules.arrive(tobi)
    assert document.lane is Lane.GREEN
    await rules.documents.move(tobi.id, document.id, shared.id)
    moved = await rules.stored(document)
    assert moved.space_id == shared.id
    assert tag.id in moved.tag_ids
    assert moved.lane is Lane.GREEN
    assert moved.space_confirmed_at is not None
    (entry,) = await rules.rule_entries(document, RULES_CHANGE)
    assert entry.result.input["trigger"] == Trigger.INGEST.value
    assert entry.result.input["space_id"] == str(shared.id)


async def test_a_move_by_rules_outside_processing_chains_and_stops_going_back(
    world: World,
) -> None:
    """After a rule applied to existing documents: the target's rules, then those of the next
    space, and a move back is reported, not applied."""
    rules = await rule_world(world)
    tobi, anna, shared = await household(rules)
    annas = await world.personal_space(anna)
    home = await world.personal_space(tobi)
    await rules.space_rule(anna, shared.id, files_into(annas, "To Anna"))
    await rules.space_rule(anna, annas.id, files_into(shared, "Back"))
    document = await rules.arrive(tobi)
    change = ChangeRules(
        world.object_store, rules.matcher, TEMPLATES, max_text=MAX_TEXT, pipeline_version="test"
    )
    async with world.uow() as uow:
        stored = await uow.documents.get(document.id)
        stored.move_to(shared.id, builders.NOW)  # as a rule applied to it would
        await change.after_arrival(
            uow,
            document=stored,
            source=home,
            prepared=Prepared(),
            definitions={},
            now=builders.NOW,
            by_person=False,
        )
        await uow.documents.update(stored)
        await uow.commit()
    moved = await rules.stored(document)
    assert moved.space_id == annas.id
    first, second = await rules.rule_entries(document, RULES_CHANGE)
    assert first.result.input["space_id"] == str(shared.id)
    assert second.result.input["space_id"] == str(annas.id)
    assert second.result.output["problem"] == (
        "rules move it back and forth: tobi → Haushalt → anna → Haushalt"
    )
    assert all(entry.node is Node.APPLY_RULES for entry in (first, second))
