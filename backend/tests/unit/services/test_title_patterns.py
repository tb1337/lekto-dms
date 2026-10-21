"""A document type's title pattern is a rule the type keeps: made, changed and deleted with
the pattern, read-only otherwise; it titles the type's documents and gives way to a rule of
the owner's that sets the title."""

import pytest

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import ConflictError
from lekto.core.domain.fields import FieldType
from lekto.core.domain.pipeline import Lane, Node
from lekto.core.domain.rules import Rule, SetTitle
from lekto.core.domain.users import User
from tests.unit.services.rules_support import (
    Classifies,
    RuleWorld,
    Titles,
    channel_api,
    definition,
    notes,
    rule_world,
)
from tests.unit.services.support import World


async def rule_notes(world: World, owner: User, document: Document) -> list[tuple[str, str]]:
    log = await world.documents.processing_log(owner.id, document.id)
    entry = next(item for item in reversed(log) if item.node is Node.APPLY_RULES)
    return notes(entry.result.output)


async def title_rules(r: RuleWorld) -> list[Rule]:
    return [rule for rule in await r.rules.list_rules(r.admin.id) if rule.managed_by is not None]


async def test_the_pattern_is_a_rule_of_its_type(world: World) -> None:
    r = await rule_world(world)
    service = world.master_data
    kind = await service.create_document_type(
        r.admin.id, "Rechnung", title_pattern="{{ document_type }} {{ filename }}"
    )
    (rule,) = await title_rules(r)
    assert rule.managed_by == kind.id and rule.space_id is None
    assert rule.definition.name == "Rechnung"
    assert rule.definition.actions == (SetTitle("{{ document_type }} {{ filename }}"),)

    # It follows the type: a new pattern, a new name.
    await service.change_document_type(r.admin.id, kind.id, title_pattern="{{ filename }}")
    await service.change_document_type(r.admin.id, kind.id, name="Beleg")
    (rule,) = await title_rules(r)
    assert rule.current.number == 3 and rule.definition.name == "Beleg"
    assert rule.definition.actions == (SetTitle("{{ filename }}"),)

    # Nobody changes it otherwise, not even an admin.
    for action in (
        r.rules.change(r.admin.id, rule.id, rule.definition),
        r.rules.set_enabled(r.admin.id, rule.id, False),
        r.rules.delete(r.admin.id, rule.id),
    ):
        with pytest.raises(ConflictError, match="title pattern of 'Beleg'"):
            await action

    # Without a pattern, or with the type, it goes; a new pattern makes a new rule.
    await service.change_document_type(r.admin.id, kind.id, title_pattern=None)
    assert await title_rules(r) == []
    await service.change_document_type(r.admin.id, kind.id, title_pattern="{{ filename }}")
    (again,) = await title_rules(r)
    assert again.id != rule.id
    await service.delete_document_type(r.admin.id, kind.id)
    assert await title_rules(r) == []


async def test_renaming_a_field_renames_it_in_the_pattern_and_its_rule(world: World) -> None:
    r = await rule_world(world)
    service = world.master_data
    kind = await service.create_document_type(r.admin.id, "Lohn")
    gross = await service.create_field(
        r.admin.id, "LA_Brutto", FieldType.AMOUNT, document_type_ids=[kind.id]
    )
    await service.change_document_type(
        r.admin.id, kind.id, title_pattern="Lohn {{ field.la_brutto }}"
    )
    await service.change_field(r.admin.id, gross.id, name="Gesamtbrutto")
    async with world.uow() as uow:
        assert (await uow.document_types.get(kind.id)).title_pattern == (
            "Lohn {{ field.gesamtbrutto }}"
        )
    (rule,) = await title_rules(r)
    assert rule.definition.actions == (SetTitle("Lohn {{ field.gesamtbrutto }}"),)


async def test_the_pattern_titles_the_type_s_documents(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    kind = await world.master_data.create_document_type(
        r.admin.id, "Rechnung", title_pattern="{{ document_type }} {{ filename }}"
    )
    model = Titles("Stromrechnung März 2026")

    document = await r.arrive(owner, classify=Classifies(document_type=kind.id), fields=model)
    assert (document.lane, document.title) == (Lane.GREEN, "Rechnung scan")

    # Another type's documents keep the model's title.
    document = await r.arrive(owner, fields=model)
    assert document.title == "Stromrechnung März 2026"


async def test_a_missing_value_keeps_the_model_s_title(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    kind = await world.master_data.create_document_type(
        r.admin.id, "Rechnung", title_pattern="{{ contact }} Rechnung"
    )
    document = await r.arrive(
        owner, classify=Classifies(document_type=kind.id), fields=Titles("Strom März")
    )
    assert (document.lane, document.title) == (Lane.GREEN, "Strom März")
    assert ("title", "skipped") in await rule_notes(world, owner, document)


async def test_a_rule_of_the_owner_s_wins_over_the_pattern(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    kind = await world.master_data.create_document_type(
        r.admin.id, "Rechnung", title_pattern="{{ document_type }}"
    )
    await r.personal_rule(
        owner, definition("Mine", channel_api(), SetTitle("Meine {{ filename }}"))
    )

    document = await r.arrive(
        owner, classify=Classifies(document_type=kind.id), fields=Titles("Strom")
    )
    assert (document.lane, document.title) == (Lane.GREEN, "Meine scan")
    assert ("title", "yielded") in await rule_notes(world, owner, document)
