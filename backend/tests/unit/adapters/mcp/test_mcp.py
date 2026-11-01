"""The MCP endpoint, with the SDK's own client: tokens, tools, and that the rights of the REST
API hold here too."""

import base64
import json
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx2
import pytest
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import ImageContent, Tool

from lekto.adapters.inbound.mcp.server import instructions
from lekto.adapters.inbound.rest import PREFIX
from lekto.adapters.outbound.memory import ManualClock
from lekto.composition.container import build_memory_container, build_services
from lekto.core.domain.documents import DocumentChanges
from lekto.core.domain.fields import FieldType, Money
from lekto.core.domain.ids import DocumentId, new_id, short_id
from lekto.core.domain.master_data import TagScope
from lekto.core.services.objects import page_key, text_key
from tests import builders
from tests.api import auth, serving
from tests.builders import SAMPLES
from tests.unit.adapters.mcp.support import TEXT, call, connected, data, error, running
from tests.unit.adapters.rest.support import Api, Scene, make_app, post, upload

# --- the endpoint -------------------------------------------------------------------------------


READS = {
    "documents_search",
    "documents_list",
    "documents_get",
    "documents_text",
    "documents_page",
    "documents_log",
    "tags_list",
    "expected_list",
}
WRITES = {"documents_update"}


async def tools_of(api: Api, headers: dict[str, str]) -> dict[str, Tool]:
    async with connected(api, headers) as client:
        return {tool.name: tool for tool in (await client.list_tools()).tools}


async def test_the_server_lists_its_tools_with_their_class(api: Api, scene: Scene) -> None:
    by_name = await tools_of(api, scene.headers["owner"])
    assert set(by_name) == READS | WRITES
    read_only = {
        name: tool.annotations is not None and tool.annotations.read_only_hint
        for name, tool in by_name.items()
    }
    assert read_only == {name: name in READS for name in by_name}
    assert all(tool.output_schema is None for tool in by_name.values())
    assert "follow" in (by_name["documents_text"].description or "")  # the warning about the text


async def test_a_read_token_sees_and_calls_no_tool_that_changes(api: Api, scene: Scene) -> None:
    assert set(await tools_of(api, scene.headers["read_token"])) == READS
    refused = await call(
        api, scene.headers["read_token"], "documents_update", id=scene.green, title="X"
    )
    assert error(refused) == "this API token may only read"


def test_the_instructions_name_the_link_into_the_web_ui() -> None:
    assert "https://lekto.example.org/ui/documents/<id>" in instructions(
        "https://lekto.example.org/ui"
    )
    assert "by its title" in instructions(None)
    assert "{" not in instructions(None)


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
async def test_both_spellings_of_the_path_work(api: Api, scene: Scene, path: str) -> None:
    response = await api.client.post(
        f"{PREFIX}{path}",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={
            **scene.headers["owner"],
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer lekto_nonsense"},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer "},
    ],
)
async def test_without_a_valid_token_the_answer_is_401(api: Api, headers: dict[str, str]) -> None:
    response = await api.client.post(
        f"{PREFIX}/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={**headers, "Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("actor", ["expired_token", "revoked_token", "deactivated"])
async def test_tokens_that_are_no_longer_good_are_refused(
    api: Api, scene: Scene, actor: str
) -> None:
    response = await api.client.post(
        f"{PREFIX}/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={**scene.headers[actor], "Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 401


async def test_a_session_cookie_does_not_open_the_endpoint(api: Api, scene: Scene) -> None:
    async with api.sign_in(scene.owner) as session:
        response = await session.client.post(
            f"{PREFIX}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={**session.headers, "Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 401


async def test_the_endpoint_is_absent_when_switched_off() -> None:

    container = build_memory_container(ManualClock(builders.NOW))
    app = make_app(container, build_services(container), mcp=False)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="https://lekto"
    ) as client:
        response = await client.post(f"{PREFIX}/mcp", json={})
    assert response.status_code == 404


async def test_the_server_works_over_a_real_connection() -> None:

    clock = ManualClock(builders.NOW)
    container = build_memory_container(clock)
    services = build_services(container)
    builders.skip_classification(services.pipeline)
    app = make_app(container, services, mcp=True)  # Uvicorn runs its lifespan
    client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="https://lekto")
    api = Api(container, services, app, client, clock)
    user = await api.user()
    received = await services.pipeline.receive(
        user.id, builders.incoming((SAMPLES / "scan.pdf").read_bytes()), filename="a.pdf"
    )
    await api.drain()
    async with (
        serving(app) as base,
        httpx2.AsyncClient(headers=auth(user)) as http,
        Client(streamable_http_client(f"{base}{PREFIX}/mcp", http_client=http)) as mcp,
    ):
        result = await mcp.call_tool("documents_get", {"id": str(received.id)})
    await client.aclose()
    assert data(result)["id"] == short_id(received.id)


# --- reading ------------------------------------------------------------------------------------


async def test_documents_list_lists_by_filters_and_counts_by_groups(api: Api, scene: Scene) -> None:
    owner = scene.headers["owner"]
    admin = await api.admin()
    await api.services.master_data.create_field(admin.id, "Betrag", FieldType.AMOUNT)
    await api.services.master_data.create_field(admin.id, "Notiz", FieldType.TEXT)
    for id, dated, amount in (
        (scene.green, "2025-03-31", "80.10"),
        (scene.yellow, "2026-01-31", "79.90"),
    ):
        data(
            await call(
                api,
                owner,
                "documents_update",
                id=id,
                document_date=dated,
                fields={"betrag": {"amount": amount, "currency": "EUR"}},
            )
        )

    every = data(await call(api, owner, "documents_list", fields=["Betrag"]))
    assert {item["id"] for item in every["items"]} == shorts(
        scene.green, scene.yellow, scene.processing
    )
    green = next(item for item in every["items"] if {item["id"]} == shorts(scene.green))
    assert green["fields"] == {"Betrag": {"amount": "80.10", "currency": "EUR"}}
    yellow = data(await call(api, owner, "documents_list", lane="yellow"))
    assert {item["id"] for item in yellow["items"]} == shorts(scene.yellow)
    paged = data(await call(api, owner, "documents_list", limit=2))
    assert len(paged["items"]) == 2 and paged["next_offset"] == 2
    last = data(await call(api, owner, "documents_list", limit=2, offset=2))
    assert len(last["items"]) == 1 and "next_offset" not in last

    by_year = data(await call(api, owner, "documents_list", group_by="year", sum="Betrag"))
    assert by_year == {
        "count": 3,
        "sum": {"EUR": "160.00"},
        "groups": [
            {"key": "2025", "count": 1, "sum": {"EUR": "80.10"}},
            {"key": "2026", "count": 1, "sum": {"EUR": "79.90"}},
            {"count": 1},
        ],
    }
    in_2026 = data(
        await call(api, owner, "documents_list", sum="Betrag", document_date_from="2026-01-01")
    )
    assert in_2026 == {"count": 1, "sum": {"EUR": "79.90"}}
    assert "holds no amount" in error(await call(api, owner, "documents_list", sum="Notiz"))
    assert "no field named" in error(await call(api, owner, "documents_list", sum="Summe"))
    # The stranger counts none of them.
    assert data(await call(api, scene.headers["stranger"], "documents_list", sum="Betrag")) == {
        "count": 0
    }


async def test_documents_list_lists_and_counts_the_hits_of_words(api: Api, scene: Scene) -> None:
    owner = scene.headers["owner"]
    listed = data(await call(api, owner, "documents_list", query="pdf", lane="green"))
    assert {item["id"] for item in listed["items"]} == shorts(scene.green)
    counted = data(await call(api, owner, "documents_list", query="pdf", group_by="month"))
    assert (counted["count"], counted["hits_only"]) == (3, True)
    reader = data(
        await call(api, scene.headers["reader"], "documents_list", query="pdf", group_by="year")
    )
    assert reader["count"] == 1


async def test_documents_list_takes_the_filters_of_a_lens(api: Api, scene: Scene) -> None:
    owner = scene.headers["owner"]
    admin = await api.admin()
    urgent = await api.services.master_data.create_tag(admin.id, "Dringend")
    await api.services.master_data.create_tag(admin.id, "Später")
    data(await call(api, owner, "documents_update", id=scene.yellow, tags=["Dringend"]))
    data(await call(api, owner, "documents_update", id=scene.green, tags=["Später"]))
    lens = {"name": "Dringendes", "filter": {"tag_ids": [str(urgent.id)]}}
    await post(api, "/lenses", lens, owner)

    listed = data(await call(api, owner, "documents_list", lens="dringendes"))
    assert {item["id"] for item in listed["items"]} == shorts(scene.yellow)
    # A filter given replaces the lens's own.
    later = data(await call(api, owner, "documents_list", lens="Dringendes", tags=["Später"]))
    assert {item["id"] for item in later["items"]} == shorts(scene.green)
    assert "no lens named" in error(await call(api, owner, "documents_list", lens="Rot"))


async def test_documents_go_by_a_short_id_or_the_whole_one(api: Api, scene: Scene) -> None:
    """Tobi, 01.11.2026 (umsetzungsplan "MCP", decision 8): the last 8 characters of the id."""
    owner = scene.headers["owner"]
    (short,) = shorts(scene.green)
    assert data(await call(api, owner, "documents_get", id=short))["id"] == short
    assert data(await call(api, owner, "documents_get", id=scene.green))["id"] == short
    assert data(await call(api, owner, "documents_text", id=short.upper()))["total_length"] > 0
    assert "is no document id" in error(await call(api, owner, "documents_get", id="1234"))
    assert "not found" in error(await call(api, owner, "documents_get", id="00000000"))
    hidden = await call(api, scene.headers["stranger"], "documents_get", id=short)
    assert "not found" in error(hidden)


async def test_documents_get_names_what_the_document_refers_to(api: Api, scene: Scene) -> None:
    master = api.services.master_data
    admin = await api.admin()
    contact = await master.create_contact(admin.id, "Stadtwerke")
    kind = await master.create_document_type(admin.id, "Rechnung")
    tag = await master.create_tag(admin.id, "Strom")
    amount = await master.create_field(admin.id, "Betrag", FieldType.AMOUNT)

    await api.services.documents.change_metadata(
        scene.owner.id,
        DocumentId(UUID(scene.green)),
        DocumentChanges(
            contact_id=contact.id,
            document_type_id=kind.id,
            tag_ids=frozenset({tag.id}),
            fields={amount.id: Money(Decimal("84.20"), "EUR")},
        ),
    )
    document = data(await call(api, scene.headers["reader"], "documents_get", id=scene.green))
    assert document["access"] == "read"
    # Master data by name only (Tobi, 01.11.2026: as few tokens as possible).
    assert document["contact"] == "Stadtwerke" and document["document_type"] == "Rechnung"
    assert document["tags"] == ["Strom"]
    assert document["fields"] == {"Betrag": {"amount": "84.20", "currency": "EUR"}}
    assert document["lane"] == "green" and document["status"] == "completed"
    # What is empty is left out.
    assert "topic" not in document and "relations" not in document
    assert str(contact.id) not in json.dumps(document) and str(tag.id) not in json.dumps(document)


async def test_documents_get_names_its_relations_one_may_read(api: Api, scene: Scene) -> None:
    """Read only (#145): the reader does not read the yellow document, so not the relation."""
    green, yellow = DocumentId(UUID(scene.green)), DocumentId(UUID(scene.yellow))
    await api.services.relations.relate(scene.owner.id, green, yellow)
    wanted = {"id": scene.green, "include": ["relations"]}
    owner = data(await call(api, scene.headers["owner"], "documents_get", **wanted))
    (relation,) = owner["relations"]
    assert relation["id"] == shorts(scene.yellow).pop() and "suggested" not in relation
    assert relation["direction"] in ("refers_to", "referred_by")
    reader = data(await call(api, scene.headers["reader"], "documents_get", **wanted))
    assert "relations" not in reader
    # Only when asked for.
    plain = data(await call(api, scene.headers["owner"], "documents_get", id=scene.green))
    assert "relations" not in plain
    changed = data(
        await call(api, scene.headers["owner"], "documents_update", id=scene.green, title="Neu")
    )
    assert {item["id"] for item in changed["document"]["relations"]} == shorts(scene.yellow)


async def test_documents_get_tells_what_is_open_and_how_it_was_read(api: Api, scene: Scene) -> None:
    owner = scene.headers["owner"]
    wanted = ["review", "reading", "facts"]
    yellow = data(await call(api, owner, "documents_get", id=scene.yellow, include=wanted))
    (judge,) = yellow["open"]
    assert judge["node"] == "judge" and judge["reason"] == "new contact"
    green = data(await call(api, owner, "documents_get", id=scene.green, include=wanted))
    assert "open" not in green and "poorly_read" not in green


async def test_documents_page_gives_the_image_of_a_page(api: Api, scene: Scene) -> None:
    document = DocumentId(UUID(scene.green))
    await api.container.object_store.put(
        page_key(document, 1), b"RIFF\x00\x00\x00\x00WEBPVP8 ", content_type="image/webp"
    )
    async with api.container.unit_of_work() as uow:
        stored = await uow.documents.get(document)
        stored.page_count = 1
        await uow.documents.update(stored)
        await uow.commit()
    result = await call(api, scene.headers["reader"], "documents_page", id=scene.green, page=1)
    assert not result.is_error
    (image,) = result.content
    assert isinstance(image, ImageContent) and image.mime_type == "image/webp"
    assert base64.b64decode(image.data).startswith(b"RIFF")
    missing = await call(api, scene.headers["reader"], "documents_page", id=scene.green, page=2)
    assert "not found" in error(missing)


async def test_documents_log_names_the_steps_and_who_decided(api: Api, scene: Scene) -> None:
    owner = scene.headers["owner"]
    data(await call(api, owner, "documents_update", id=scene.green, title="Neu"))
    log = data(await call(api, owner, "documents_log", id=scene.green))
    nodes = [entry["node"] for entry in log["entries"]]
    assert nodes[0] == "receive" and "judge" in nodes
    change = log["entries"][-1]
    assert (change["node"], change["by"], change["via_token"]) == ("apply_rules", "owner", "tests")
    every = data(await call(api, owner, "documents_log", id=scene.yellow, every_run=True))
    assert {entry["run"] for entry in every["entries"]} == {1, 2}
    latest = data(await call(api, owner, "documents_log", id=scene.yellow))
    assert {entry["run"] for entry in latest["entries"]} == {2}


async def test_documents_update_tries_a_change_without_storing_it(api: Api, scene: Scene) -> None:
    owner = scene.headers["owner"]
    tried = data(
        await call(api, owner, "documents_update", id=scene.green, title="Probe", dry_run=True)
    )
    assert tried["dry_run"] is True and tried["document"]["title"] == "Probe"
    stored = data(await call(api, owner, "documents_get", id=scene.green))
    assert stored["title"] != "Probe"


async def test_a_document_one_may_not_read_is_just_not_found(api: Api, scene: Scene) -> None:
    unknown = str(new_id())
    missing = error(await call(api, scene.headers["stranger"], "documents_get", id=unknown))
    for actor, which in [
        ("stranger", scene.green),
        ("reader", scene.yellow),
        ("reader", scene.processing),
    ]:
        message = error(await call(api, scene.headers[actor], "documents_get", id=which))
        assert message.replace(which, "X") == missing.replace(unknown, "X"), (actor, which)
    owner_sees = data(await call(api, scene.headers["owner"], "documents_get", id=scene.yellow))
    assert owner_sees["lane"] == "yellow"
    # Admins read every document (Tobi, 08.10.2026).
    admin_sees = data(await call(api, scene.headers["admin"], "documents_get", id=scene.yellow))
    assert admin_sees["lane"] == "yellow"


async def test_documents_text_reads_in_pieces_and_only_for_readers(api: Api, scene: Scene) -> None:
    first = data(await call(api, scene.headers["reader"], "documents_text", id=scene.green))
    assert first["text"] == TEXT[:100]  # the server's limit: LEKTO_MCP_TEXT_MAX
    assert (first["offset"], first["total_length"], first["next_offset"]) == (0, len(TEXT), 100)
    asked_more = data(
        await call(api, scene.headers["reader"], "documents_text", id=scene.green, limit=5000)
    )
    assert asked_more["text"] == TEXT[:100]
    second = data(
        await call(
            api, scene.headers["reader"], "documents_text", id=scene.green, offset=100, limit=10
        )
    )
    assert second["text"] == TEXT[100:110] and second["next_offset"] == 110
    end = data(
        await call(
            api, scene.headers["reader"], "documents_text", id=scene.green, offset=len(TEXT) - 3
        )
    )
    assert end["text"] == TEXT[-3:] and "next_offset" not in end
    for actor, which in [("stranger", scene.green), ("reader", scene.yellow)]:
        assert "not found" in error(
            await call(api, scene.headers[actor], "documents_text", id=which)
        )
    bad = await call(api, scene.headers["reader"], "documents_text", id=scene.green, offset=-1)
    assert bad.is_error


async def test_a_document_without_text_says_so(api: Api, scene: Scene) -> None:
    await api.container.object_store.delete(text_key(DocumentId(UUID(scene.green))))
    result = await call(api, scene.headers["owner"], "documents_text", id=scene.green)
    assert "no text yet" in error(result)


async def test_tags_list_gives_each_tag_as_its_path_by_scope(api: Api, scene: Scene) -> None:
    admin = await api.admin()
    master = api.services.master_data
    zeta = await master.create_tag(admin.id, "Zeta")
    await master.create_tag(admin.id, "alpha")
    await master.create_tag(admin.id, "Child", parent_id=zeta.id)
    await master.create_tag(admin.id, "Insurer", scope=TagScope.CONTACT)
    tags = data(await call(api, scene.headers["read_token"], "tags_list"))
    assert tags == {"document": ["alpha", "Zeta", "Zeta / Child"], "contact": ["Insurer"]}
    groups = data(await call(api, scene.headers["read_token"], "tags_list", scope="contact"))
    assert groups == {"contact": ["Insurer"]}


# --- search -------------------------------------------------------------------------------------


def shorts(*ids: str) -> set[str]:
    """The short ids MCP names the documents `ids` by."""
    return {short_id(UUID(id)) for id in ids}


async def found(api: Api, headers: dict[str, str], **arguments: Any) -> set[str]:
    ids: set[str] = set()
    offset: int | None = 0
    while offset is not None:
        page = data(
            await call(
                api, headers, "documents_search", query="pdf", limit=1, offset=offset, **arguments
            )
        )
        ids |= {item["id"] for item in page.get("items", [])}
        offset = page.get("next_offset")
    return ids


async def test_search_finds_what_the_caller_may_read(api: Api, scene: Scene) -> None:
    everything = shorts(scene.green, scene.yellow, scene.processing)
    assert await found(api, scene.headers["owner"]) == everything
    assert await found(api, scene.headers["read_token"]) == everything
    assert await found(api, scene.headers["reader"]) == shorts(scene.green)
    assert await found(api, scene.headers["stranger"]) == set()
    page = data(await call(api, scene.headers["reader"], "documents_search", query="pdf"))
    item = page["items"][0]
    assert {item["id"]} == shorts(scene.green) and item["access"] == "read"
    assert set(item) >= {"title", "snippet", "lane"}
    assert isinstance(item["snippet"], str)
    assert "semantic" in page  # false says something, unlike null or empty
    nothing = data(await call(api, scene.headers["stranger"], "documents_search", query="pdf"))
    assert "items" not in nothing and "next_offset" not in nothing


async def test_search_filters_by_name(api: Api, scene: Scene) -> None:
    admin = await api.admin()
    master = api.services.master_data
    energy = await master.create_tag(admin.id, "Energie")
    tag = await master.create_tag(admin.id, "Strom", parent_id=energy.id)
    await master.create_tag(admin.id, "Gruppe", scope=TagScope.CONTACT)

    await api.services.documents.change_metadata(
        scene.owner.id,
        DocumentId(UUID(scene.green)),
        DocumentChanges(tag_ids=frozenset({tag.id})),
    )
    indexing = api.services.indexing
    assert indexing is not None
    await indexing.reconcile()
    await builders.drain(indexing)
    assert await found(api, scene.headers["owner"], tags=["strom"]) == shorts(scene.green)
    # A tag finds the documents with a tag below it.
    assert await found(api, scene.headers["owner"], tags=["Energie"]) == shorts(scene.green)
    unknown = await call(
        api, scene.headers["owner"], "documents_search", query="pdf", tags=["Nope"]
    )
    assert "no tag named 'Nope'" in error(unknown)
    # Groups are no document tags.
    group = await call(
        api, scene.headers["owner"], "documents_search", query="pdf", tags=["Gruppe"]
    )
    assert "no tag named 'Gruppe'" in error(group)
    unknown = await call(
        api, scene.headers["owner"], "documents_search", query="pdf", contact="Nope"
    )
    assert "no contact named 'Nope'" in error(unknown)


async def test_search_filters_by_topics(api: Api, scene: Scene) -> None:
    """Several topics: the documents with one of them, each with the topics below it."""
    admin = await api.admin()
    master = api.services.master_data
    work = await master.create_tag(admin.id, "Arbeit", scope=TagScope.TOPIC)
    insurance = await master.create_tag(admin.id, "Versicherung", scope=TagScope.TOPIC)
    health = await master.create_tag(
        admin.id, "Krankenversicherung", scope=TagScope.TOPIC, parent_id=insurance.id
    )
    nord = await master.create_contact(admin.id, "Nord", topic_ids=[work.id, health.id])
    for which, topic in ((scene.green, work), (scene.yellow, health)):
        await api.services.documents.change_metadata(
            scene.owner.id,
            DocumentId(UUID(which)),
            DocumentChanges(contact_id=nord.id, topic_id=topic.id),
        )
    indexing = api.services.indexing
    assert indexing is not None
    await indexing.reconcile()
    await builders.drain(indexing)
    owner = scene.headers["owner"]
    assert await found(api, owner, topics=["arbeit"]) == shorts(scene.green)
    assert await found(api, owner, topics=["Versicherung"]) == shorts(scene.yellow)
    assert await found(api, owner, topics=["Arbeit", "Krankenversicherung"]) == shorts(
        scene.green, scene.yellow
    )
    page = data(await call(api, owner, "documents_search", query="pdf", topics=["Arbeit"]))
    assert page["items"][0]["topic"] == "Arbeit"
    assert "no topic named 'Nope'" in error(
        await call(api, owner, "documents_search", query="pdf", topics=["Nope"])
    )


async def test_search_without_an_index_says_so() -> None:

    container = build_memory_container(ManualClock(builders.NOW))
    services = replace(build_services(container), search=None)
    app = make_app(container, services, mcp=True)
    async with running(app):
        api = Api(
            container,
            services,
            app,
            httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="https://lekto"),
            ManualClock(builders.NOW),
        )
        user = await api.user()
        result = await call(api, auth(user), "documents_search", query="anything")
    assert "search is not available" in error(result)


# --- changing -----------------------------------------------------------------------------------


async def test_documents_update_changes_what_is_given(api: Api, scene: Scene) -> None:
    admin = await api.admin()
    master = api.services.master_data
    await master.create_contact(admin.id, "Stadtwerke")
    await master.create_tag(admin.id, "Strom")
    await master.create_tag(admin.id, "Wohnung")
    await master.create_field(admin.id, "Zählerstand", FieldType.NUMBER)
    result = data(
        await call(
            api,
            scene.headers["writer"],
            "documents_update",
            id=scene.green,
            title="Strom März",
            contact="stadtwerke",
            tags=["Strom", "wohnung"],
            document_date="2026-03-31",
            fields={"zählerstand": "1234.5"},
        )
    )
    document = result["document"]
    assert result["access"] == "edit" and document["title"] == "Strom März"
    assert document["contact"] == "Stadtwerke"
    assert document["tags"] == ["Strom", "Wohnung"]
    assert document["document_date"] == "2026-03-31"
    assert document["fields"] == {"Zählerstand": "1234.5"}

    # What is left out stays; tags are replaced as a whole; null removes.
    again = data(
        await call(
            api,
            scene.headers["owner"],
            "documents_update",
            id=scene.green,
            tags=["Strom"],
            contact=None,
            document_date=None,
            fields={"Zählerstand": None},
        )
    )["document"]
    assert again["title"] == "Strom März"
    assert "contact" not in again and "document_date" not in again
    assert again["tags"] == ["Strom"] and "fields" not in again
    # The same change as over REST.
    rest = (
        await api.client.get(f"{PREFIX}/documents/{scene.green}", headers=auth(scene.owner))
    ).json()
    assert rest["title"] == "Strom März" and rest["contact_id"] is None


async def test_a_change_carries_the_token(api: Api, scene: Scene) -> None:
    """The verdicts name the token the change came through (umsetzungsplan "MCP", decision
    11), as over REST."""
    changed = await call(
        api, scene.headers["owner"], "documents_update", id=scene.green, document_date="2026-03-31"
    )
    data(changed)
    async with api.container.unit_of_work() as uow:
        verdicts = await uow.processing_facts.verdicts(DocumentId(UUID(scene.green)))
    assert verdicts
    assert {None if verdict.via is None else verdict.via.name for verdict in verdicts} == {"tests"}


async def test_the_topic_is_read_and_set_by_its_name(api: Api, scene: Scene) -> None:
    admin = await api.admin()
    master = api.services.master_data
    work = await master.create_tag(admin.id, "Arbeit", scope=TagScope.TOPIC)
    other = await master.create_tag(admin.id, "Girokonto", scope=TagScope.TOPIC)
    await master.create_contact(admin.id, "Nord", topic_ids=[work.id])
    writer = scene.headers["writer"]
    result = data(
        await call(api, writer, "documents_update", id=scene.green, contact="nord", topic="arbeit")
    )
    assert result["document"]["topic"] == "Arbeit"
    document = data(await call(api, scene.headers["reader"], "documents_get", id=scene.green))
    assert document["topic"] == "Arbeit"
    # Only one the contact enables; a tag is no topic; null removes it.
    assert "does not enable" in error(
        await call(api, writer, "documents_update", id=scene.green, topic=other.name)
    )
    assert "no topic named" in error(
        await call(api, writer, "documents_update", id=scene.green, topic="Strom")
    )
    cleared = data(await call(api, writer, "documents_update", id=scene.green, topic=None))
    assert "topic" not in cleared["document"]
    topics = data(await call(api, writer, "tags_list", scope="topic"))
    assert topics == {"topic": ["Arbeit", "Girokonto"]}


async def test_documents_update_needs_a_read_write_token_and_write_access(
    api: Api, scene: Scene
) -> None:
    refused = await call(
        api, scene.headers["read_token"], "documents_update", id=scene.green, title="X"
    )
    assert "may only read" in error(refused)
    no_write = await call(
        api, scene.headers["reader"], "documents_update", id=scene.green, title="X"
    )
    assert "no write access" in error(no_write)
    hidden = await call(
        api, scene.headers["stranger"], "documents_update", id=scene.green, title="X"
    )
    assert "not found" in error(hidden)
    unchanged = (
        await api.client.get(f"{PREFIX}/documents/{scene.green}", headers=auth(scene.owner))
    ).json()
    assert unchanged["title"] != "X"


async def test_documents_update_refuses_unknown_names_and_bad_values(
    api: Api, scene: Scene
) -> None:
    admin = await api.admin()
    await api.services.master_data.create_field(admin.id, "Betrag", FieldType.AMOUNT)
    owner = scene.headers["owner"]
    cases: list[tuple[dict[str, Any], str]] = [
        ({"contact": "Nobody"}, "no contact named 'Nobody'"),
        ({"document_type": "Nothing"}, "no document type named 'Nothing'"),
        ({"tags": ["Missing"]}, "no tag named 'Missing'"),
        ({"fields": {"Unknown": 1}}, "no field named 'Unknown'"),
        ({"fields": {"Betrag": "lots"}}, "does not accept"),
        ({"title": ""}, ""),
    ]
    for arguments, message in cases:
        result = await call(api, owner, "documents_update", id=scene.green, **arguments)
        assert message in error(result), arguments


async def test_documents_update_returns_the_document_and_the_rules_report(
    api: Api, scene: Scene
) -> None:
    result = data(
        await call(api, scene.headers["owner"], "documents_update", id=scene.green, title="Z")
    )
    assert result["id"] == shorts(scene.green).pop() and result["document"]["title"] == "Z"
    assert result.get("rules", []) == []


async def test_an_editor_whose_change_files_the_document_away_learns_nothing_more(
    api: Api,
) -> None:
    admin, owner, editor = await api.admin(), await api.user(), await api.user()
    o = auth(owner)
    acme = await post(api, "/contacts", {"name": "ACME"}, auth(admin))
    shared = await post(api, "/spaces", {"name": "Shared"}, o)
    private = await post(api, "/spaces", {"name": "Private"}, o)
    response = await api.client.put(
        f"{PREFIX}/spaces/{shared['id']}/members/{editor.id}",
        json={"role": "edit"},
        headers=o,
    )
    assert response.status_code < 300, response.text
    # A rule of the owner's personal space files arrivals into the shared space; a rule of the
    # shared space files a document of ACME into the private one.
    for name, triggers, condition, space, of in (
        ("Shared", ["ingest"], {"field": "channel", "op": "is", "value": "api"}, shared, None),
        (
            "Private",
            ["change"],
            {"field": "contact", "op": "is", "value": acme["id"]},
            private,
            shared,
        ),
    ):
        await post(
            api,
            "/rules",
            {
                "name": name,
                "triggers": triggers,
                "conditions": {"all": [condition]},
                "actions": [{"type": "set_space", "space_id": space["id"]}],
                **({} if of is None else {"space_id": of["id"]}),
            },
            o,
        )
    id = await upload(api, o)

    result = await call(api, auth(editor), "documents_update", id=id, contact="ACME")

    assert data(result) == {"id": shorts(id).pop(), "filed_away": True}
    assert "not found" in error(await call(api, auth(editor), "documents_get", id=id))
    owners = data(await call(api, o, "documents_update", id=id, title="Seen by the owner"))
    assert owners["document"]["space_id"] == private["id"]
    assert "rules" not in owners  # no change that triggers it


async def test_expected_list_names_the_series_one_may_read(api: Api, scene: Scene) -> None:
    """Read only (#145): the scene's documents make no series."""
    found = data(await call(api, scene.headers["owner"], "expected_list"))
    assert found == {}
