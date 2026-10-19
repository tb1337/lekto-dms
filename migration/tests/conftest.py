import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

from lekto_migration import fake_paperless
from lekto_migration.cli import execute
from lekto_migration.config import Config
from lekto_migration.fake_paperless import Archive, FakePaperless, sample_archive
from tests import fake_lekto
from tests.fake_lekto import FakeLekto

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@dataclass
class Setup:
    directory: Path
    archive: Archive
    paperless: FakePaperless
    lekto: FakeLekto
    messages: list[str] = field(default_factory=list)

    def config(self, **changes: object) -> Config:
        values: dict[str, object] = {
            "paperless_url": "http://paperless",
            "lekto_url": "http://lekto",
            "state": self.directory / "state.sqlite",
            "report_dir": self.directory / "reports",
            "paperless_token": fake_paperless.TOKEN,
            "lekto_token": fake_lekto.TOKEN,
            "concurrency": 3,
        }
        return Config(**{**values, **changes})  # type: ignore[arg-type]

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
            poll=(0.0, 0.0),
            delays=(0.0, 0.0, 0.0),
        )

    def report(self, command: str) -> dict[str, Any]:
        import json

        return cast(
            "dict[str, Any]",
            json.loads((self.directory / "reports" / f"{command}.json").read_text()),
        )


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    archive = sample_archive(PDF)
    return Setup(tmp_path, archive, FakePaperless(archive), FakeLekto())
