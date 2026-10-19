"""The trained classifiers, in memory."""

from lekto.adapters.outbound.memory.rows import MemoryRepository, _copy
from lekto.core.domain.classifier import ClassifierModel
from lekto.core.domain.ids import ClassifierModelId


class MemoryClassifierModelRepository(MemoryRepository[ClassifierModelId, ClassifierModel]):
    async def latest(self) -> ClassifierModel | None:
        models = await self.list_all()
        return models[0] if models else None

    async def list_all(self) -> list[ClassifierModel]:
        models = [_copy(row) for row in self._all()]
        return sorted(models, key=lambda model: model.number, reverse=True)
