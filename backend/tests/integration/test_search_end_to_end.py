"""Milestone M6 end to end: documents arrive through the REST API, the worker processes and
indexes them, the search finds them for those who may read them. Real API server (Uvicorn),
worker and Meilisearch; fake embeddings (vectors of 16 numbers); OCR and parser are fakes that
bring the text of the test. Two set-ups: SQLite with the filesystem, Postgres with S3 (Garage)."""

import asyncio
import secrets
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import func, select

from lekto.adapters.inbound.rest import PREFIX
from lekto.adapters.outbound.memory import FakeEmbeddings
from lekto.adapters.outbound.sql import Database
from lekto.adapters.outbound.sql.tables import jobs
from lekto.composition.settings import Settings
from lekto.core.domain.jobs import JobStatus
from lekto.core.domain.spaces import SpaceRole
from lekto.core.domain.users import Role, User
from lekto.core.ports.object_store import ObjectStore
from lekto.core.services.indexing import INDEX_JOB, REBUILD_JOB, REFRESH_JOB
from tests import builders
from tests.api import auth, until
from tests.integration.e2e import DOCUMENTS, System, TextOcr, TextParser, running_system
from tests.integration.services import drop, new_index

SEARCH = f"{DOCUMENTS}/search"
TIMEOUT = 60.0  # seconds a document may take here


class SearchSystem(System):
    async def search(self, user: User, text: str, **params: Any) -> dict[str, Any]:
        """By words unless the test asks for more: a search by meaning ranks every document, so
        it would find documents that are not about the text."""
        response = await self.client.post(
            SEARCH,
            json={"q": text},
            params={"semantic_ratio": 0, **params},
            headers=auth(user),
        )
        assert response.status_code == 200, response.text
        page: dict[str, Any] = response.json()
        return page

    async def ids(self, user: User, text: str, **params: Any) -> set[str]:
        page = await self.search(user, text, **params)
        return {item["document"]["id"] for item in page["items"]}

    async def idle(self) -> None:
        """Wait until no search job is queued or running."""

        async def active() -> int:
            statement = (
                select(func.count())
                .select_from(jobs)
                .where(
                    jobs.c.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
                    jobs.c.kind.in_([INDEX_JOB, REFRESH_JOB, REBUILD_JOB]),
                )
            )
            async with self.database.engine.connect() as connection:
                return int((await connection.execute(statement)).scalar_one())

        async def idle() -> bool:
            if await active():
                return False
            await asyncio.sleep(0.5)  # events that are still on their way
            return not await active()

        await until(idle, TIMEOUT, every=0.2, what="the worker is idle")

    async def processed(self, user: User, id: str) -> None:
        """Wait until the pipeline is done with the document: the search finds it earlier, and
        a change while nodes still run meets their writes (409)."""

        async def done() -> bool:
            response = await self.client.get(f"{DOCUMENTS}/{id}", headers=auth(user))
            return bool(response.json()["processing"]["status"] != "processing")

        await until(done, TIMEOUT, every=0.2, what=f"{id} processed")

    async def found(self, user: User, text: str, expected: set[str], **params: Any) -> None:
        """Wait until the search finds exactly `expected` (the index follows a moment later)."""

        async def condition() -> bool:
            return await self.ids(user, text, **params) == expected

        await until(condition, TIMEOUT, every=0.2, what=f"{text!r} finds {expected}")


@pytest.fixture
def index_name() -> str:
    return f"lekto-test-{secrets.token_hex(6)}"


@pytest.fixture
async def system(
    stores: tuple[Database, ObjectStore], meilisearch_settings: Settings, index_name: str
) -> AsyncIterator[SearchSystem]:
    index = new_index(meilisearch_settings, index_name, dimensions=FakeEmbeddings.DIMENSIONS)
    try:
        async with running_system(
            SearchSystem,
            stores,
            ocr=TextOcr(),
            parser=TextParser(),
            search_index=index,
            embeddings=FakeEmbeddings(),
        ) as system:
            yield system
    finally:
        await index.aclose()
        await drop(meilisearch_settings, index_name, f"{index_name}-rebuild")


async def test_documents_are_found_by_those_who_may_read_them(system: SearchSystem) -> None:
    owner, reader, stranger = await system.user(), await system.user(), await system.user()
    admin = await system.user(Role.ADMIN)
    async with system.container.unit_of_work() as uow:
        shared = builders.space(owner, "Household")
        shared.set_member(reader.id, SpaceRole.READ)
        await uow.spaces.add(shared)
        await uow.commit()

    bill = await system.upload(owner, "Stromrechnung der Stadtwerke", space_id=str(shared.id))
    lease = await system.upload(owner, "Mietvertrag für die Wohnung in Berlin")
    private = {bill, lease}

    # A new document is found by words soon after it has been filed.
    await system.found(owner, "Stromrechnung", {bill})
    await system.found(owner, "Mietvertrag", {lease})
    assert await system.ids(owner, "Wohnung Berlin") == {lease}
    assert await system.ids(owner, "document.pdf") == private  # the file name

    # Readers of a space find what is green in it, nothing else.
    await system.found(reader, "Stromrechnung", {bill})  # once it is green, not while in processing
    assert await system.ids(reader, "Mietvertrag") == set()
    for user in (stranger, admin):
        assert await system.ids(user, "Stromrechnung") == set()
        assert await system.ids(user, "Mietvertrag") == set()

    # With embeddings, the meaning takes part and the rights hold for it as well.
    page = await system.search(reader, "Stromrechnung", semantic_ratio=1.0)
    assert page["semantic"] is True
    assert {item["document"]["id"] for item in page["items"]} <= {bill}
    page = await system.search(stranger, "Stromrechnung", semantic_ratio=1.0)
    assert page["items"] == []
    hit = (await system.search(owner, "Stromrechnung"))["items"][0]
    assert any(piece["match"] for piece in hit["snippet"])

    # Changes reach the index.
    await system.processed(owner, lease)
    patched = await system.client.patch(
        f"{DOCUMENTS}/{lease}", json={"title": "Wohnungsvertrag Hamburg"}, headers=auth(owner)
    )
    assert patched.status_code == 200, patched.text
    await system.found(owner, "Hamburg", {lease})

    # A removed member finds nothing at once, before the index could have changed.
    revoked = await system.client.delete(
        f"{PREFIX}/spaces/{shared.id}/members/{reader.id}", headers=auth(owner)
    )
    assert revoked.status_code in {200, 204}, revoked.text
    assert await system.ids(reader, "Stromrechnung") == set()
    assert await system.ids(owner, "Stromrechnung") == {bill}

    # Deleting removes the document from the index.
    deleted = await system.client.delete(f"{DOCUMENTS}/{bill}", headers=auth(owner))
    assert deleted.status_code == 204
    await system.found(owner, "Stromrechnung", set())

    health = await system.client.get(f"{PREFIX}/health")
    assert health.json()["status"] == "ok"


async def test_the_index_is_rebuilt_on_an_empty_meilisearch(
    system: SearchSystem, meilisearch_settings: Settings, index_name: str
) -> None:
    owner, admin = await system.user(), await system.user(Role.ADMIN)
    first = await system.upload(owner, "Steuerbescheid Finanzamt")
    second = await system.upload(owner, "Versicherungspolice Hausrat")
    await system.found(owner, "Steuerbescheid", {first})
    await system.found(owner, "Versicherungspolice", {second})

    # Meilisearch loses everything, while no job is at work.
    await system.idle()
    await drop(meilisearch_settings, index_name)

    async def gone() -> bool:
        """The search fails (503) or, once the adapter has set up an empty index, finds nothing."""
        response = await system.client.post(
            SEARCH,
            json={"q": "Steuerbescheid"},
            params={"semantic_ratio": 0},
            headers=auth(owner),
        )
        return response.status_code == 503 or response.json()["items"] == []

    await until(gone, 10, every=0.2, what="the loss shows")

    denied = await system.client.post(f"{PREFIX}/search/reindex", headers=auth(owner))
    assert denied.status_code == 403
    rebuild = await system.client.post(f"{PREFIX}/search/reindex", headers=auth(admin))
    assert rebuild.status_code == 202

    await system.found(owner, "Steuerbescheid", {first})
    await system.found(owner, "Versicherungspolice", {second})
    page = await system.search(owner, "Steuerbescheid", semantic_ratio=0.5)
    assert page["semantic"] is True  # the vectors were made again
