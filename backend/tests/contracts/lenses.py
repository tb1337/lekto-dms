"""Contract suite for `LensRepository` in the unit of work: a user's lenses."""

from datetime import date
from typing import Any

import pytest

from lekto.core.domain.errors import ConcurrencyError, ConflictError, NotFoundError
from lekto.core.domain.ids import (
    ContactId,
    DocumentTypeId,
    FieldId,
    SpaceId,
    TagId,
    new_id,
)
from lekto.core.domain.lenses import (
    Grouping,
    Layout,
    Lens,
    LensChanges,
    LensFilter,
    LensSort,
    RelativePeriod,
)
from lekto.core.domain.users import User
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from tests import builders
from tests.builders import HOUR, NOW
from tests.contracts.unit_of_work import a_user


def a_lens(owner: User, name: str = "To pay", position: int = 0, **parts: Any) -> Lens:
    lens = Lens.create(owner_id=owner.id, name=name, position=position, now=NOW)
    if parts:
        lens.change(LensChanges(**parts), now=NOW)
    return lens


class LensRepositoryContract:
    async def test_a_lens_round_trips_with_all_its_parts(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner = await a_user(uow_factory)
        due, total = FieldId(new_id()), FieldId(new_id())
        lens = a_lens(
            owner,
            filter=LensFilter(
                contact_ids=(ContactId(new_id()), ContactId(new_id())),
                document_type_ids=(DocumentTypeId(new_id()),),
                contact_group_ids=(TagId(new_id()),),
                document_type_group_ids=(TagId(new_id()),),
                topic_ids=(TagId(new_id()),),
                tag_ids=(TagId(new_id()), TagId(new_id())),
                space_ids=(SpaceId(new_id()),),
                field_id=total,
                date_from=date(2026, 1, 1),
                date_to=date(2026, 12, 31),
            ),
            sort=LensSort.FIELD,
            sort_field_id=due,
            grouping=Grouping.DUE,
            layout=Layout.LIST,
            card_field_ids=(total, due),
            due_field_id=due,
        )
        moving = a_lens(
            owner,
            "This year",
            1,
            filter=LensFilter(relative_period=RelativePeriod.THIS_YEAR),
            query="electricity bill",
            sort=LensSort.RELEVANCE,
        )
        async with uow_factory() as uow:
            await uow.lenses.add(lens)
            await uow.lenses.add(moving)
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.lenses.get(lens.id) == lens
            assert await uow.lenses.find(moving.id) == moving

    async def test_a_missing_lens_is_not_found(self, uow_factory: UnitOfWorkFactory) -> None:
        missing = a_lens(builders.user())
        async with uow_factory() as uow:
            assert await uow.lenses.find(missing.id) is None
            with pytest.raises(NotFoundError):
                await uow.lenses.get(missing.id)
            with pytest.raises(NotFoundError):
                await uow.lenses.remove(missing.id)

    async def test_names_are_unique_per_owner_regardless_of_case(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner, other = await a_user(uow_factory), await a_user(uow_factory)
        async with uow_factory() as uow:
            await uow.lenses.add(a_lens(owner, "To pay"))
            await uow.lenses.add(a_lens(other, "To pay"))
            await uow.commit()
        with pytest.raises(ConflictError):
            async with uow_factory() as uow:
                await uow.lenses.add(a_lens(owner, "to PAY"))
                await uow.commit()
        async with uow_factory() as uow:
            renamed = a_lens(owner, "Tax")
            await uow.lenses.add(renamed)
            await uow.commit()
        with pytest.raises(ConflictError):
            async with uow_factory() as uow:
                stored = await uow.lenses.get(renamed.id)
                stored.change(LensChanges(name="TO PAY"), now=NOW + HOUR)
                await uow.lenses.update(stored)
                await uow.commit()

    async def test_a_users_lenses_by_position(self, uow_factory: UnitOfWorkFactory) -> None:
        owner, other = await a_user(uow_factory), await a_user(uow_factory)
        second, first, third = a_lens(owner, "b", 1), a_lens(owner, "a", 0), a_lens(owner, "c", 2)
        async with uow_factory() as uow:
            for lens in (second, first, third, a_lens(other, "theirs")):
                await uow.lenses.add(lens)
            await uow.commit()
        async with uow_factory() as uow:
            listed = await uow.lenses.list_for_owner(owner.id)
            assert [lens.name for lens in listed] == ["a", "b", "c"]
            assert await uow.lenses.remove_for_owner(owner.id) == 3
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.lenses.list_for_owner(owner.id) == []
            assert [lens.name for lens in await uow.lenses.list_for_owner(other.id)] == ["theirs"]

    async def test_update_checks_the_version_and_remove_deletes(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner = await a_user(uow_factory)
        lens = a_lens(owner)
        async with uow_factory() as uow:
            await uow.lenses.add(lens)
            await uow.commit()
        async with uow_factory() as first, uow_factory() as second:
            one, other = await first.lenses.get(lens.id), await second.lenses.get(lens.id)
            one.change(LensChanges(name="first"), now=NOW + HOUR)
            await first.lenses.update(one)
            await first.commit()
            other.change(LensChanges(name="second"), now=NOW + HOUR)
            with pytest.raises(ConcurrencyError):
                await second.lenses.update(other)
                await second.commit()
        async with uow_factory() as uow:
            stored = await uow.lenses.get(lens.id)
            assert (stored.name, stored.version) == ("first", 2)
            await uow.lenses.remove(lens.id)
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.lenses.find(lens.id) is None
