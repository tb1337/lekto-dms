"""In-memory lens repository, on the tables of the in-memory unit of work."""

from lekto.adapters.outbound.memory.rows import MemoryRepository, _copy
from lekto.core.domain.ids import LensId, UserId
from lekto.core.domain.lenses import Lens


class MemoryLensRepository(MemoryRepository[LensId, Lens]):
    async def remove_for_owner(self, owner: UserId) -> int:
        return self._remove_rows([row for row in self._all() if row.owner_id == owner])

    async def list_for_owner(self, owner: UserId) -> list[Lens]:
        rows = [row for row in self._all() if row.owner_id == owner]
        rows.sort(key=lambda lens: (lens.position, lens.created_at, lens.id))
        return [_copy(row) for row in rows]
