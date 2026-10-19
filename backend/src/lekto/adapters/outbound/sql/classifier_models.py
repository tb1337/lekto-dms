"""The trained classifiers in `classifier_models`."""

from typing import Any

from sqlalchemy import Row, select

from lekto.adapters.outbound.sql import tables as t
from lekto.adapters.outbound.sql.repositories import SqlRepository, Values
from lekto.core.domain.classifier import ClassifierModel
from lekto.core.domain.ids import ClassifierModelId


class SqlClassifierModelRepository(SqlRepository[ClassifierModelId, ClassifierModel]):
    kind = "classifier model"
    table = t.classifier_models

    async def latest(self) -> ClassifierModel | None:
        rows = (
            await self._tx.read(select(self.table).order_by(self.table.c.number.desc()).limit(1))
        ).all()
        return self._entity(rows[0]) if rows else None

    async def list_all(self) -> list[ClassifierModel]:
        rows = (await self._tx.read(select(self.table).order_by(self.table.c.number.desc()))).all()
        return [self._entity(row) for row in rows]

    def _entity(self, row: Row[Any]) -> ClassifierModel:
        return ClassifierModel(
            id=ClassifierModelId(row.id),
            number=row.number,
            trained_at=row.trained_at,
            examples=row.examples,
            examples_until=row.examples_until,
            object_key=row.object_key,
            summary=row.summary,
            version=row.version,
        )

    def _values(self, entity: ClassifierModel) -> Values:
        return {
            "id": entity.id,
            "number": entity.number,
            "trained_at": entity.trained_at,
            "examples": entity.examples,
            "examples_until": entity.examples_until,
            "object_key": entity.object_key,
            "summary": entity.summary,
            "version": entity.version,
        }
