"""Lens repository on SQL tables."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Row, delete, select

from lekto.adapters.outbound.sql import tables as t
from lekto.adapters.outbound.sql.repositories import SqlRepository, Values
from lekto.core.domain.ids import (
    ContactId,
    DocumentTypeId,
    FieldId,
    LensId,
    SpaceId,
    TagId,
    UserId,
)
from lekto.core.domain.lenses import Grouping, Layout, Lens, LensFilter, LensSort, RelativePeriod
from lekto.core.domain.validation import name_key


class SqlLensRepository(SqlRepository[LensId, Lens]):
    kind = "lens"
    table = t.lenses

    async def remove_for_owner(self, owner: UserId) -> int:
        result = await self._tx.write(delete(self.table).where(self.table.c.owner_id == owner))
        return int(result.rowcount)

    async def list_for_owner(self, owner: UserId) -> list[Lens]:
        table = self.table
        rows = await self._tx.read(
            select(table)
            .where(table.c.owner_id == owner)
            .order_by(table.c.position, table.c.created_at, table.c.id)
        )
        return [self._entity(row) for row in rows]

    def _entity(self, row: Row[Any]) -> Lens:
        return Lens(
            id=LensId(row.id),
            owner_id=UserId(row.owner_id),
            name=row.name,
            position=row.position,
            filter=_filter(row.filter),
            query=row.query,
            sort=None if row.sort is None else LensSort(row.sort),
            sort_field_id=None if row.sort_field_id is None else FieldId(row.sort_field_id),
            grouping=Grouping(row.grouping),
            layout=Layout(row.layout),
            card_field_ids=tuple(FieldId(UUID(id)) for id in row.card_field_ids),
            due_field_id=None if row.due_field_id is None else FieldId(row.due_field_id),
            created_at=row.created_at,
            updated_at=row.updated_at,
            version=row.version,
        )

    def _values(self, entity: Lens) -> Values:
        return {
            "id": entity.id,
            "owner_id": entity.owner_id,
            "name": entity.name,
            "name_key": name_key(entity.name),
            "position": entity.position,
            "filter": _filter_json(entity.filter),
            "query": entity.query,
            "sort": None if entity.sort is None else entity.sort.value,
            "sort_field_id": entity.sort_field_id,
            "grouping": entity.grouping.value,
            "layout": entity.layout.value,
            "card_field_ids": [str(id) for id in entity.card_field_ids],
            "due_field_id": entity.due_field_id,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
            "version": entity.version,
        }


_LISTS = (
    "contact_ids",
    "document_type_ids",
    "contact_group_ids",
    "document_type_group_ids",
    "topic_ids",
    "tag_ids",
    "space_ids",
)


def _filter_json(filter: LensFilter) -> dict[str, Any]:
    """The filter as JSON: the lists of ids as text, the days in ISO."""
    return {
        **{name: [str(id) for id in getattr(filter, name)] for name in _LISTS},
        "field_id": None if filter.field_id is None else str(filter.field_id),
        "date_from": None if filter.date_from is None else filter.date_from.isoformat(),
        "date_to": None if filter.date_to is None else filter.date_to.isoformat(),
        "relative_period": None if filter.relative_period is None else filter.relative_period.value,
    }


def _filter(data: dict[str, Any]) -> LensFilter:
    def ids(name: str) -> tuple[UUID, ...]:
        return tuple(UUID(id) for id in data.get(name, ()))

    def day(name: str) -> date | None:
        value = data.get(name)
        return None if value is None else date.fromisoformat(value)

    relative = data.get("relative_period")
    field = data.get("field_id")
    return LensFilter(
        contact_ids=tuple(ContactId(id) for id in ids("contact_ids")),
        document_type_ids=tuple(DocumentTypeId(id) for id in ids("document_type_ids")),
        contact_group_ids=tuple(TagId(id) for id in ids("contact_group_ids")),
        document_type_group_ids=tuple(TagId(id) for id in ids("document_type_group_ids")),
        topic_ids=tuple(TagId(id) for id in ids("topic_ids")),
        tag_ids=tuple(TagId(id) for id in ids("tag_ids")),
        space_ids=tuple(SpaceId(id) for id in ids("space_ids")),
        field_id=None if field is None else FieldId(UUID(field)),
        date_from=day("date_from"),
        date_to=day("date_to"),
        relative_period=None if relative is None else RelativePeriod(relative),
    )
