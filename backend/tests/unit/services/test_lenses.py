"""A user's lenses: their own alone, checked fields, an order, and what is gone left out."""

import pytest

from lekto.core.domain.errors import ConflictError, NotFoundError, ValidationError
from lekto.core.domain.fields import FieldType
from lekto.core.domain.ids import FieldId, new_id
from lekto.core.domain.lenses import Grouping, LensChanges, LensFilter, LensSort
from lekto.core.domain.master_data import TagScope
from lekto.core.domain.spaces import SpaceRole
from lekto.core.domain.users import Role
from lekto.core.services.lenses import MAX_LENSES
from tests.unit.services.support import World


async def test_a_user_creates_lenses_one_after_another(world: World) -> None:
    user = await world.user()
    first = await world.lenses.create(user.id, "To pay", LensChanges())
    second = await world.lenses.create(user.id, "Tax", LensChanges(query="tax office"))
    assert (first.position, second.position) == (0, 1)
    listed = await world.lenses.list_lenses(user.id)
    assert [lens.name for lens in listed] == ["To pay", "Tax"]
    with pytest.raises(ConflictError):
        await world.lenses.create(user.id, "TAX", LensChanges())


async def test_a_lens_is_its_owners_alone(world: World) -> None:
    owner, other = await world.user(), await world.user()
    admin = await world.user(role=Role.ADMIN)
    lens = await world.lenses.create(owner.id, "To pay", LensChanges())
    for stranger in (other, admin):
        with pytest.raises(NotFoundError):
            await world.lenses.get(stranger.id, lens.id)
        with pytest.raises(NotFoundError):
            await world.lenses.update(stranger.id, lens.id, LensChanges(name="mine"))
        with pytest.raises(NotFoundError):
            await world.lenses.delete(stranger.id, lens.id)
        assert await world.lenses.list_lenses(stranger.id) == []
    await world.lenses.delete(owner.id, lens.id)
    assert await world.lenses.list_lenses(owner.id) == []


async def test_the_fields_of_a_lens_are_checked(world: World) -> None:
    admin, user = await world.user(role=Role.ADMIN), await world.user()
    due = await world.master_data.create_field(admin.id, "Due", FieldType.DATE)
    total = await world.master_data.create_field(admin.id, "Total", FieldType.AMOUNT)
    note = await world.master_data.create_field(admin.id, "Note", FieldType.TEXT)
    good = LensChanges(
        sort=LensSort.FIELD,
        sort_field_id=total.id,
        grouping=Grouping.DUE,
        due_field_id=due.id,
        card_field_ids=(total.id, due.id, note.id),
    )
    lens = await world.lenses.create(user.id, "To pay", good)
    assert lens.card_field_ids == (total.id, due.id, note.id)
    for bad in (
        LensChanges(due_field_id=total.id),  # not a date
        LensChanges(sort_field_id=note.id),  # text does not sort
        LensChanges(card_field_ids=(FieldId(new_id()),)),  # no such field
    ):
        with pytest.raises(ValidationError):
            await world.lenses.update(user.id, lens.id, bad)
    assert (await world.lenses.get(user.id, lens.id)).due_field_id == due.id


async def test_what_is_gone_is_left_out(world: World) -> None:
    admin, user = await world.user(role=Role.ADMIN), await world.user()
    due = await world.master_data.create_field(admin.id, "Due", FieldType.DATE)
    total = await world.master_data.create_field(admin.id, "Total", FieldType.AMOUNT)
    paid = await world.master_data.create_tag(admin.id, "paid")
    tax = await world.master_data.create_tag(admin.id, "tax")
    group = await world.master_data.create_tag(admin.id, "Bank", scope=TagScope.CONTACT)
    lens = await world.lenses.create(
        user.id,
        "To pay",
        LensChanges(
            filter=LensFilter(tag_ids=(paid.id, tax.id), contact_group_ids=(group.id,)),
            sort=LensSort.FIELD,
            sort_field_id=due.id,
            grouping=Grouping.DUE,
            due_field_id=due.id,
            card_field_ids=(total.id, due.id),
        ),
    )
    await world.master_data.delete_tag(admin.id, paid.id)
    await world.master_data.delete_field(admin.id, due.id)
    shown = await world.lenses.get(user.id, lens.id)
    assert shown.filter.tag_ids == (tax.id,)
    assert shown.filter.contact_group_ids == (group.id,)
    assert shown.card_field_ids == (total.id,)
    assert (shown.sort, shown.sort_field_id, shown.due_field_id) == (None, None, None)
    assert shown.grouping is Grouping.NONE
    # What is stored stays; a change saves what is shown.
    renamed = await world.lenses.update(user.id, lens.id, LensChanges(name="Bills"))
    assert renamed.name == "Bills" and renamed.card_field_ids == (total.id,)


async def test_a_lens_keeps_only_the_spaces_its_owner_sees(world: World) -> None:
    """A space the owner left (or never saw) is left out, as a deleted one (Tobi,
    22.10.2026)."""
    owner, other = await world.user(), await world.user()
    household = await world.spaces.create(other.id, "Household")
    await world.spaces.set_member(other.id, household.id, owner.id, SpaceRole.READ)
    personal = await world.personal_space(owner)
    lens = await world.lenses.create(
        owner.id,
        "Mine",
        LensChanges(filter=LensFilter(space_ids=(personal.id, household.id))),
    )
    assert (await world.lenses.get(owner.id, lens.id)).filter.space_ids == (
        personal.id,
        household.id,
    )
    await world.spaces.remove_member(owner.id, household.id, owner.id)  # leaves it
    assert (await world.lenses.get(owner.id, lens.id)).filter.space_ids == (personal.id,)


async def test_lenses_are_ordered_by_naming_each_once(world: World) -> None:
    user = await world.user()
    a, b, c = [await world.lenses.create(user.id, name, LensChanges()) for name in "abc"]
    ordered = await world.lenses.reorder(user.id, [c.id, a.id, b.id])
    assert [(lens.name, lens.position) for lens in ordered] == [("c", 0), ("a", 1), ("b", 2)]
    assert [lens.name for lens in await world.lenses.list_lenses(user.id)] == ["c", "a", "b"]
    for bad in ([c.id, a.id], [c.id, a.id, b.id, b.id], [c.id, a.id, FieldId(new_id())]):
        with pytest.raises(ValidationError):
            await world.lenses.reorder(user.id, bad)  # type: ignore[arg-type]


async def test_a_user_has_a_limited_number_of_lenses(world: World) -> None:
    user = await world.user()
    for number in range(MAX_LENSES):
        await world.lenses.create(user.id, f"Lens {number}", LensChanges())
    with pytest.raises(ConflictError):
        await world.lenses.create(user.id, "One more", LensChanges())


async def test_lenses_go_with_their_user(world: World) -> None:
    admin, user = await world.user(role=Role.ADMIN), await world.user()
    await world.lenses.create(user.id, "To pay", LensChanges())
    await world.users.delete_user(admin.id, user.id)
    async with world.uow() as uow:
        assert await uow.lenses.list_for_owner(user.id) == []
