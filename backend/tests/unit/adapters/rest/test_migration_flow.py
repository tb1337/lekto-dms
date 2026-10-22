"""The migration client against the real API (in memory), with a stand-in for Paperless: the two
sides agree on every endpoint, field and rule the client relies on."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

import httpx2
from lekto_migration import fake_paperless
from lekto_migration import plan as plans
from lekto_migration.cli import execute
from lekto_migration.config import Config
from lekto_migration.fake_paperless import FakePaperless, sample_archive

from lekto.adapters.inbound.rest import PREFIX
from lekto.core.domain.pipeline import SIGNALS, Node
from lekto.core.services.imports import ImportedFieldsNode, ImportedJudgeNode, ImportedSignal
from tests import api as helpers
from tests.api import until
from tests.builders import SAMPLES, PlaceholderNode
from tests.unit.adapters.rest.support import Api


class Migrating:
    def __init__(self, api: Api, directory: Path, admin: Any) -> None:
        self.api = api
        self.directory = directory
        self.admin = admin
        archive = sample_archive(
            (SAMPLES / "scan.pdf").read_bytes(), (SAMPLES / "photo.jpg").read_bytes()
        )
        self.paperless = FakePaperless(archive)
        self.messages: list[str] = []

    def config(self, **changes: Any) -> Config:
        values: dict[str, Any] = {
            "paperless_url": "http://paperless",
            "lekto_url": "https://lekto",
            "state": self.directory / "state.sqlite",
            "report_dir": self.directory / "reports",
            "plan": self.directory / "migration-plan.yaml",
            "paperless_token": fake_paperless.TOKEN,
            "lekto_token": helpers.token(self.admin),
            "concurrency": 3,
        }
        return Config(**{**values, **changes})

    async def run(self, command: str, *, stop: asyncio.Event | None = None, **changes: Any) -> int:
        return await execute(
            self.config(**changes),
            command,
            stop=stop,
            paperless_transport=self.paperless.transport(),
            lekto_transport=httpx2.ASGITransport(app=self.api.app),
            progress=self.messages.append,
            ask=lambda question: True,
            poll=(0.01, 0.01),
            delays=(0.0, 0.0, 0.0),
            today=date(2026, 10, 21),
        )

    async def migrate(self, **changes: Any) -> int:
        for command in ("plan", "prepare", "run"):
            if command == "plan" and (self.directory / "migration-plan.yaml").exists():
                continue
            code = await self.run(command, **changes)
            if code != 0:
                return code
        return 0

    def edit(self, section: str, name: str, entry: str) -> None:
        path = self.directory / "migration-plan.yaml"
        document = plans.yaml().load(path.read_text())
        document[section][name] = plans.yaml().load(f"x: {entry}")["x"]
        plans.dump(document, path)

    async def documents(self) -> list[dict[str, Any]]:
        response = await self.api.client.get(
            f"{PREFIX}/documents?all_users=true&limit=200", headers=helpers.auth(self.admin)
        )
        assert response.status_code == 200
        return list(response.json()["items"])


@asynccontextmanager
async def migrating(api: Api, directory: Path) -> AsyncIterator[Migrating]:
    """The API with its worker running, an admin to migrate with, and the real signals, judge
    and fields node of a migration around nodes that do nothing (there is no language
    model)."""
    uow = api.container.unit_of_work
    pipeline = api.services.pipeline
    for signal in SIGNALS:
        pipeline.replace_executor(signal, ImportedSignal(uow, PlaceholderNode()))
    pipeline.replace_executor(Node.JUDGE, ImportedJudgeNode(uow, PlaceholderNode()))
    pipeline.replace_executor(Node.FIELDS, ImportedFieldsNode(uow, PlaceholderNode()))
    admin = await api.admin()

    async def work() -> None:
        while True:
            await api.drain()
            await asyncio.sleep(0.005)

    worker = asyncio.create_task(work())
    try:
        yield Migrating(api, directory, admin)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_the_whole_migration_runs_against_the_api(api: Api, tmp_path: Path) -> None:
    async with migrating(api, tmp_path) as m:
        assert await m.run("plan") == 0, m.messages
        assert await m.run("check") == 0, m.messages
        assert await m.documents() == []

        assert await m.run("prepare") == 0, m.messages
        assert await m.run("run") == 0, m.messages
        documents = await m.documents()
        assert len(documents) == 8
        assert {d["lane"] for d in documents} == {"green"}
        assert {d["channel"] for d in documents} == {"migration"}

        users = {
            u["username"]: u
            for u in (await api.client.get(f"{PREFIX}/users", headers=helpers.auth(m.admin))).json()
        }
        assert {"tobias", "anna", "bob", "gone"} <= set(users)
        assert users["gone"]["active"] is False and users["anna"]["role"] == "user"
        by_title = {d["title"]: d for d in documents}
        assert by_title["Document 10"]["uploaded_by"] == users["tobias"]["id"]
        assert by_title["Document 14"]["uploaded_by"] == str(m.admin.id)  # no owner in Paperless
        assert by_title["Document 15"]["uploaded_by"] == str(m.admin.id)  # an owner who is gone
        assert by_title["Document 10"]["document_date"] == "2024-05-01"
        assert len(by_title["Document 10"]["fields"]) == 11  # notes are no longer taken over

        spaces = (
            await api.client.get(
                f"{PREFIX}/spaces", params={"all_users": True}, headers=helpers.auth(m.admin)
            )
        ).json()
        personal = {s["personal_of"]: s for s in spaces if s["personal_of"] is not None}
        # Without further permissions a document goes to its uploader's personal space.
        assert by_title["Document 10"]["space_id"] == personal[users["tobias"]["id"]]["id"]
        shared = next(d for d in spaces if d["name"].startswith("Geteilt"))
        assert shared["personal_of"] is None
        # The uploader and the writers edit, the readers read; the admin is no member.
        assert {(s["user_id"], s["role"]) for s in shared["members"]} == {
            (users["anna"]["id"], "edit"),
            (users["bob"]["id"], "read"),
            (users["tobias"]["id"], "edit"),
        }
        assert by_title["Document 13"]["uploaded_by"] == users["anna"]["id"]
        assert by_title["Document 13"]["space_id"] == shared["id"]
        # Its members see it; a stranger does not.
        bob = await api.user("bob-session")
        assert (
            await api.client.get(
                f"{PREFIX}/documents/{by_title['Document 13']['id']}", headers=helpers.auth(bob)
            )
        ).status_code == 404

        log = (
            await api.client.get(
                f"{PREFIX}/documents/{by_title['Document 10']['id']}/log",
                headers=helpers.auth(m.admin),
            )
        ).json()
        imported = {e["node"]: e for e in log if e["model_version"] == "imported"}
        # Taken over, the document's signals propose nothing and its judge applies the metadata.
        signals = {"signal_llm", "signal_classifier", "signal_neighbours", "signal_facts"}
        assert set(imported) == {"judge", "fields", *signals}
        for signal in signals:  # nothing to propose: they abstain
            assert imported[signal]["output"] == {"abstained": "taken over from the source system"}

        assert await m.run("check") == 0, m.messages
        assert await m.run("check", download=True) == 0, m.messages

        # A second run adds nothing.
        assert await m.run("run") == 0
        assert len(await m.documents()) == 8
        assert len(m.paperless.downloads) == 8 + 8  # the check downloaded the originals again


async def test_reviews_and_the_alignment_run_against_the_api(api: Api, tmp_path: Path) -> None:
    async with migrating(api, tmp_path) as m:
        assert await m.run("plan") == 0
        m.edit("tags", "tax", "{to: tag, name: tax, create: true, review: Check the tag}")
        m.edit(
            "tags",
            "tax/2024",
            "[{to: tag, name: tax/2024, parent: tax, create: true},"
            " {to: topic, name: Taxes, create: true}]",
        )
        assert await m.migrate() == 0, m.messages
        by_title = {d["title"]: d for d in await m.documents()}
        ten = by_title["Document 10"]
        assert (ten["lane"], ten["processing"]["status"]) == ("yellow", "review")
        topics = (
            await api.client.get(f"{PREFIX}/tags?scope=topic", headers=helpers.auth(m.admin))
        ).json()
        (taxes,) = [t for t in topics if t["name"] == "Taxes"]
        # The alignment after the pipeline set the topic and enabled it at the contact; it
        # confirmed nothing.
        assert ten["topic_id"] == taxes["id"] and ten["confirmed_at"] is None
        contact = (
            await api.client.get(
                f"{PREFIX}/contacts/{ten['contact_id']}", headers=helpers.auth(m.admin)
            )
        ).json()
        assert taxes["id"] in contact["topic_ids"]
        log = (
            await api.client.get(
                f"{PREFIX}/documents/{ten['id']}/log", headers=helpers.auth(m.admin)
            )
        ).json()
        judge = next(e for e in log if e["node"] == "judge")
        assert (judge["outcome"], judge["reason"]) == ("uncertain", "Check the tag")
        assert by_title["Document 12"]["lane"] == "green"  # no tax tag

        # A plan changed afterwards aligns what was migrated.
        m.edit("custom_fields", "Count", "drop")
        assert await m.run("check") == 0, m.messages
        assert await m.run("run") == 0, m.messages
        ten = {d["title"]: d for d in await m.documents()}["Document 10"]
        assert len(ten["fields"]) == 10 and ten["topic_id"] == taxes["id"]
        assert await m.run("check") == 0


async def test_a_stopped_run_continues_against_the_api(api: Api, tmp_path: Path) -> None:
    async with migrating(api, tmp_path) as m:
        stop = asyncio.Event()

        async def three() -> bool:
            return len(await m.documents()) >= 3

        async def watch() -> None:
            await until(three, 30, every=0.005, what="three documents")
            stop.set()

        assert await m.run("plan") == 0 and await m.run("prepare") == 0
        watcher = asyncio.create_task(watch())
        assert await m.run("run", stop=stop, concurrency=1) == 130
        await watcher
        partial = len(await m.documents())
        assert 3 <= partial < 8

        assert await m.run("run") == 0
        assert len(await m.documents()) == 8
        assert await m.run("check") == 0


async def test_a_second_state_finds_the_duplicates(api: Api, tmp_path: Path) -> None:
    async with migrating(api, tmp_path) as m:
        assert await m.migrate() == 0
        second = tmp_path / "second.sqlite"
        assert await m.run("prepare", state=second) == 0
        assert await m.run("run", state=second) == 0
        assert len(await m.documents()) == 8
        assert await m.run("check", state=second) == 0
