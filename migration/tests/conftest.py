import asyncio
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest

from lekto_migration import fake_paperless
from lekto_migration import plan as plans
from lekto_migration.cli import execute
from lekto_migration.config import Config
from lekto_migration.fake_paperless import Archive, FakePaperless, sample_archive
from tests import fake_lekto
from tests.fake_lekto import FakeLekto

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
TODAY = date(2026, 10, 21)


@dataclass
class Setup:
    directory: Path
    archive: Archive
    paperless: FakePaperless
    lekto: FakeLekto
    messages: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    answer: bool = True  # what the person answers when asked

    @property
    def plan_path(self) -> Path:
        return self.directory / "migration-plan.yaml"

    def config(self, **changes: object) -> Config:
        values: dict[str, object] = {
            "paperless_url": "http://paperless",
            "lekto_url": "http://lekto",
            "state": self.directory / "state.sqlite",
            "report_dir": self.directory / "reports",
            "plan": self.plan_path,
            "paperless_token": fake_paperless.TOKEN,
            "lekto_token": fake_lekto.TOKEN,
            "concurrency": 3,
        }
        return Config(**{**values, **changes})  # type: ignore[arg-type]

    def ask(self, question: str) -> bool:
        self.questions.append(question)
        return self.answer

    async def run(
        self, command: str, *, stop: asyncio.Event | None = None, **changes: object
    ) -> int:
        return await execute(
            self.config(**changes),
            command,
            stop=stop,
            paperless_transport=self.paperless.transport(),
            lekto_transport=self.lekto.transport(),
            progress=self.messages.append,
            ask=self.ask,
            poll=(0.0, 0.0),
            delays=(0.0, 0.0, 0.0),
            today=TODAY,
        )

    async def migrate(self, **changes: Any) -> int:
        """plan (once), prepare and run; the code of the first that is not fine, else run's."""
        if not self.plan_path.exists():
            code = await self.run("plan", **changes)
            if code != 0:
                return code
        for command in ("prepare", "run"):
            code = await self.run(command, **changes)
            if code != 0 or command == "run":
                return code
        raise AssertionError("unreachable")

    def edit(self, section: str, name: str, entry: str) -> None:
        """Change one entry of the plan (YAML of the entry), as a person would."""
        document = plans.yaml().load(self.plan_path.read_text())
        value = plans.yaml().load(f"x: {entry}")["x"]
        if section in (plans.ASN, "settings"):
            if section == "settings":
                document["settings"][name] = value
            else:
                document[plans.ASN] = value
        else:
            document[section][name] = value
        plans.dump(document, self.plan_path)

    def report(self, command: str) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            json.loads((self.directory / "reports" / f"{command}.json").read_text()),
        )


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    archive = sample_archive(PDF)
    return Setup(tmp_path, archive, FakePaperless(archive), FakeLekto())
