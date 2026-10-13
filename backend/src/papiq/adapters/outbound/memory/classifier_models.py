"""The trained classifiers, in memory."""

from papiq.adapters.outbound.memory.rows import MemoryRepository
from papiq.core.domain.classifier import ClassifierModel
from papiq.core.domain.ids import ClassifierModelId


class MemoryClassifierModelRepository(MemoryRepository[ClassifierModelId, ClassifierModel]):
    async def latest(self) -> ClassifierModel | None:
        models = await self.list_all()
        return models[0] if models else None

    async def list_all(self) -> list[ClassifierModel]:
        models = [self._copy(row) for row in self._all()]
        return sorted(models, key=lambda model: model.number, reverse=True)

    async def remove(self, id: ClassifierModelId) -> None:
        await self.get(id)
        self._remove_rows([row for row in self._all() if row.id == id])
