"""A user's lenses: creating, changing, ordering and deleting them.

A lens belongs to its owner alone; nobody else, admins included, learns that it exists
(NotFoundError). The fields it names are checked when it is saved: the card fields must exist,
the deadline must be a date field, the sort field one a list sorts by. What it names may be
deleted after; when a lens is handed out, what is gone is dropped (a sort or a grouping that
needed it falls back to the default), so a lens never fails for it. Lenses are settings: no
events.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from uuid import UUID

from lekto.core.domain.errors import ConflictError, NotFoundError, ValidationError
from lekto.core.domain.fields import SORTABLE_TYPES, FieldDefinition, FieldType
from lekto.core.domain.ids import FieldId, LensId, TagId, UserId
from lekto.core.domain.lenses import UNSET, Grouping, Lens, LensChanges
from lekto.core.domain.periods import Period
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.users import User
from lekto.core.ports.clock import Clock
from lekto.core.ports.repository import DocumentFilter
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import (
    check_fact_filter,
    field_definitions,
    load_actor,
    of_a_person,
)

MAX_LENSES = 100
"""Lenses a user has at most."""


class LensService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def list_lenses(self, actor: UserId) -> list[Lens]:
        """The caller's lenses in their order."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            lenses = await uow.lenses.list_for_owner(user.id)
            existing = await _existing(uow, user)
        return [existing.prune(lens) for lens in lenses]

    def documents_of(self, lens: Lens) -> DocumentFilter:
        """The filter of the documents list that `lens` holds, as of today in UTC (the web UI
        reckons a relative period in the viewer's time zone); its words are `lens.query`."""
        chosen = lens.filter
        if chosen.relative_period is not None:
            period = chosen.relative_period.period(self._clock.now().date())
        elif chosen.date_from is None and chosen.date_to is None:
            period = None
        else:
            period = Period(chosen.date_from or date.min, chosen.date_to or date.max)
        return DocumentFilter(
            contacts=frozenset(chosen.contact_ids) or None,
            document_types=frozenset(chosen.document_type_ids) or None,
            tags=tuple(frozenset({tag}) for tag in chosen.tag_ids),
            contact_groups=_either(chosen.contact_group_ids),
            document_type_groups=_either(chosen.document_type_group_ids),
            topics=frozenset(chosen.topic_ids) or None,
            spaces=frozenset(chosen.space_ids) or None,
            field=chosen.field_id,
            document_dates=period,
            facts=chosen.facts,
        )

    async def get(self, actor: UserId, id: LensId) -> Lens:
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            lens = await _own(uow, user, id)
            return (await _existing(uow, user)).prune(lens)

    async def create(self, actor: UserId, name: str, changes: LensChanges) -> Lens:
        """A new lens at the end of the caller's. ValidationError for parts that do not fit or
        fields that do not (see the module), ConflictError for a name the caller has already
        or more than `MAX_LENSES`."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            lenses = await uow.lenses.list_for_owner(user.id)
            if len(lenses) >= MAX_LENSES:
                raise ConflictError(because(ReasonCode.LENSES_LIMIT, max=MAX_LENSES))
            position = max((lens.position for lens in lenses), default=-1) + 1
            now = self._clock.now()
            lens = Lens.create(owner_id=user.id, name=name, position=position, now=now)
            lens.change(changes, now=now)
            _check_fields(lens, await field_definitions(uow))
            check_fact_filter(user, DocumentFilter(facts=lens.filter.facts))
            await uow.lenses.add(lens)
            await uow.commit()
            return lens

    async def update(self, actor: UserId, id: LensId, changes: LensChanges) -> Lens:
        """Change what `changes` sets, on the lens without what is gone; errors as `create`."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            existing = await _existing(uow, user)
            lens = existing.prune(await _own(uow, user, id))
            lens.change(changes, now=self._clock.now())
            _check_fields(lens, existing.fields)
            check_fact_filter(user, DocumentFilter(facts=lens.filter.facts))
            await uow.lenses.update(lens)
            await uow.commit()
            return lens

    async def delete(self, actor: UserId, id: LensId) -> None:
        async with self._uow() as uow:
            lens = await _own(uow, await load_actor(uow, actor), id)
            await uow.lenses.remove(lens.id)
            await uow.commit()

    async def reorder(self, actor: UserId, ids: Sequence[LensId]) -> list[Lens]:
        """Put the caller's lenses in the order of `ids`, which must name each of them once
        (ValidationError otherwise)."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            lenses = {lens.id: lens for lens in await uow.lenses.list_for_owner(user.id)}
            if len(ids) != len(set(ids)) or set(ids) != set(lenses):
                raise ValidationError("ids: each of the caller's lenses once")
            now = self._clock.now()
            for position, id in enumerate(ids):
                lens = lenses[id]
                if lens.position != position:
                    lens.position = position
                    lens.updated_at = now
                    await uow.lenses.update(lens)
            existing = await _existing(uow, user)
            await uow.commit()
            return [existing.prune(lenses[id]) for id in ids]


async def _own(uow: UnitOfWork, user: User, id: LensId) -> Lens:
    lens = await uow.lenses.find(id)
    if lens is None or lens.owner_id != user.id:
        raise NotFoundError("lens", id)
    return lens


def _check_fields(lens: Lens, definitions: dict[FieldId, FieldDefinition]) -> None:
    """ValidationError unless the fields the lens names exist, its deadline is a date field and
    its sort field one a list sorts by."""
    for id in lens.card_field_ids:
        if id not in definitions:
            raise ValidationError(because(ReasonCode.CARD_FIELD_UNKNOWN, id=str(id)))
    due = None if lens.due_field_id is None else definitions.get(lens.due_field_id)
    if lens.due_field_id is not None and (due is None or due.data_type is not FieldType.DATE):
        raise ValidationError(because(ReasonCode.DUE_FIELD_NOT_DATE))
    sorted_by = None if lens.sort_field_id is None else definitions.get(lens.sort_field_id)
    if lens.sort_field_id is not None and (
        sorted_by is None or sorted_by.data_type not in SORTABLE_TYPES
    ):
        raise ValidationError(because(ReasonCode.SORT_FIELD_INVALID))


@dataclass(frozen=True)
class _Existing:
    """What a lens may name that is there: master data, spaces, fields with their types."""

    contacts: frozenset[UUID]
    document_types: frozenset[UUID]
    tags: frozenset[UUID]
    spaces: frozenset[UUID]
    fields: dict[FieldId, FieldDefinition]
    admin: bool = False  # a person's facts only an admin's lens keeps

    def prune(self, lens: Lens) -> Lens:
        """`lens` without what is gone (not stored)."""
        filter = lens.filter
        kept = replace(
            filter,
            contact_ids=tuple(id for id in filter.contact_ids if id in self.contacts),
            document_type_ids=tuple(
                id for id in filter.document_type_ids if id in self.document_types
            ),
            contact_group_ids=tuple(id for id in filter.contact_group_ids if id in self.tags),
            document_type_group_ids=tuple(
                id for id in filter.document_type_group_ids if id in self.tags
            ),
            topic_ids=tuple(id for id in filter.topic_ids if id in self.tags),
            tag_ids=tuple(id for id in filter.tag_ids if id in self.tags),
            space_ids=tuple(id for id in filter.space_ids if id in self.spaces),
            field_id=filter.field_id if filter.field_id in self.fields else None,
            facts=tuple(item for item in filter.facts if self.admin or not of_a_person(item)),
        )
        due = self.fields.get(lens.due_field_id) if lens.due_field_id else None
        due_kept = due is not None and due.data_type is FieldType.DATE
        sorted_by = self.fields.get(lens.sort_field_id) if lens.sort_field_id else None
        sort_kept = sorted_by is not None and sorted_by.data_type in SORTABLE_TYPES
        changes = LensChanges(
            filter=kept if kept != filter else UNSET,
            card_field_ids=tuple(id for id in lens.card_field_ids if id in self.fields),
            due_field_id=UNSET if due_kept or lens.due_field_id is None else None,
            grouping=Grouping.NONE if lens.grouping is Grouping.DUE and not due_kept else UNSET,
            sort=None if lens.sort_field_id is not None and not sort_kept else UNSET,
            sort_field_id=None if lens.sort_field_id is not None and not sort_kept else UNSET,
        )
        pruned = replace(lens)
        pruned.change(changes, now=lens.updated_at)
        return pruned


async def _existing(uow: UnitOfWork, user: User) -> _Existing:
    """What a lens of `user` may still name: the spaces among it only those they see (every
    one for an admin)."""
    spaces = (
        await uow.spaces.list_all()
        if user.is_active_admin
        else await uow.spaces.list_accessible(user.id)
    )
    return _Existing(
        contacts=frozenset(item.id for item in await uow.contacts.list_all()),
        document_types=frozenset(item.id for item in await uow.document_types.list_all()),
        tags=frozenset(item.id for item in await uow.tags.list_all()),
        spaces=frozenset(space.id for space in spaces),
        fields=await field_definitions(uow),
        admin=user.is_active_admin,
    )


def _either(groups: tuple[TagId, ...]) -> tuple[frozenset[TagId], ...]:
    """Groups of a lens as a filter takes them: one set, any of them."""
    return (frozenset(groups),) if groups else ()
