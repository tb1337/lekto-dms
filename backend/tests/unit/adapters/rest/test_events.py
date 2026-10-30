"""Server-sent events through a real Uvicorn server: each user receives only events of
documents they may read."""

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta

import httpx2

from lekto.adapters.inbound.rest import PREFIX, close_event_streams
from lekto.adapters.inbound.rest.events import EventHub, message
from lekto.adapters.outbound.memory import FakeEmbeddings
from lekto.composition.container import build_memory_container, build_services
from lekto.composition.settings import Settings
from lekto.core.domain.events import ClassifierTrained, DocumentUpdated
from lekto.core.domain.ids import DocumentId, UserId, new_id
from lekto.core.domain.spaces import SpaceRole
from lekto.core.domain.users import Role
from lekto.core.ports.embeddings import EmbeddingResult
from tests.api import Stream, auth, issue_token, listen, serving, until
from tests.builders import NOW, PASSWORD, SAMPLES
from tests.unit.adapters.rest.support import Api, make_app

EVENTS = f"{PREFIX}/events"


async def test_events_reach_only_users_who_may_read_the_document(api: Api) -> None:
    owner, reader, stranger = await api.user(), await api.user(), await api.user()
    admin = await api.admin()
    shared = await api.services.spaces.create(owner.id, "Shared")
    await api.services.spaces.set_member(owner.id, shared.id, reader.id, SpaceRole.READ)

    async with serving(api.app) as url, httpx2.AsyncClient(base_url=url, timeout=10) as client:
        streams = {user.id: Stream() for user in (owner, reader, stranger, admin)}
        tasks = [
            asyncio.create_task(listen(client, user, streams[user.id]))
            for user in (owner, reader, stranger, admin)
        ]
        for stream in streams.values():
            await asyncio.wait_for(stream.ready.wait(), timeout=5)
            assert stream.status == 200

        files = {"file": ("scan.pdf", (SAMPLES / "scan.pdf").read_bytes(), "x/y")}
        response = await client.post(
            f"{PREFIX}/documents",
            files=files,
            data={"space_id": str(shared.id)},
            headers=auth(owner),
        )
        document = response.json()["id"]
        own = streams[owner.id]
        await until(lambda: "document.received" in own.types())
        await api.drain()  # processing runs to green
        await until(lambda: own.events and own.events[-1]["type"] == "document.lane_changed")

        assert own.types()[:2] == ["document.received", "document.node_completed"]
        assert own.events[-1]["new"] == "green"
        assert {event["document_id"] for event in own.events} == {document}
        node = own.events[1]
        assert (node["node"], node["run"], node["outcome"]) == ("receive", 1, "ok")

        shared_events = streams[reader.id].types()
        assert "document.received" not in shared_events  # not visible while processing
        assert shared_events[-1] == "document.lane_changed"  # visible once green
        assert streams[stranger.id].events == []
        # Admins read every document, in processing too (Tobi, 08.10.2026).
        await until(lambda: streams[admin.id].types() == own.types())

        # A deleted document cannot be checked any more: those who could read it hear of it.
        deleted = await client.delete(f"{PREFIX}/documents/{document}", headers=auth(owner))
        assert deleted.status_code == 204
        await until(lambda: "document.deleted" in own.types())
        await until(lambda: "document.deleted" in streams[reader.id].types())
        await until(lambda: "document.deleted" in streams[admin.id].types())
        await asyncio.sleep(0.1)
        assert own.events[-1] == {**own.events[-1], "type": "document.deleted"}
        assert "readers" not in own.events[-1] and "readers" not in streams[reader.id].events[-1]
        assert streams[stranger.id].events == []

        close_event_streams(api.app)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)


async def test_the_end_of_a_training_reaches_every_user(api: Api) -> None:
    user, admin = await api.user(), await api.admin()
    async with serving(api.app) as url, httpx2.AsyncClient(base_url=url, timeout=10) as client:
        streams = {member.id: Stream() for member in (user, admin)}
        tasks = [
            asyncio.create_task(listen(client, member, streams[member.id]))
            for member in (user, admin)
        ]
        for stream in streams.values():
            await asyncio.wait_for(stream.ready.wait(), timeout=5)
        async with api.container.unit_of_work() as uow:
            await uow.outbox.add([ClassifierTrained(occurred_at=NOW, number=4, examples=120)])
            await uow.commit()
        await until(
            lambda: all(stream.types() == ["classifier.trained"] for stream in streams.values())
        )
        event = streams[user.id].events[0]
        assert (event["number"], event["examples"]) == (4, 120)
        assert "document_id" not in event
        close_event_streams(api.app)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)


async def test_a_stream_for_one_document(api: Api) -> None:
    owner, stranger = await api.user(), await api.user()
    async with serving(api.app) as url, httpx2.AsyncClient(base_url=url, timeout=10) as client:
        files = {"file": ("scan.pdf", (SAMPLES / "scan.pdf").read_bytes(), "x/y")}
        first = (await client.post(f"{PREFIX}/documents", files=files, headers=auth(owner))).json()
        other = {"file": ("photo.jpg", (SAMPLES / "photo.jpg").read_bytes(), "x/y")}
        await asyncio.sleep(0.1)  # the received events of both are delivered before listening

        hidden = await client.get(
            EVENTS, params={"document_id": first["id"]}, headers=auth(stranger)
        )
        assert hidden.status_code == 404

        stream = Stream()
        task = asyncio.create_task(listen(client, owner, stream, document_id=first["id"]))
        await asyncio.wait_for(stream.ready.wait(), timeout=5)
        await client.post(f"{PREFIX}/documents", files=other, headers=auth(owner))
        await api.drain()
        await until(lambda: stream.types().count("document.lane_changed") == 1)
        assert {event["document_id"] for event in stream.events} == {first["id"]}
        close_event_streams(api.app)
        await asyncio.wait_for(task, timeout=5)


async def test_a_stream_ends_when_its_token_is_revoked() -> None:
    container = build_memory_container()
    services = build_services(container)
    app = make_app(container, services, recheck=timedelta(milliseconds=200))
    user = await services.users.bootstrap_admin("root", PASSWORD)
    assert user is not None
    await issue_token(services.auth, user)
    [token] = await services.auth.list_api_tokens(user.id)
    async with serving(app) as url, httpx2.AsyncClient(base_url=url, timeout=10) as client:
        stream = Stream()
        task = asyncio.create_task(listen(client, user, stream))
        await asyncio.wait_for(stream.ready.wait(), timeout=5)
        assert stream.status == 200
        await services.auth.revoke_api_token(user.id, token.id)
        await asyncio.wait_for(task, timeout=5)  # the server ended the stream


async def test_the_meaning_of_a_query_reaches_only_its_searcher() -> None:
    """A search whose meaning was not ready in time answers by words with `meaning_pending`;
    once the meaning is ready, `search.meaning_ready` with the query reaches the searcher's
    stream, not another user's, and the same search takes the meaning into account."""

    class Gated:
        model = "fake-embeddings 1"

        def __init__(self) -> None:
            self.gate = asyncio.Event()

        async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
            await self.gate.wait()
            return await FakeEmbeddings(model=self.model).embed(texts)

    gated = Gated()
    container = replace(build_memory_container(), embeddings=gated)
    settings = Settings.model_construct(search_embed_timeout=timedelta(milliseconds=50))
    services = build_services(container, settings)
    app = make_app(container, services)
    searcher = await services.users.bootstrap_admin("root", PASSWORD)
    assert searcher is not None
    other = await services.users.create_user(searcher.id, "other", Role.USER, PASSWORD)
    for user in (searcher, other):
        await issue_token(services.auth, user)
    async with serving(app) as url, httpx2.AsyncClient(base_url=url, timeout=10) as client:
        streams = {user.id: Stream() for user in (searcher, other)}
        tasks = [
            asyncio.create_task(listen(client, user, streams[user.id]))
            for user in (searcher, other)
        ]
        for stream in streams.values():
            await asyncio.wait_for(stream.ready.wait(), timeout=5)
        query = {"q": "Weihnachtsgeld"}
        first = await client.post(f"{PREFIX}/documents/search", json=query, headers=auth(searcher))
        assert first.status_code == 200, first.text
        body = first.json()
        assert (body["mode"], body["meaning_pending"]) == ("words", True)
        assert body["reason"]["code"] == "search_embed_timeout"
        gated.gate.set()
        await until(lambda: streams[searcher.id].types() == ["search.meaning_ready"])
        event = streams[searcher.id].events[0]
        assert event["query"] == "Weihnachtsgeld"
        assert "user_id" not in event and "document_id" not in event
        again = await client.post(f"{PREFIX}/documents/search", json=query, headers=auth(searcher))
        assert (again.json()["mode"], again.json()["reason"]) == ("hybrid", None)
        warm = await client.post(f"{PREFIX}/documents/search/warm", headers=auth(searcher))
        assert warm.status_code == 204
        await asyncio.sleep(0.1)
        assert streams[other.id].events == []
        close_event_streams(app)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)


class _Readers:
    """Stands in for the documents service: who may read which document."""

    def __init__(self, readers: dict[DocumentId, set[UserId]]) -> None:
        self._readers = readers

    async def filter_readers(self, id: DocumentId, candidates: set[UserId]) -> set[UserId]:
        return self._readers.get(id, set()) & set(candidates)

    async def active_admins(self, candidates: set[UserId]) -> set[UserId]:
        return set()


async def test_a_relation_reaches_only_who_reads_both_documents() -> None:
    """The friend reads the invoice, not the reminder that refers to it: the invoice's
    `document.updated` with `relations` reaches only the owner, without the other end."""
    owner, friend = UserId(new_id()), UserId(new_id())
    invoice, reminder = DocumentId(new_id()), DocumentId(new_id())
    hub = EventHub(_Readers({invoice: {owner, friend}, reminder: {owner}}))  # type: ignore[arg-type]
    event = DocumentUpdated(
        document_id=invoice, occurred_at=NOW, fields=("relations",), related=reminder
    )
    async with hub.listen(owner) as mine, hub.listen(friend) as theirs:
        await hub.handle(event)
        assert (mine.queue.qsize(), theirs.queue.qsize()) == (1, 0)
    assert "related" not in message(event)
