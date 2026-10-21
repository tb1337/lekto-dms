"""The sample archive, a Lekto that has nothing but its admin, and the first plan, for tests
of the plan's application; entries and settings are replaced by YAML snippets."""

from datetime import UTC, datetime
from typing import Any

from lekto_migration import plan as plans
from lekto_migration.directory import Directory
from lekto_migration.expect import Context, Expected, expect, field_infos
from lekto_migration.fake_paperless import Archive, sample_archive
from lekto_migration.paperless import Snapshot
from lekto_migration.survey import draft
from tests.conftest import PDF

NOW = datetime(2026, 10, 21, tzinfo=UTC)


class World:
    """What the plan is applied to, and the plan."""

    def __init__(self) -> None:
        self.archive: Archive = sample_archive(PDF)
        self.directory = Directory({"id": "admin", "username": "root"})
        self.changes: dict[str, dict[str, str]] = {}
        self.settings: dict[str, Any] = {}
        self.inactive: frozenset[str] = frozenset()

    def snapshot(self) -> Snapshot:
        a = self.archive
        return Snapshot(
            "3.3.0",
            a.users,
            a.groups,
            a.correspondents,
            a.document_types,
            a.tags,
            a.custom_fields,
            a.storage_paths,
            a.documents,
        )

    def set(self, section: str, name: str, entry: str) -> "World":
        self.changes.setdefault(section, {})[name] = entry
        return self

    def plan(self) -> plans.Plan:
        document = draft(self.snapshot(), self.directory, source="p", target="l")
        for section, entries in self.changes.items():
            for name, entry in entries.items():
                value = plans.yaml().load(f"x: {entry}")["x"]
                if section == plans.ASN:
                    document[plans.ASN] = value
                else:
                    document[section][name] = value
        for key, value in self.settings.items():
            document["settings"][key] = value
        return plans.parse(document)

    def expect(self, id: int) -> Expected:
        plan = self.plan()
        context = Context(
            plan=plan,
            snapshot=self.snapshot(),
            fields=field_infos(plan, self.directory, self.snapshot()),
            admin="root",
            inactive=self.inactive,
            now=NOW,
        )
        document = next(d for d in self.archive.documents if d["id"] == id)
        return expect(document, context)

    def document(self, id: int) -> dict[str, Any]:
        return next(d for d in self.archive.documents if d["id"] == id)

    def context(self) -> Context:
        plan = self.plan()
        return Context(
            plan=plan,
            snapshot=self.snapshot(),
            fields=field_infos(plan, self.directory, self.snapshot()),
            admin=self.directory.admin["username"],
            inactive=self.inactive,
            now=NOW,
        )

    def all(self) -> list[Expected]:
        context = self.context()
        return [expect(document, context) for document in self.archive.documents]
