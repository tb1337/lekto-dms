"""What the repositories store: entities with an identifier and a version."""

from typing import Protocol
from uuid import UUID


class Entity[K: UUID](Protocol):
    """An entity as a repository keeps it: `id` identifies it, `version` counts its updates for
    optimistic locking (an update checks it and raises it by one)."""

    @property
    def id(self) -> K: ...

    version: int
