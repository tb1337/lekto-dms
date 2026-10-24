"""The rights matrix over HTTP: every actor against every endpoint that touches a document,
a space or master data. Each case runs on a fresh scene.

Actors: the owner (who made the shared space and edits it); a reader of it (`read`); a second
editor of it (`writer`, `edit`); a stranger; an admin (no member); the owner's `read` token; an
expired token; a revoked token; a deactivated user who was an editor; a deactivated admin.

Documents in the shared space: green (its readers see it), yellow and in processing (its
editors and admins only). Who uploaded a document has no rights for it. Admins have every
right and see everything (Tobi, 08.10.2026); lists show their reach unless they ask for all
users. Hidden documents and spaces are "not found" (404), exactly as missing ones.
"""

from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType
from typing import Any
from uuid import UUID

import httpx2
import pytest

from lekto.adapters.inbound.rest import PREFIX
from lekto.core.domain.encoding import base64url
from lekto.core.domain.ids import new_id
from tests.contracts.images import image
from tests.unit.adapters.rest.support import ACTORS, DENIED, Api, Scene, build_scene

type Call = Callable[[Scene, httpx2.AsyncClient, dict[str, str], str], Awaitable[httpx2.Response]]


def doc(method: str, suffix: str = "", body: Any = None) -> Call:
    async def call(
        scene: Scene, client: httpx2.AsyncClient, headers: dict[str, str], which: str
    ) -> httpx2.Response:
        url = f"{PREFIX}/documents/{scene.document(which)}{suffix}"
        payload = body(scene) if callable(body) else body
        return await client.request(method, url, json=payload, headers=headers)

    return call


HIDDEN = {"stranger": 404}

# Each actor who may read the green document reads it.
READ_ALL: Mapping[str, int] = MappingProxyType(
    {
        "owner": 200,
        "reader": 200,
        "writer": 200,
        "read_token": 200,
        "admin": 200,
        **HIDDEN,
        **DENIED,
    }
)

# For the green document in the shared space.
GREEN: dict[str, tuple[Call, Mapping[str, int]]] = {
    "read": (doc("GET"), READ_ALL),
    "original": (doc("GET", "/original"), READ_ALL),
    "archive": (doc("GET", "/archive"), READ_ALL),
    "preview": (doc("GET", "/preview"), READ_ALL),
    "text": (doc("GET", "/text"), READ_ALL),
    "structure": (doc("GET", "/structure"), READ_ALL),
    "page": (doc("GET", "/pages/1"), READ_ALL),
    "files": (doc("GET", "/files"), READ_ALL),
    "change": (
        doc("PATCH", body={"title": "Changed"}),
        {
            "owner": 200,
            "reader": 403,
            "writer": 200,
            "read_token": 403,
            "admin": 200,
            **HIDDEN,
            **DENIED,
        },
    ),
    "dry_run": (
        doc("POST", "/dry-run", {"title": "Changed"}),
        {
            "owner": 200,
            "reader": 403,
            "writer": 200,
            "read_token": 403,
            "admin": 200,
            **HIDDEN,
            **DENIED,
        },
    ),
    "move": (
        doc("POST", "/move", lambda scene: {"space_id": str(scene.own_space.id)}),
        {
            "owner": 204,
            "reader": 403,
            "writer": 404,  # the owner's private space is none of theirs
            "stranger": 404,
            "admin": 204,  # admins move any document into any space
            "read_token": 403,
            **DENIED,
        },
    ),
    "delete": (
        doc("DELETE"),
        {
            "owner": 204,
            "reader": 403,
            "writer": 204,
            "read_token": 403,
            "admin": 204,
            **HIDDEN,
            **DENIED,
        },
    ),
    "log": (
        doc("GET", "/log"),
        {
            "owner": 200,
            "reader": 403,
            "writer": 200,
            "read_token": 200,
            "admin": 200,
            **HIDDEN,
            **DENIED,
        },
    ),
    "exchanges": (
        doc("GET", "/exchanges/signal_llm"),
        {
            "owner": 200,
            "reader": 403,
            "writer": 200,
            "read_token": 200,
            "admin": 200,
            **HIDDEN,
            **DENIED,
        },
    ),
    "retry": (
        doc("POST", "/retry"),
        {
            "owner": 409,
            "reader": 403,
            "writer": 409,
            "read_token": 403,
            "admin": 409,
            **HIDDEN,
            **DENIED,
        },
    ),
    "reprocess": (
        doc("POST", "/reprocess", {"from_node": "parse"}),
        {
            "owner": 202,
            "reader": 403,
            "writer": 202,
            "read_token": 403,
            "admin": 202,
            **HIDDEN,
            **DENIED,
        },
    ),
    "review": (
        doc("GET", "/review"),
        {
            "owner": 200,
            "reader": 403,
            "writer": 200,
            "read_token": 200,
            "admin": 200,
            **HIDDEN,
            **DENIED,
        },
    ),
    "confirm": (
        doc("POST", "/confirm", {}),
        {
            "owner": 409,
            "reader": 403,
            "writer": 409,
            "read_token": 403,
            "admin": 409,
            **HIDDEN,
            **DENIED,
        },
    ),
}

CASES = [
    pytest.param(name, actor, expected.get(actor), id=f"{name}-{actor}")
    for name, (_, expected) in GREEN.items()
    for actor in ACTORS
]


@pytest.mark.parametrize(("operation", "actor", "expected"), CASES)
async def test_green_document(api: Api, operation: str, actor: str, expected: int) -> None:
    scene = await build_scene(api)
    call, _ = GREEN[operation]
    response = await call(scene, api.client, scene.headers[actor], "green")
    assert response.status_code == expected, response.text
    if actor in HIDDEN:
        assert response.json()["detail"] == f"document {scene.green} not found"


HIDDEN_FROM_READERS = [
    "read",
    "original",
    "archive",
    "preview",
    "text",
    "structure",
    "page",
    "files",
    "change",
    "dry_run",
    "delete",
    "log",
    "exchanges",
    "review",
]


@pytest.mark.parametrize("which", ["yellow", "processing"])
@pytest.mark.parametrize("operation", HIDDEN_FROM_READERS)
async def test_yellow_and_processing_documents_are_the_editors_and_admins(
    api: Api, which: str, operation: str
) -> None:
    scene = await build_scene(api)
    call, _ = GREEN[operation]
    for actor in ("reader", "stranger"):
        response = await call(scene, api.client, scene.headers[actor], which)
        assert response.status_code == 404, (actor, response.text)
        assert response.json()["detail"] == f"document {scene.document(which)} not found"
    for actor in ("owner", "writer", "admin"):
        response = await call(scene, api.client, scene.headers[actor], which)
        if which == "processing" and operation in {"archive", "preview", "page"}:
            assert response.status_code == 404  # not made yet
        elif which == "processing" and operation in {"text", "structure"}:
            assert response.status_code == 409  # not parsed yet
        else:
            assert response.status_code in {200, 204}, (actor, response.text)
        if operation == "delete":
            break  # gone for the admin as well


async def test_the_inbox_is_the_editors_and_all_of_them_for_admins(api: Api) -> None:
    """The documents in processing, yellow and new (green by itself, the green one) in the
    spaces a user edits; reading a space never brings one in; admins have every user's with
    `all_users`."""
    scene = await build_scene(api)
    open = [scene.processing, scene.yellow, scene.green]  # newest first
    for actor, expected in [("owner", open), ("read_token", open), ("writer", open)] + [
        (actor, []) for actor in ("reader", "stranger", "admin")
    ]:
        response = await api.client.get(f"{PREFIX}/inbox", headers=scene.headers[actor])
        assert response.status_code == 200, response.text
        assert [item["document"]["id"] for item in response.json()["items"]] == expected, actor
        summary = await api.client.get(f"{PREFIX}/inbox/summary", headers=scene.headers[actor])
        assert summary.json()["open"] == len(expected), actor
    every = await api.client.get(
        f"{PREFIX}/inbox", params={"all_users": True}, headers=scene.headers["admin"]
    )
    assert [item["document"]["id"] for item in every.json()["items"]] == open
    for path, method in INBOX_LISTS:
        for actor in ("owner", "reader", "stranger", "read_token"):
            response = await api.client.request(
                method, path, params={"all_users": True}, headers=scene.headers[actor]
            )
            assert response.status_code == 403, (path, actor)
        for actor in DENIED:
            response = await api.client.request(method, path, headers=scene.headers[actor])
            assert response.status_code == 401, (path, actor)
    confirm = doc("POST", "/confirm", {})
    for actor in ("reader", "stranger"):
        response = await confirm(scene, api.client, scene.headers[actor], "yellow")
        assert response.status_code == 404, actor
    denied = await confirm(scene, api.client, scene.headers["read_token"], "yellow")
    assert denied.status_code == 403
    by_editor = await confirm(scene, api.client, scene.headers["writer"], "yellow")
    assert by_editor.status_code == 202, by_editor.text


INBOX_LISTS = [
    (f"{PREFIX}/inbox", "GET"),
    (f"{PREFIX}/inbox/summary", "GET"),
    (f"{PREFIX}/inbox/seen", "POST"),
]

# Seen and new again: whoever reads the document (it counts for an inbox it can stand in).
SEEN = {
    "owner": 204,
    "reader": 204,
    "writer": 204,
    "read_token": 403,
    "admin": 204,
    **HIDDEN,
    **DENIED,
}


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize("which", ["green", "yellow", "processing"])
async def test_seen_is_marked_by_whoever_reads_the_document(
    api: Api, method: str, which: str
) -> None:
    scene = await build_scene(api)
    call = doc(method, "/seen")
    hidden = which != "green"
    for actor in ACTORS:
        expected = SEEN[actor]
        if hidden and actor == "reader":
            expected = 404
        response = await call(scene, api.client, scene.headers[actor], which)
        assert response.status_code == expected, (actor, response.text)


async def test_hidden_and_missing_documents_look_alike(api: Api) -> None:
    scene = await build_scene(api)
    missing = "01999d5e-8a7f-7c1e-b6a3-2f4d5e6f7a8b"
    for which, id in (("hidden", scene.yellow), ("missing", missing)):
        response = await api.client.get(f"{PREFIX}/documents/{id}", headers=scene.headers["reader"])
        assert response.status_code == 404, which
        assert response.json() == {
            "type": "about:blank",
            "title": "Not Found",
            "status": 404,
            "detail": f"document {id} not found",
            "reason": {"code": "not_found", "params": {"kind": "document", "id": id}},
        }


# --- lists, filters, pages ----------------------------------------------------------------------


async def listed(scene: Scene, actor: str, **params: Any) -> set[str]:
    found: set[str] = set()
    cursor = None
    while True:
        query = {**params, "limit": 1, **({"cursor": cursor} if cursor else {})}
        response = await scene.api.client.get(
            f"{PREFIX}/documents", params=query, headers=scene.headers[actor]
        )
        assert response.status_code == 200, response.text
        page = response.json()
        found |= {item["id"] for item in page["items"]}
        cursor = page["next_cursor"]
        if cursor is None:
            return found


async def test_lists_show_only_readable_documents(api: Api) -> None:
    scene = await build_scene(api)
    everything = {scene.green, scene.yellow, scene.processing}
    assert await listed(scene, "owner") == everything
    assert await listed(scene, "read_token") == everything
    assert await listed(scene, "writer") == everything  # editors see every lane
    assert await listed(scene, "reader") == {scene.green}
    assert await listed(scene, "reader", lane="yellow") == set()
    assert await listed(scene, "reader", lane="processing") == set()
    assert await listed(scene, "reader", space_id=str(scene.shared.id)) == {scene.green}
    for actor in ("stranger", "admin"):
        assert await listed(scene, actor) == set()
        assert await listed(scene, actor, space_id=str(scene.shared.id)) == set()
        assert await listed(scene, actor, contact_id=scene.contact) == set()
    # Admins see every document when they ask for all users; nobody else may ask.
    assert await listed(scene, "admin", all_users=True) == everything
    assert await listed(scene, "admin", all_users=True, lane="yellow") == {scene.yellow}
    for actor in ("owner", "reader", "stranger", "read_token"):
        response = await api.client.get(
            f"{PREFIX}/documents", params={"all_users": True}, headers=scene.headers[actor]
        )
        assert response.status_code == 403, actor
    assert await listed(scene, "owner", lane=["yellow", "processing"]) == {
        scene.yellow,
        scene.processing,
    }
    for actor in ("expired_token", "revoked_token", "deactivated", "deactivated_admin"):
        response = await api.client.get(f"{PREFIX}/documents", headers=scene.headers[actor])
        assert response.status_code == 401


async def test_a_cursor_does_not_reveal_hidden_documents(api: Api) -> None:
    """Paging after a hidden document's id answers as after an id that does not exist, for
    every sort: nothing about the hidden one shows (#74). By arrival, the id alone places the
    page, and only readable documents follow."""
    scene = await build_scene(api)
    reader = scene.headers["reader"]
    hidden, unknown = (base64url(UUID(id).bytes) for id in (scene.yellow, str(new_id())))
    for sort in ("-created_at", "created_at", "title", "-document_date"):
        answers = []
        for cursor in (hidden, unknown):
            response = await api.client.get(
                f"{PREFIX}/documents", params={"cursor": cursor, "sort": sort}, headers=reader
            )
            answers.append((response.status_code, response.json()["detail"]))
        assert answers[0] == answers[1], sort
        assert answers[0][0] == 422, sort
    owner = await api.client.get(
        f"{PREFIX}/documents", params={"cursor": hidden}, headers=scene.headers["owner"]
    )
    assert owner.status_code == 200


# --- event streams ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("actor", "which", "expected"),
    [
        ("reader", "yellow", 404),
        ("reader", "processing", 404),
        ("stranger", "green", 404),
        ("expired_token", "green", 401),
        ("deactivated", "green", 401),
        ("deactivated_admin", "green", 401),
    ],
)
async def test_event_streams_of_one_document(
    api: Api, actor: str, which: str, expected: int
) -> None:
    scene = await build_scene(api)
    response = await api.client.get(
        f"{PREFIX}/events",
        params={"document_id": scene.document(which)},
        headers=scene.headers[actor],
    )
    assert response.status_code == expected


# --- spaces ------------------------------------------------------------------------------------


async def test_spaces(api: Api) -> None:
    scene = await build_scene(api)
    url = f"{PREFIX}/spaces/{scene.shared.id}"
    owner_view = await api.client.get(url, headers=scene.headers["owner"])
    assert owner_view.status_code == 200
    assert {m["role"] for m in owner_view.json()["members"]} == {"read", "edit"}
    reader_view = (await api.client.get(url, headers=scene.headers["reader"])).json()
    assert reader_view["role"] == "read" and len(reader_view["members"]) == 4
    assert (await api.client.get(url, headers=scene.headers["stranger"])).status_code == 404
    listed = (await api.client.get(f"{PREFIX}/spaces", headers=scene.headers["stranger"])).json()
    assert str(scene.shared.id) not in str(listed)
    # Admins see and manage every space (Tobi, 08.10.2026).
    admin_view = (await api.client.get(url, headers=scene.headers["admin"])).json()
    assert admin_view["role"] == "edit"
    own = (await api.client.get(f"{PREFIX}/spaces", headers=scene.headers["admin"])).json()
    assert str(scene.shared.id) not in {d["id"] for d in own}  # the list follows the reach
    every = (
        await api.client.get(
            f"{PREFIX}/spaces", params={"all_users": True}, headers=scene.headers["admin"]
        )
    ).json()
    assert {str(scene.shared.id), str(scene.own_space.id)} <= {d["id"] for d in every}
    changes = [
        ("PATCH", url, {"name": "Renamed"}),
        ("PUT", f"{url}/members/{UUID(int=1)}", {"role": "read"}),
        ("DELETE", f"{url}/members/{UUID(int=1)}", None),
        ("DELETE", url, None),
    ]
    expected = {"reader": 403, "stranger": 404, "read_token": 403}
    for method, target, body in changes:
        for actor, status in {**expected, **DENIED}.items():
            response = await api.client.request(
                method, target, json=body, headers=scene.headers[actor]
            )
            assert response.status_code == status, (method, target, actor)
    renamed = await api.client.patch(url, json={"name": "Renamed"}, headers=scene.headers["writer"])
    assert renamed.status_code == 200
    by_admin = await api.client.patch(url, json={"name": "Again"}, headers=scene.headers["admin"])
    assert by_admin.status_code == 200 and by_admin.json()["name"] == "Again"
    not_empty = await api.client.delete(url, headers=scene.headers["admin"])
    assert not_empty.status_code == 409


# --- master data and users ----------------------------------------------------------------------


MASTER_DATA = {
    "contacts": {"name": "X"},
    "document-types": {"name": "X"},
    "tags": {"name": "X"},
    "fields": {"name": "X", "data_type": "text"},
}
# Changes of an item besides renaming and deleting, also for admins only: (method, path below
# the item, body).
ITEM_CHANGES: dict[str, list[tuple[str, str, Any]]] = {
    "contacts": [("POST", "/identifiers", {"kind": "customer_number", "value": "2004-7718"})],
    "document-types": [("PUT", "/fields", {"fields": []})],
}
NOT_ADMIN = {"owner": 403, "reader": 403, "writer": 403, "stranger": 403, "read_token": 403}


@pytest.mark.parametrize("kind", MASTER_DATA)
async def test_master_data_is_read_by_all_and_changed_by_admins(api: Api, kind: str) -> None:
    scene = await build_scene(api)
    url = f"{PREFIX}/{kind}"
    for actor in ("owner", "reader", "stranger", "admin", "read_token"):
        assert (await api.client.get(url, headers=scene.headers[actor])).status_code == 200
    for actor in DENIED:
        assert (await api.client.get(url, headers=scene.headers[actor])).status_code == 401
    body = MASTER_DATA[kind]
    for actor, status in {**NOT_ADMIN, **DENIED}.items():
        response = await api.client.post(url, json=body, headers=scene.headers[actor])
        assert response.status_code == status, actor
    created = await api.client.post(url, json=body, headers=scene.headers["admin"])
    assert created.status_code == 201
    item = f"{url}/{created.json()['id']}"
    for actor in ("owner", "reader", "stranger", "read_token"):
        assert (await api.client.get(item, headers=scene.headers[actor])).status_code == 200
    changes = [("PATCH", "", {"name": "Y"}), ("DELETE", "", None), *ITEM_CHANGES.get(kind, [])]
    for method, path, change in changes:
        for actor, status in {**NOT_ADMIN, **DENIED}.items():
            response = await api.client.request(
                method, f"{item}{path}", json=change, headers=scene.headers[actor]
            )
            assert response.status_code == status, (method, path, actor)
    for method, path, change in ITEM_CHANGES.get(kind, []):
        response = await api.client.request(
            method, f"{item}{path}", json=change, headers=scene.headers["admin"]
        )
        assert response.status_code == 200, (method, path, response.text)
    renamed = await api.client.patch(item, json={"name": "Y"}, headers=scene.headers["admin"])
    assert renamed.status_code == 200
    assert (await api.client.delete(item, headers=scene.headers["admin"])).status_code == 204


async def test_a_contacts_logo_is_read_by_all_and_changed_by_admins(api: Api) -> None:
    scene = await build_scene(api)
    url = f"{PREFIX}/contacts/{scene.contact}/logo"
    files = {"file": ("logo.png", image((64, 64)), "image/png")}
    for actor, status in {**NOT_ADMIN, **DENIED}.items():
        response = await api.client.put(url, files=files, headers=scene.headers[actor])
        assert response.status_code == status, actor
    uploaded = await api.client.put(url, files=files, headers=scene.headers["admin"])
    assert uploaded.status_code == 200
    for actor in ("owner", "reader", "stranger", "admin", "read_token"):
        assert (await api.client.get(url, headers=scene.headers[actor])).status_code == 200
    for actor in DENIED:
        assert (await api.client.get(url, headers=scene.headers[actor])).status_code == 401
    for actor, status in {**NOT_ADMIN, **DENIED}.items():
        response = await api.client.delete(url, headers=scene.headers[actor])
        assert response.status_code == status, actor
        response = await api.client.post(f"{url}/fetch", headers=scene.headers[actor])
        assert response.status_code == status, actor
    assert (await api.client.delete(url, headers=scene.headers["admin"])).status_code == 204


async def test_users_are_managed_by_admins(api: Api) -> None:
    scene = await build_scene(api)
    owner_list = (await api.client.get(f"{PREFIX}/users", headers=scene.headers["owner"])).json()
    assert all(set(user) == {"id", "username", "personal_space_id"} for user in owner_list)
    assert "deactivated" not in {user["username"] for user in owner_list}
    admin_list = (await api.client.get(f"{PREFIX}/users", headers=scene.headers["admin"])).json()
    assert {"role", "active"} <= set(admin_list[0])
    assert "deactivated" in {user["username"] for user in admin_list}
    target = f"{PREFIX}/users/{scene.owner.id}"
    for method, path, body in [
        ("POST", f"{PREFIX}/users", {"username": "new"}),
        ("PATCH", target, {}),
        ("PATCH", target, {"role": "admin"}),
        ("POST", f"{target}/password", {"password": "a long new password"}),
        ("DELETE", f"{target}/totp", None),
        ("DELETE", f"{target}/oidc", None),
        ("DELETE", target, None),
    ]:
        for actor, status in {**NOT_ADMIN, **DENIED}.items():
            response = await api.client.request(
                method, path, json=body, headers=scene.headers[actor]
            )
            assert response.status_code == status, (method, path, actor)
    account = (await api.client.get(target, headers=scene.headers["admin"])).json()
    assert account["has_password"] is True and account["totp_enabled"] is False
    summary = (await api.client.get(target, headers=scene.headers["reader"])).json()
    assert set(summary) == {"id", "username", "personal_space_id"}
