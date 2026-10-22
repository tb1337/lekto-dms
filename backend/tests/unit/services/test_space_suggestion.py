"""Lekto suggests the space: what the language model is asked, what the judge does with its
answer, and how a person accepts or keeps a suggestion in the inbox."""

from typing import Any

import pytest

from lekto.adapters.outbound.memory import FakeLanguageModel
from lekto.core.domain.classification import SPACE, checks_from_json
from lekto.core.domain.classifier import OWN_SPACE
from lekto.core.domain.documents import Document, DocumentChanges
from lekto.core.domain.errors import NotFoundError
from lekto.core.domain.inbox import InboxTab
from lekto.core.domain.pipeline import Lane, Node, Outcome, ProcessingStatus
from lekto.core.domain.rules import RuleScope
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import User
from lekto.core.services._spaces import SpaceCandidates
from lekto.core.services.classification.nodes import JudgeNode
from lekto.core.services.classification.prompts import SPACES_HEADING
from lekto.core.services.classification.signals import (
    ClassifierSignal,
    FactsSignal,
    NeighboursSignal,
    _candidate_spaces,
)
from lekto.core.services.inbox import open_nodes
from lekto.core.services.objects import text_key
from lekto.core.services.pipeline import MetadataResult, NodeExecutor
from lekto.core.services.rules import RuleService
from tests import builders
from tests.builders import incoming
from tests.unit.services.rules_support import FakeMatcher
from tests.unit.services.support import World
from tests.unit.services.test_classification import (
    INVOICE,
    extraction,
    fields_step,
    judge,
    model,
    proposal,
    responder,
    rules_step,
    seed,
    signal_step,
)
from tests.unit.services.test_space_rules import files_into


async def household(world: World, *, anna_reads_tobi: bool = False) -> tuple[User, User, Space]:
    """Tobi and Anna edit "Haushalt"; Anna described her personal space (only for her)."""
    tobi, anna = await world.user("tobi"), await world.user("anna")
    shared = builders.space(tobi, "Haushalt", editors=[anna])
    shared.describe("Wohnung, Nebenkosten, Versorger")
    async with world.uow() as uow:
        await uow.spaces.add(shared)
        annas = await uow.spaces.get_personal(anna.id)
        annas.describe("Annas Arbeit")
        await uow.spaces.update(annas)
        if anna_reads_tobi:
            home = await uow.spaces.get_personal(tobi.id)
            home.set_member(anna.id, SpaceRole.READ)
            await uow.spaces.update(home)
        await uow.commit()
    return tobi, anna, shared


async def tobis_invoice(world: World, tobi: User) -> Document:
    document = builders.document(tobi, await world.personal_space(tobi))
    async with world.uow() as uow:
        await uow.documents.add(document)
        await uow.commit()
    await world.object_store.put(
        text_key(document.id), INVOICE.encode(), content_type="text/markdown; charset=utf-8"
    )
    return document


def space_check(result: MetadataResult) -> Any:
    return next(c for c in checks_from_json(result.result.output["fields"]) if c.field == SPACE)


async def test_the_model_chooses_among_the_spaces_the_uploader_may_file_into(world: World) -> None:
    """The uploader's own personal space first, shared spaces with their description, other
    users' personal spaces by their user only: what Anna wrote about hers is hers."""
    await seed(world)
    tobi, anna, shared = await household(world)
    document = await tobis_invoice(world, tobi)
    fake = model(proposal(space="s2"))

    result = await signal_step(world, fake).run(document)

    (request,) = fake.requests
    listed = request.user.split(SPACES_HEADING, 1)[1].split("The document follows", 1)[0]
    assert listed.strip().splitlines() == [
        "- s1: own personal space of the uploader",
        "- s2: Haushalt: Wohnung, Nebenkosten, Versorger",
        "- s3: personal space of anna",
    ]
    assert "Annas Arbeit" not in request.user
    schema: Any = request.schema
    assert schema["properties"]["space"]["anyOf"][0]["enum"] == ["s1", "s2", "s3"]
    out: Any = result.output
    assert out["proposal"]["space"] == str(shared.id)
    sent: Any = result.input
    assert sent["spaces"]["s3"] == str((await world.personal_space(anna)).id)


async def test_the_uploader_s_own_description_of_their_personal_space_is_listed(
    world: World,
) -> None:
    """What Tobi wrote about his personal space goes with his own documents only."""
    await seed(world)
    tobi, _, _ = await household(world)
    async with world.uow() as uow:
        home = await uow.spaces.get_personal(tobi.id)
        home.describe("Arbeit, Gesundheit")
        await uow.spaces.update(home)
        await uow.commit()
    document = await tobis_invoice(world, tobi)
    fake = model(proposal(space="s1"))

    await signal_step(world, fake).run(document)

    (request,) = fake.requests
    listed = request.user.split(SPACES_HEADING, 1)[1].split("The document follows", 1)[0]
    assert listed.strip().splitlines()[0] == (
        "- s1: own personal space of the uploader: Arbeit, Gesundheit"
    )


async def test_a_user_with_nowhere_else_to_file_is_not_asked(world: World) -> None:
    await seed(world)
    tobi = await world.user("tobi")
    document = await tobis_invoice(world, tobi)
    fake = model(proposal())
    result = await signal_step(world, fake).run(document)
    (request,) = fake.requests
    assert SPACES_HEADING not in request.user
    schema: Any = request.schema
    assert "space" not in schema["properties"]
    out: Any = result.output
    assert out["proposal"]["space"] is None
    judged = await judge(world, document, model(proposal()))
    assert isinstance(judged, MetadataResult)
    assert all(c.field != SPACE for c in checks_from_json(judged.result.output["fields"]))


async def test_a_wider_space_is_suggested_and_the_document_stays(world: World) -> None:
    await seed(world)
    tobi, _, shared = await household(world)
    document = await tobis_invoice(world, tobi)
    result = await judge(world, document, model(proposal(space="s2")))
    assert isinstance(result, MetadataResult)
    check = space_check(result)
    assert check.outcome is Outcome.UNCERTAIN
    assert check.suggestion == str(shared.id)
    assert check.reason == "suggests another space, which shows it to more people"
    assert result.space is None
    assert result.result.outcome is Outcome.UNCERTAIN


async def test_a_space_that_shows_it_to_no_one_new_is_moved_to(world: World) -> None:
    """Anna reads Tobi's personal space already: Haushalt shows it to no one new."""
    await seed(world)
    tobi, _, shared = await household(world, anna_reads_tobi=True)
    document = await tobis_invoice(world, tobi)
    result = await judge(world, document, model(proposal(space="s2")))
    assert isinstance(result, MetadataResult)
    assert space_check(result).value == str(shared.id)
    assert result.space == shared.id
    async with world.uow() as uow:
        stored = await uow.documents.get(document.id)
        await result.apply(uow, stored, builders.NOW)
    assert stored.space_id == shared.id
    assert stored.space_confirmed_at is None  # the pipeline placed it


async def test_a_space_a_person_decided_is_left(world: World) -> None:
    await seed(world)
    tobi, _, _ = await household(world)
    document = await tobis_invoice(world, tobi)
    document.confirm_space(builders.NOW)
    async with world.uow() as uow:
        await uow.documents.update(document)
        await uow.commit()
    result = await judge(world, document, model(proposal(space="s2")))
    assert isinstance(result, MetadataResult)
    check = space_check(result)
    assert (check.outcome, check.value, check.reason) == (
        Outcome.OK,
        None,
        "a person chose the space",
    )


# --- through the pipeline and the inbox -------------------------------------------------------


async def arrive(world: World, uploader: User, answer: dict[str, Any]) -> Document:
    fake = FakeLanguageModel(responder(answer, extraction()))
    executors: dict[Node, NodeExecutor] = {
        Node.SIGNAL_LLM: signal_step(world, fake),
        Node.SIGNAL_FACTS: FactsSignal(world.uow, world.object_store),
        Node.SIGNAL_CLASSIFIER: ClassifierSignal(world.object_store, None, world.uow),
        Node.SIGNAL_NEIGHBOURS: NeighboursSignal(
            world.uow, world.object_store, None, None, builders.NEIGHBOURS
        ),
        Node.JUDGE: JudgeNode(
            world.uow,
            world.object_store,
            world.clock,
            builders.CLASSIFICATION,
            thresholds=builders.THRESHOLDS,
        ),
        Node.FIELDS: fields_step(world, fake),
        Node.APPLY_RULES: rules_step(world),
    }
    pipeline = world.pipeline(executors)
    received = await pipeline.receive(uploader.id, incoming(b"%PDF-1.7\n%%EOF\n"), filename="a.pdf")
    await world.object_store.put(
        text_key(received.id), INVOICE.encode(), content_type="text/markdown; charset=utf-8"
    )
    await world.drain(pipeline)
    async with world.uow() as uow:
        return await uow.documents.get(received.id)


async def test_accepting_the_suggestion_moves_it_and_it_is_new_for_the_others(
    world: World,
) -> None:
    await seed(world)
    tobi, anna, shared = await household(world)
    document = await arrive(world, tobi, proposal(space="s2"))
    assert document.lane is Lane.YELLOW
    assert document.processing.status is ProcessingStatus.REVIEW
    assert document.space_id == (await world.personal_space(tobi)).id
    with pytest.raises(NotFoundError):  # not shown to her yet
        await world.documents.get(anna.id, document.id)

    await world.pipeline({Node.APPLY_RULES: rules_step(world)}).confirm(
        tobi.id, document.id, DocumentChanges(), accept_suggestions=True
    )
    await world.drain(world.pipeline({Node.APPLY_RULES: rules_step(world)}))
    async with world.uow() as uow:
        moved = await uow.documents.get(document.id)
    assert moved.space_id == shared.id
    assert moved.space_confirmed_at is not None
    assert moved.lane is Lane.GREEN
    tabs = await world.inbox.summary(anna.id)
    assert tabs.counts.get(InboxTab.NEW, 0) == 1


async def test_keeping_the_space_is_a_decision(world: World) -> None:
    await seed(world)
    tobi, _, _ = await household(world)
    home = await world.personal_space(tobi)
    document = await arrive(world, tobi, proposal(space="s2"))
    await world.pipeline({Node.APPLY_RULES: rules_step(world)}).confirm(
        tobi.id, document.id, DocumentChanges()
    )
    async with world.uow() as uow:
        kept = await uow.documents.get(document.id)
    assert kept.space_id == home.id
    assert kept.space_confirmed_at is not None  # the judge leaves it from now on


async def test_sure_it_stays_does_not_hold_back_a_rule_that_files_it(world: World) -> None:
    """The model names the uploader's own space (alone, nothing else knows it): no model
    value, so a trusted rule files it into Haushalt as it would without an answer."""
    await seed(world)
    tobi, _, shared = await household(world)
    rules = RuleService(world.uow, world.clock, builders.TEMPLATES, FakeMatcher())
    await rules.create(tobi.id, RuleScope.SPACE, files_into(shared))
    document = await arrive(world, tobi, proposal(space="s1"))
    assert document.space_id == shared.id
    assert document.lane is Lane.GREEN


async def test_rules_that_file_it_into_the_suggested_space_settle_the_suggestion(
    world: World,
) -> None:
    await seed(world)
    tobi, _, shared = await household(world)
    rules = RuleService(world.uow, world.clock, builders.TEMPLATES, FakeMatcher())
    await rules.create(tobi.id, RuleScope.SPACE, files_into(shared))
    document = await arrive(world, tobi, proposal(space="s2"))
    assert document.space_id == shared.id
    assert document.lane is Lane.GREEN
    async with world.uow() as uow:
        log = await uow.processing_log.list_for(document.id)
    assert open_nodes(document, log) == ()


async def test_a_suggestion_the_confirming_editor_cannot_take_keeps_the_space(
    world: World,
) -> None:
    """Bob edits Tobi's personal space, not Haushalt: confirming with the suggestions decides
    the rest and keeps the space, instead of refusing the whole confirmation."""
    await seed(world)
    tobi, _, _ = await household(world)
    bob = await world.user("bob")
    home = await world.personal_space(tobi)
    async with world.uow() as uow:
        stored = await uow.spaces.get(home.id)
        stored.set_member(bob.id, SpaceRole.EDIT)
        await uow.spaces.update(stored)
        await uow.commit()
    document = await arrive(world, tobi, proposal(space="s2"))
    assert document.lane is Lane.YELLOW
    await world.pipeline({Node.APPLY_RULES: rules_step(world)}).confirm(
        bob.id, document.id, DocumentChanges(), accept_suggestions=True
    )
    async with world.uow() as uow:
        kept = await uow.documents.get(document.id)
    assert kept.space_id == home.id
    assert kept.space_confirmed_at is not None


def test_own_and_the_id_of_the_uploader_s_personal_space_add_up() -> None:
    """Documents handed over to Anna are labelled with her space's id, her own uploads "own":
    for her, both are her personal space."""
    anna = builders.user("anna")
    annas = builders.personal_space(anna)
    house = builders.space(anna, "Haushalt")
    candidates = SpaceCandidates(
        uploader=anna, personal=annas.id, spaces={annas.id: annas, house.id: house}, people={}
    )
    ranked, known = _candidate_spaces(
        [(OWN_SPACE, 0.4), (str(house.id), 0.35), (str(annas.id), 0.25)], candidates
    )
    assert ranked[0][0] == annas.id
    assert ranked[0][1] == pytest.approx(0.65)
    assert [space for space, _ in ranked] == [annas.id, house.id]
    assert known == {annas.id, house.id}
