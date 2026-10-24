"""RuleService: who may read and change which rules, references, deleting rules, and rules whose
references go away."""

import pytest

from lekto.adapters.outbound.regex import RegexPatternMatcher
from lekto.core.domain.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from lekto.core.domain.fields import FieldType
from lekto.core.domain.ids import ContactId, SpaceId, new_id
from lekto.core.domain.pipeline import Lane
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.rules import (
    AddTags,
    ForceReview,
    Rule,
    RuleScope,
    SetContact,
    SetDocumentType,
    SetField,
    SetSpace,
    SetTitle,
)
from lekto.core.domain.spaces import SpaceRole
from lekto.core.services.rules import RuleService
from tests import builders
from tests.builders import TEMPLATES
from tests.unit.services.rules_support import channel_api, definition, rule_world, text_matches
from tests.unit.services.support import World


async def test_space_rules_are_their_spaces_and_global_rules_the_admins(world: World) -> None:
    r = await rule_world(world)
    owner, other = await world.user(), await world.user()
    title = definition("Title", channel_api(), SetTitle("Scan"))
    mine = await r.personal_rule(owner, title)
    theirs = await r.personal_rule(other, title)
    review = definition("Check", channel_api(), ForceReview("check"))

    # Only admins make and change global rules; everyone reads them.
    with pytest.raises(PermissionDeniedError):
        await r.rules.create(owner.id, RuleScope.GLOBAL, review)
    shared = await r.global_rule(review)
    assert shared.space_id is None
    assert (await r.rules.get(owner.id, shared.id)).id == shared.id
    with pytest.raises(PermissionDeniedError):
        await r.rules.change(owner.id, shared.id, review)
    with pytest.raises(PermissionDeniedError):
        await r.rules.set_enabled(owner.id, shared.id, False)
    with pytest.raises(PermissionDeniedError):
        await r.rules.delete(owner.id, shared.id)
    assert (await r.rules.change(r.admin.id, shared.id, review)).current.number == 2

    # Another user does not learn that the rule of a space they do not edit exists.
    for action in (
        r.rules.get(other.id, mine.id),
        r.rules.versions(other.id, mine.id),
        r.rules.version(other.id, mine.id, 1),
        r.rules.change(other.id, mine.id, title),
        r.rules.set_enabled(other.id, mine.id, False),
        r.rules.delete(other.id, mine.id),
    ):
        with pytest.raises(NotFoundError):
            await action

    # Admins read and change every rule (Tobi, 08.10.2026); the space stays.
    assert (await r.rules.get(r.admin.id, mine.id)).id == mine.id
    assert len(await r.rules.versions(r.admin.id, mine.id)) == 1
    changed = await r.rules.change(r.admin.id, mine.id, title)
    personal = await world.personal_space(owner)
    assert (changed.space_id, changed.current.number) == (personal.id, 2)
    assert changed.current.created_by == r.admin.id
    assert not (await r.rules.set_enabled(r.admin.id, mine.id, False)).enabled
    assert (await r.rules.set_enabled(r.admin.id, mine.id, True)).enabled

    # Listing: the caller's rules and the global ones; all users' for admins only.
    assert {rule.id for rule in await r.rules.list_rules(owner.id)} == {mine.id, shared.id}
    space_rules = await r.rules.list_rules(owner.id, scope=RuleScope.SPACE)
    assert {rule.id for rule in space_rules} == {mine.id}
    of_personal = await r.rules.list_rules(owner.id, space=personal.id)
    assert {rule.id for rule in of_personal} == {mine.id}
    assert {rule.id for rule in await r.rules.list_rules(r.admin.id)} == {shared.id}
    with pytest.raises(PermissionDeniedError):
        await r.rules.list_rules(owner.id, all_users=True)
    everything = await r.rules.list_rules(r.admin.id, all_users=True)
    assert {rule.id for rule in everything} == {mine.id, theirs.id, shared.id}
    assert everything[0].id == shared.id  # same priority: global rules first


async def test_rules_refer_only_to_what_exists_and_file_where_the_owner_may(world: World) -> None:
    r = await rule_world(world)
    owner, other = await world.user(), await world.user()
    foreign = await world.spaces.create(other.id, "Office")

    async def files_into(space: SpaceId) -> Rule:
        return await r.rules.create(
            owner.id, RuleScope.SPACE, definition("File", channel_api(), SetSpace(space))
        )

    with pytest.raises(NotFoundError):
        await files_into(foreign.id)  # not shared: does not exist for the owner
    with pytest.raises(NotFoundError):
        await files_into(SpaceId(new_id()))
    await world.spaces.set_member(other.id, foreign.id, owner.id, SpaceRole.READ)
    with pytest.raises(PermissionDeniedError):
        await files_into(foreign.id)
    await world.spaces.set_member(other.id, foreign.id, owner.id, SpaceRole.EDIT)
    rule = await r.personal_rule(owner, definition("File", channel_api(), SetSpace(foreign.id)))

    # Changing and enabling check again.
    await world.spaces.set_member(other.id, foreign.id, owner.id, SpaceRole.READ)
    await r.rules.set_enabled(owner.id, rule.id, False)
    with pytest.raises(PermissionDeniedError):
        await r.rules.set_enabled(owner.id, rule.id, True)
    with pytest.raises(PermissionDeniedError):
        await r.rules.change(
            owner.id, rule.id, definition("File again", channel_api(), SetSpace(foreign.id))
        )
    assert (await r.rules.get(owner.id, rule.id)).current.number == 1

    with pytest.raises(NotFoundError):
        await r.personal_rule(
            owner, definition("C", channel_api(), SetContact(ContactId(new_id())))
        )


async def test_a_deleted_rule_never_runs_and_its_versions_stay_readable(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    tag = await r.tag("tax")
    rule = await r.personal_rule(
        owner, definition("Tax", channel_api(), AddTags(frozenset({tag.id})))
    )
    await r.rules.change(
        owner.id, rule.id, definition("Tax v2", channel_api(), AddTags(frozenset({tag.id})))
    )
    await r.rules.delete(owner.id, rule.id)

    with pytest.raises(NotFoundError):
        await r.rules.get(owner.id, rule.id)
    with pytest.raises(NotFoundError):
        await r.rules.set_enabled(owner.id, rule.id, True)
    with pytest.raises(NotFoundError):
        await r.rules.delete(owner.id, rule.id)
    assert await r.rules.list_rules(owner.id) == []
    assert await r.rules.list_rules(r.admin.id, all_users=True) == []
    versions = await r.rules.versions(owner.id, rule.id)
    assert [version.definition.name for version in versions] == ["Tax", "Tax v2"]

    document = await r.arrive(owner)
    assert document.tag_ids == set()
    (entry,) = await r.rule_entries(document, "rules")
    assert entry.result.input["rules"] == []


async def test_deleting_master_data_and_spaces_disables_the_rules_that_use_them(
    world: World,
) -> None:
    """Tags are the exception: a tag a rule uses is not deleted (an admin sees every rule)."""
    r = await rule_world(world)
    owner, sharer = await world.user(), await world.user()
    contact = await r.contact("ACME")
    kind = await world.master_data.create_document_type(r.admin.id, "Invoice")
    tag = await r.tag("tax")
    space = await world.spaces.create(sharer.id, "Shared")
    await world.spaces.set_member(sharer.id, space.id, owner.id, SpaceRole.EDIT)
    by_contact = await r.personal_rule(
        owner, definition("C", channel_api(), SetContact(contact.id))
    )
    by_type = await r.personal_rule(owner, definition("T", channel_api(), SetDocumentType(kind.id)))
    by_tag = await r.global_rule(definition("G", channel_api(), AddTags(frozenset({tag.id}))))
    by_space = await r.personal_rule(owner, definition("D", channel_api(), SetSpace(space.id)))
    note = await world.master_data.create_field(r.admin.id, "Note", FieldType.TEXT)
    by_field = await r.personal_rule(
        owner, definition("A", channel_api(), SetField(note.id, "from a rule"))
    )
    unrelated = await r.personal_rule(owner, definition("U", channel_api(), SetTitle("Scan")))

    await world.master_data.delete_contact(r.admin.id, contact.id)
    await world.master_data.delete_document_type(r.admin.id, kind.id)
    with pytest.raises(ConflictError, match="rules 'G'"):
        await world.master_data.delete_tag(r.admin.id, tag.id)
    assert (await r.rules.get(r.admin.id, by_tag.id)).enabled
    await world.spaces.delete(sharer.id, space.id)
    await world.master_data.delete_field(r.admin.id, note.id)

    expected = {
        by_contact.id: "contact 'ACME' was deleted",
        by_type.id: "document type 'Invoice' was deleted",
        by_space.id: "space 'Shared' was deleted",
        by_field.id: "field 'Note' was deleted",
    }
    for id, reason in expected.items():
        rule = await r.rules.get(r.admin.id, id)
        assert rule.enabled is False
        assert rule.disabled_reason is not None and rule.disabled_reason.text == reason
        # Enabling checks the references again.
        actor = r.admin if rule.scope is RuleScope.GLOBAL else owner
        with pytest.raises(NotFoundError):
            await r.rules.set_enabled(actor.id, id, True)
    assert (await r.rules.get(owner.id, unrelated.id)).enabled


async def test_removing_a_choice_a_rule_uses_disables_the_rule(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    size = await world.master_data.create_field(
        r.admin.id, "Size", FieldType.CHOICE, choices=["S", "M"]
    )
    small = await r.personal_rule(owner, definition("S", channel_api(), SetField(size.id, "S")))
    medium = await r.personal_rule(owner, definition("M", channel_api(), SetField(size.id, "M")))

    await world.master_data.change_field(r.admin.id, size.id, choices=["S"])
    disabled = await r.rules.get(owner.id, medium.id)
    assert disabled.enabled is False
    assert disabled.disabled_reason == because(ReasonCode.RULE_DISABLED_CHOICE, field="Size")
    assert (await r.rules.get(owner.id, small.id)).enabled
    with pytest.raises(ValidationError):
        await r.rules.set_enabled(owner.id, medium.id, True)

    await world.master_data.change_field(r.admin.id, size.id, choices=["S", "M"])
    enabled = await r.rules.set_enabled(owner.id, medium.id, True)
    assert (enabled.enabled, enabled.disabled_reason) == (True, None)


async def test_deleting_a_user_removes_the_rules_of_their_personal_space(world: World) -> None:
    r = await rule_world(world)
    leaving, staying = await world.user("leaving"), await world.user()
    personal = await world.personal_space(leaving)
    gone = await r.personal_rule(leaving, definition("Mine", channel_api(), SetTitle("Scan")))
    hands_over = await r.personal_rule(
        staying, definition("Hand over", channel_api(), SetSpace(personal.id))
    )

    await world.users.delete_user(r.admin.id, leaving.id)

    with pytest.raises(NotFoundError):
        await r.rules.get(r.admin.id, gone.id)
    everything = await r.rules.list_rules(r.admin.id, all_users=True)
    assert [rule.id for rule in everything] == [hands_over.id]
    rule = await r.rules.get(staying.id, hands_over.id)
    assert (rule.enabled, rule.disabled_reason) == (
        False,
        because(ReasonCode.RULE_DISABLED_PERSONAL_SPACE, user="leaving"),
    )


async def test_the_editors_of_a_space_make_its_rules(world: World) -> None:
    r = await rule_world(world)
    editor, reader, stranger = await world.user(), await world.user(), await world.user()
    household = await world.spaces.create(editor.id, "Household")
    await world.spaces.set_member(editor.id, household.id, reader.id, SpaceRole.READ)
    title = definition("Title", channel_api(), SetTitle("Scan"))
    rule = await r.space_rule(editor, household.id, title)
    assert (rule.scope, rule.space_id) == (RuleScope.SPACE, household.id)
    with pytest.raises(PermissionDeniedError):
        await r.space_rule(reader, household.id, title)
    with pytest.raises(NotFoundError):
        await r.space_rule(stranger, household.id, title)
    for user in (reader, stranger):  # readers do not see the space's rules
        with pytest.raises(NotFoundError):
            await r.rules.get(user.id, rule.id)
        assert rule.id not in {item.id for item in await r.rules.list_rules(user.id)}
    # A new editor sees and changes them.
    await world.spaces.set_member(editor.id, household.id, reader.id, SpaceRole.EDIT)
    assert (await r.rules.change(reader.id, rule.id, title)).current.created_by == reader.id
    assert rule.id in {item.id for item in await r.rules.list_rules(reader.id)}
    with pytest.raises(ValidationError, match="global rule belongs to no space"):
        await r.rules.create(r.admin.id, RuleScope.GLOBAL, title, space=household.id)
    # Its rules go with the space.
    async with world.uow() as uow:
        await uow.documents.add(builders.processed(editor, household))
        await uow.commit()
    with pytest.raises(ConflictError, match="not empty"):
        await world.spaces.delete(editor.id, household.id)


async def test_rules_hand_documents_over_into_another_users_personal_space(
    world: World,
) -> None:
    r = await rule_world(world)
    owner, partner = await world.user(), await world.user()
    theirs = await world.personal_space(partner)
    rule = await r.personal_rule(owner, definition("To them", channel_api(), SetSpace(theirs.id)))
    assert rule.definition.references().spaces == {theirs.id}
    document = await r.arrive(owner)
    assert document.space_id == theirs.id  # the channel is no guess: nothing to confirm


async def test_rules_hand_nothing_over_to_a_deactivated_user(world: World) -> None:
    """Saving refuses it; a rule saved before the user was deactivated leaves the document
    where it is and asks a person."""
    r = await rule_world(world)
    owner, partner = await world.user(), await world.user()
    theirs = await world.personal_space(partner)
    rule = await r.personal_rule(owner, definition("To them", channel_api(), SetSpace(theirs.id)))
    await world.users.update(r.admin.id, partner.id, active=False)
    document = await r.arrive(owner)
    assert document.space_id == (await world.personal_space(owner)).id
    assert document.lane is Lane.YELLOW
    again = definition("Again", channel_api(), SetSpace(theirs.id))
    with pytest.raises(NotFoundError):
        await r.rules.change(owner.id, rule.id, again)


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (SetTitle("{{ contact "), r"actions\[0\]: invalid template"),
        (SetTitle("{{ sender }}"), r"actions\[0\]: unknown value sender"),
        (SetTitle("{{ field.brutto }}"), r"unknown value field\.brutto"),
        (SetTitle("{{ contact | nonsense }}"), "unknown filter"),
        (ForceReview("{% include 'x' %}"), r"actions\[0\]: invalid template"),
    ],
)
async def test_a_rule_s_templates_are_checked(world: World, action: object, message: str) -> None:
    r = await rule_world(world)
    owner = await world.user()
    with pytest.raises(ValidationError, match=message):
        await r.personal_rule(owner, definition("Bad", channel_api(), action))  # type: ignore[arg-type]


async def test_templates_name_fields_by_their_key(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    service = world.master_data
    gross = await service.create_field(r.admin.id, "LA_Brutto", FieldType.AMOUNT)
    note = await service.create_field(r.admin.id, "Notiz", FieldType.TEXT)
    actions = (
        SetTitle("Lohn {{ field.la_brutto }}"),
        SetField(note.id, "{{ field.la_brutto.amount }} {{ field.la_brutto.currency }}"),
        ForceReview("{% if field.notiz %}{{ field.notiz }}{% endif %}"),
    )
    rule = await r.personal_rule(owner, definition("Lohn", channel_api(), *actions))
    assert rule.definition.actions == actions
    # A field that is not text takes its value as it is, not as a template.
    amount = SetField(gross.id, {"amount": "1.00", "currency": "EUR"})
    assert await r.personal_rule(owner, definition("Betrag", channel_api(), amount))


async def test_renaming_a_field_rewrites_the_templates_that_use_it(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    service = world.master_data
    gross = await service.create_field(r.admin.id, "LA_Brutto", FieldType.AMOUNT)
    note = await service.create_field(r.admin.id, "Notiz", FieldType.TEXT)
    await service.create_field(r.admin.id, "LA_Brutto_alt", FieldType.AMOUNT)
    uses = await r.personal_rule(
        owner,
        definition(
            "Lohn",
            channel_api(),
            SetTitle("Lohn {{ field.la_brutto }} {{ field['la_brutto'].amount }}"),
            SetField(note.id, "{% if field.la_brutto_alt %}x{% endif %}{{ field.la_brutto }}"),
        ),
    )
    other = await r.personal_rule(owner, definition("Andere", channel_api(), SetTitle("Scan")))

    await service.change_field(r.admin.id, gross.id, name="Gesamtbrutto")

    changed = await r.rules.get(owner.id, uses.id)
    assert changed.current.number == 2 and changed.current.created_by == r.admin.id
    assert changed.definition.actions == (
        SetTitle("Lohn {{ field.gesamtbrutto }} {{ field.gesamtbrutto.amount }}"),
        # Another field whose key begins the same stays.
        SetField(note.id, "{% if field.la_brutto_alt %}x{% endif %}{{ field.gesamtbrutto }}"),
    )
    assert (await r.rules.get(owner.id, other.id)).current.number == 1


async def test_a_field_a_template_uses_is_not_deleted(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    service = world.master_data
    gross = await service.create_field(r.admin.id, "LA_Brutto", FieldType.AMOUNT)
    rule = await r.personal_rule(
        owner, definition("Lohn", channel_api(), ForceReview("{{ field.la_brutto.amount }}"))
    )
    with pytest.raises(ConflictError, match=r"field\.la_brutto is used by .*'Lohn'"):
        await service.delete_field(r.admin.id, gross.id)
    await r.rules.delete(owner.id, rule.id)
    await service.delete_field(r.admin.id, gross.id)


async def test_a_pattern_is_checked_by_the_matcher_that_runs_it(world: World) -> None:
    """Of the `regex` package, which knows Unicode properties that `re` refuses."""
    r = await rule_world(world)
    rules = RuleService(world.uow, world.clock, TEMPLATES, RegexPatternMatcher(0.2))
    admin = r.admin.id
    street = await r.tag("Street")
    accepted = definition("Umlauts", text_matches(r"\p{L}+straße"), AddTags(frozenset({street.id})))
    rule = await rules.create(admin, RuleScope.GLOBAL, accepted)
    assert rule.definition == accepted
    with pytest.raises(ValidationError, match="invalid pattern"):
        broken = definition("Broken", text_matches("("), AddTags(frozenset({street.id})))
        await rules.create(admin, RuleScope.GLOBAL, broken)
    with pytest.raises(ValidationError, match="invalid pattern"):
        broken = definition("Broken", text_matches("[a-"), AddTags(frozenset({street.id})))
        await rules.change(admin, rule.id, broken)


async def test_an_admin_lists_the_rules_of_any_space(world: World) -> None:
    r = await rule_world(world)
    editor = await world.user()
    household = await world.spaces.create(editor.id, "Household")
    rule = await r.space_rule(
        editor, household.id, definition("Tag", channel_api(), ForceReview("x"))
    )
    listed = await r.rules.list_rules(r.admin.id, space=household.id)
    assert [item.id for item in listed] == [rule.id]
    assert await r.rules.list_rules((await world.user()).id, space=household.id) == []


async def test_a_rule_moves_between_spaces_and_global(world: World) -> None:
    """Tobi, 22.10.2026: a change may move a rule; the mover changes it where it is and edits
    where it goes (global: admins); the history shows the move."""
    r = await rule_world(world)
    editor, other = await world.user(), await world.user()
    household = await world.spaces.create(editor.id, "Household")
    archive = await world.spaces.create(editor.id, "Archive")
    foreign = await world.spaces.create(other.id, "Foreign")
    await world.spaces.set_member(other.id, foreign.id, editor.id, SpaceRole.READ)
    title = definition("Title", channel_api(), SetTitle("Scan"))
    rule = await r.space_rule(editor, household.id, title)

    moved = await r.rules.change(editor.id, rule.id, title, scope=RuleScope.SPACE, space=archive.id)
    assert (moved.scope, moved.space_id, moved.current.number) == (
        RuleScope.SPACE,
        archive.id,
        2,
    )
    with pytest.raises(PermissionDeniedError):  # reads the space only
        await r.rules.change(editor.id, rule.id, title, scope=RuleScope.SPACE, space=foreign.id)
    with pytest.raises(PermissionDeniedError, match="only admins"):
        await r.rules.change(editor.id, rule.id, title, scope=RuleScope.GLOBAL)
    with pytest.raises(ValidationError, match="give the scope"):
        await r.rules.change(editor.id, rule.id, title, space=household.id)
    global_ = await r.rules.change(r.admin.id, rule.id, title, scope=RuleScope.GLOBAL)
    assert (global_.scope, global_.space_id) == (RuleScope.GLOBAL, None)
    with pytest.raises(PermissionDeniedError, match="only admins change global rules"):
        await r.rules.change(editor.id, rule.id, title, scope=RuleScope.SPACE)
    back = await r.rules.change(r.admin.id, rule.id, title, scope=RuleScope.SPACE)
    assert back.space_id == (await world.personal_space(r.admin)).id
    versions = await r.rules.versions(r.admin.id, rule.id)
    assert [version.space_id for version in versions] == [
        household.id,
        archive.id,
        None,
        back.space_id,
    ]
    assert [version.created_by for version in versions] == [
        editor.id,
        editor.id,
        r.admin.id,
        r.admin.id,
    ]
    # Without a scope it stays where it is.
    assert (await r.rules.change(r.admin.id, rule.id, title)).space_id == back.space_id


async def test_a_rule_is_saved_switched_off_in_one_go(world: World) -> None:
    """Issue #73: the editor saves new and changed rules switched off, to try them first; one
    transaction, so a rule never runs in between."""
    r = await rule_world(world)
    owner = await world.user()
    title = definition("Title", channel_api(), SetTitle("Scan"))
    created = await r.rules.create(owner.id, RuleScope.SPACE, title, enabled=False)
    assert not created.enabled
    assert not (await r.rules.get(owner.id, created.id)).enabled
    on = await r.rules.set_enabled(owner.id, created.id, True)
    changed = await r.rules.change(owner.id, on.id, title, enabled=False)
    assert (changed.enabled, changed.current.number) == (False, 2)
    # Without `enabled` it stays as it is; with True it is switched on with the change.
    assert not (await r.rules.change(owner.id, on.id, title)).enabled
    assert (await r.rules.change(owner.id, on.id, title, enabled=True)).enabled
