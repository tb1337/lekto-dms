"""Lekto's master data by kind and name, as the plan names it: users by user name, contacts,
document types and fields by name, tags by scope and name (names are unique per scope), and
the spaces by owner. Names are compared without case, as Lekto does."""

from dataclasses import dataclass, field
from typing import Any

from lekto_migration.lekto import Lekto
from lekto_migration.plan import TAG_SCOPES, norm

SCOPES = ("document", "topic", "contact", "document_type")


@dataclass
class Directory:
    admin: dict[str, Any]  # the executing admin
    users: dict[str, dict[str, Any]] = field(default_factory=dict)
    contacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    document_types: dict[str, dict[str, Any]] = field(default_factory=dict)
    tags: dict[str, dict[str, dict[str, Any]]] = field(
        default_factory=lambda: {scope: {} for scope in SCOPES}
    )
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    spaces: list[dict[str, Any]] = field(default_factory=list)
    read: bool = False  # False: no Lekto was read (a plan without a Lekto key); all is new

    @classmethod
    async def of(cls, lekto: Lekto | None, admin: dict[str, Any] | None = None) -> "Directory":
        if lekto is None:
            return cls(admin or {"id": "admin", "username": "admin"})
        directory = cls(admin or (await lekto.me())["user"], read=True)
        for user in await lekto.items("/users"):
            directory.users[norm(user["username"])] = user
        for contact in await lekto.items("/contacts"):
            directory.contacts[norm(contact["name"])] = contact
        for document_type in await lekto.items("/document-types"):
            directory.document_types[norm(document_type["name"])] = document_type
        for tag in await lekto.items("/tags"):
            scope = tag.get("scope", "document")
            directory.tags.setdefault(scope, {})[norm(tag["name"])] = tag
        for item in await lekto.items("/fields"):
            directory.fields[norm(item["name"])] = item
        directory.spaces = await lekto.items("/spaces")
        directory.users.setdefault(norm(directory.admin["username"]), directory.admin)
        return directory

    def _store(self, to: str) -> dict[str, dict[str, Any]] | None:
        if to in TAG_SCOPES:
            return self.tags.setdefault(TAG_SCOPES[to], {})
        return {
            "user": self.users,
            "contact": self.contacts,
            "document_type": self.document_types,
            "field": self.fields,
        }.get(to)

    def find(self, to: str, name: str) -> dict[str, Any] | None:
        """The Lekto object a target names, or None."""
        store = self._store(to)
        return None if store is None else store.get(norm(name))

    def add(self, to: str, item: dict[str, Any]) -> None:
        """Remember an object `prepare` created."""
        store = self._store(to)
        if store is not None:
            store[norm(item.get("username") or item["name"])] = item

    def by_id(self, to: str, id: str) -> dict[str, Any] | None:
        store = self._store(to)
        return None if store is None else next((i for i in store.values() if i["id"] == id), None)

    def space(self, owner_id: str, name: str) -> dict[str, Any] | None:
        return next(
            (s for s in self.spaces if s["owner_id"] == owner_id and norm(s["name"]) == norm(name)),
            None,
        )

    def default_space(self, owner_id: str) -> dict[str, Any] | None:
        return next(
            (s for s in self.spaces if s["owner_id"] == owner_id and s.get("is_default")), None
        )
