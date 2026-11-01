"""Parity of MCP with the REST API (Tobi, 01.11.2026, umsetzungsplan "MCP"): every endpoint is
served by a tool, planned for one, or left out for a reason. A new endpoint fails this test
until someone decides which."""

import json
from dataclasses import dataclass
from enum import StrEnum

from lekto.adapters.inbound.mcp.registry import split_name
from lekto.adapters.inbound.rest import PREFIX
from tests.unit.adapters.mcp.support import listed_tools
from tests.unit.adapters.rest.support import Api, Scene
from tests.unit.test_openapi import CHECKED_IN


class Excluded(StrEnum):
    ACCOUNT = "one's own account and signing in"
    MANAGING = "managing Lekto: users, spaces, webhooks, lenses, pipeline runs, training, index"
    MASTER_DATA = "master data is only read"
    RULES = "rules are only read; made, changed and applied in the web UI"
    UPLOAD = "no uploads"
    WEB_UI = "cannot be undone or changes many at once: the client links to the web UI"
    RELATIONS = "relations are set in the web UI: a document's text could relate it unnoticed"
    VLM = "sending pages to a VLM is a person's decision"
    BROWSER = "for the browser: event streams, files, page layout, references in addresses"
    INTERNALS = "raw internals of the processing: the calls of the language model"
    NOT_FOR_CLIENTS = "health checks and the callbacks of external tasks"


@dataclass(frozen=True)
class Planned:
    """Served by a tool of a later pull request of the plan (a new one, or one extended)."""

    pr: int
    tool: str


ACCOUNT, MANAGING, MASTER_DATA = Excluded.ACCOUNT, Excluded.MANAGING, Excluded.MASTER_DATA
RULES, WEB_UI, BROWSER = Excluded.RULES, Excluded.WEB_UI, Excluded.BROWSER

ENDPOINTS: dict[str, str | Excluded | Planned] = {
    # auth
    "POST /auth/login": ACCOUNT,
    "GET /auth/oidc": ACCOUNT,
    "GET /auth/oidc/login": ACCOUNT,
    "GET /auth/oidc/callback": ACCOUNT,
    "POST /auth/logout": ACCOUNT,
    "GET /auth/me": ACCOUNT,
    "GET /auth/me/profile": ACCOUNT,
    "PATCH /auth/me/profile": ACCOUNT,
    "POST /auth/password": ACCOUNT,
    "DELETE /auth/sessions": ACCOUNT,
    "POST /auth/totp": ACCOUNT,
    "POST /auth/totp/confirm": ACCOUNT,
    "POST /auth/totp/disable": ACCOUNT,
    "POST /auth/totp/recovery-codes": ACCOUNT,
    "GET /auth/tokens": ACCOUNT,
    "POST /auth/tokens": ACCOUNT,
    "DELETE /auth/tokens/{id}": ACCOUNT,
    "POST /auth/oidc/link": ACCOUNT,
    "DELETE /auth/oidc/link": ACCOUNT,
    # automation, classifier, jobs, pipeline, search: the page "System"
    "GET /automation": Planned(6, "system_status"),
    "GET /automation/signals": Planned(6, "system_status"),
    "GET /automation/holders": MANAGING,
    "GET /automation/holders/cases": MANAGING,
    "GET /classifier": Planned(6, "system_status"),
    "GET /classifier/models": MANAGING,
    "POST /classifier/train": MANAGING,
    "GET /jobs/summary": Planned(6, "system_status"),
    "GET /jobs": Planned(6, "system_status"),
    "GET /jobs/durations": Planned(6, "system_status"),
    "POST /jobs/{id}/retry": MANAGING,
    "GET /pipeline": Planned(6, "system_status"),
    "POST /pipeline/reparse": MANAGING,
    "POST /pipeline/relate": MANAGING,
    "POST /pipeline/render-pages": MANAGING,
    "POST /pipeline/read-facts": MANAGING,
    "GET /search/status": Planned(6, "system_status"),
    "POST /search/reindex": MANAGING,
    "POST /search/check": MANAGING,
    # documents
    "POST /documents": Excluded.UPLOAD,
    "GET /documents": "documents_list",
    "GET /documents/count": "documents_list",
    "GET /documents/facets": "documents_list",
    "POST /documents/search": "documents_search",
    "POST /documents/search/warm": BROWSER,
    "GET /documents/stream": BROWSER,
    "POST /documents/bulk": WEB_UI,
    "GET /documents/bulk/{id}": WEB_UI,
    "GET /documents/{id}": "documents_get",
    "PATCH /documents/{id}": "documents_update",
    "DELETE /documents/{id}": WEB_UI,
    "POST /documents/{id}/move": WEB_UI,
    "POST /documents/{id}/reprocess": WEB_UI,
    "POST /documents/{id}/retry": Planned(5, "documents_retry"),
    "POST /documents/{id}/vision": Excluded.VLM,
    "POST /documents/{id}/dry-run": "documents_update",
    "GET /documents/{id}/text": "documents_text",
    "GET /documents/{id}/pages/{number}": "documents_page",
    "GET /documents/{id}/log": "documents_log",
    "GET /documents/{id}/facts": "documents_get",
    "GET /documents/{id}/reading": "documents_get",
    "GET /documents/{id}/review": "documents_get",
    "GET /documents/{id}/original": BROWSER,
    "GET /documents/{id}/archive": BROWSER,
    "GET /documents/{id}/preview": BROWSER,
    "GET /documents/{id}/structure": BROWSER,
    "GET /documents/{id}/files": BROWSER,
    "GET /documents/{id}/places/{kind}/{ref}": BROWSER,
    "GET /documents/{id}/exchanges/{node}": Excluded.INTERNALS,
    "POST /documents/{id}/facts/decisions": Planned(5, "facts_decide"),
    "POST /documents/{id}/confirm": Planned(5, "inbox_confirm"),
    "PUT /documents/{id}/seen": Planned(5, "inbox_mark_seen"),
    "DELETE /documents/{id}/seen": Planned(5, "inbox_mark_seen"),
    "GET /documents/{id}/relations": "documents_get",
    "POST /documents/{id}/relations": Excluded.RELATIONS,
    "DELETE /documents/{id}/relations/{other_id}": Excluded.RELATIONS,
    "GET /events": BROWSER,
    "GET /expected": "expected_list",
    # inbox
    "GET /inbox": Planned(5, "inbox_list"),
    "GET /inbox/summary": Planned(5, "inbox_list"),
    "POST /inbox/seen": WEB_UI,
    # identifiers
    "GET /identifiers/open": Planned(6, "identifiers_open"),
    "POST /identifiers/open/search": Planned(6, "identifiers_open"),
    "GET /identifiers/open/summary": Planned(6, "identifiers_open"),
    "GET /identifiers/open/{kind}/{ref}": Planned(6, "identifiers_open"),
    "POST /identifiers/open/decisions": MASTER_DATA,
    "POST /identifiers/open/recommended": MASTER_DATA,
    "POST /identifiers/refs": BROWSER,
    "GET /identifiers/refs/{kind}/{ref}": BROWSER,
    "GET /identifiers/places/{kind}/{ref}": Planned(6, "identifiers_find"),
    # master data
    "GET /contacts": Planned(6, "contacts_list"),
    "POST /contacts": MASTER_DATA,
    "GET /contacts/{id}": Planned(6, "contacts_get"),
    "PATCH /contacts/{id}": MASTER_DATA,
    "DELETE /contacts/{id}": MASTER_DATA,
    "POST /contacts/logos/fetch": MASTER_DATA,
    "POST /contacts/{id}/identifiers": MASTER_DATA,
    "GET /contacts/{id}/logo": BROWSER,
    "PUT /contacts/{id}/logo": MASTER_DATA,
    "DELETE /contacts/{id}/logo": MASTER_DATA,
    "POST /contacts/{id}/logo/fetch": MASTER_DATA,
    "GET /document-types": Planned(6, "document_types_list"),
    "POST /document-types": MASTER_DATA,
    "GET /document-types/{id}": Planned(6, "document_types_list"),
    "PATCH /document-types/{id}": MASTER_DATA,
    "DELETE /document-types/{id}": MASTER_DATA,
    "PUT /document-types/{id}/fields": MASTER_DATA,
    "GET /tags": "tags_list",
    "POST /tags": MASTER_DATA,
    "GET /tags/{id}": "tags_list",
    "PATCH /tags/{id}": MASTER_DATA,
    "DELETE /tags/{id}": MASTER_DATA,
    "GET /fields": Planned(6, "fields_list"),
    "POST /fields": MASTER_DATA,
    "GET /fields/{id}": Planned(6, "fields_list"),
    "PATCH /fields/{id}": MASTER_DATA,
    "DELETE /fields/{id}": MASTER_DATA,
    # rules
    "GET /rules": Planned(6, "rules_list"),
    "POST /rules": RULES,
    "GET /rules/{id}": Planned(6, "rules_get"),
    "PUT /rules/{id}": RULES,
    "PATCH /rules/{id}": RULES,
    "DELETE /rules/{id}": RULES,
    "GET /rules/{id}/versions": Planned(6, "rules_get"),
    "GET /rules/{id}/versions/{number}": Planned(6, "rules_get"),
    "POST /rules/{id}/apply/preview": RULES,
    "GET /rules/{id}/apply/hits/{document_id}": RULES,
    "POST /rules/{id}/apply": RULES,
    "GET /rule-applications/{id}": RULES,
    "POST /templates/preview": RULES,
    # lenses, spaces, users, webhooks
    "GET /lenses": Planned(6, "lenses_list"),
    "POST /lenses": MANAGING,
    "PUT /lenses/order": MANAGING,
    "GET /lenses/{id}": Planned(6, "lenses_list"),
    "PATCH /lenses/{id}": MANAGING,
    "DELETE /lenses/{id}": MANAGING,
    "GET /spaces": Planned(6, "spaces_list"),
    "POST /spaces": MANAGING,
    "GET /spaces/{id}": Planned(6, "spaces_list"),
    "PATCH /spaces/{id}": MANAGING,
    "DELETE /spaces/{id}": MANAGING,
    "PUT /spaces/{id}/members/{user_id}": MANAGING,
    "DELETE /spaces/{id}/members/{user_id}": MANAGING,
    "GET /users": MANAGING,
    "POST /users": MANAGING,
    "GET /users/{id}": MANAGING,
    "PATCH /users/{id}": MANAGING,
    "DELETE /users/{id}": MANAGING,
    "GET /users/{id}/profile": MANAGING,
    "PATCH /users/{id}/profile": MANAGING,
    "POST /users/{id}/password": MANAGING,
    "DELETE /users/{id}/totp": MANAGING,
    "DELETE /users/{id}/oidc": MANAGING,
    "GET /users/{id}/removal": MANAGING,
    "GET /webhooks": MANAGING,
    "POST /webhooks": MANAGING,
    "GET /webhooks/{id}": MANAGING,
    "PATCH /webhooks/{id}": MANAGING,
    "DELETE /webhooks/{id}": MANAGING,
    "POST /webhooks/{id}/secret": MANAGING,
    "DELETE /webhooks/{id}/secret": MANAGING,
    "GET /webhooks/{id}/deliveries": MANAGING,
    "GET /webhooks/{id}/deliveries/summary": MANAGING,
    "POST /webhooks/{id}/test": MANAGING,
    # not for clients
    "GET /health": Excluded.NOT_FOR_CLIENTS,
    "POST /external/tasks/{id}/result": Excluded.NOT_FOR_CLIENTS,
    "GET /external/tasks/{id}/files/{name}": Excluded.NOT_FOR_CLIENTS,
}
PLANNED_PRS = {5, 6}
"""The pull requests of the plan that add tools; after the last, nothing is planned."""


def endpoints() -> set[str]:
    paths = json.loads(CHECKED_IN.read_text(encoding="utf-8"))["paths"]
    return {
        f"{method.upper()} {path.removeprefix(PREFIX)}"
        for path, operations in paths.items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    }


def test_every_endpoint_is_decided() -> None:
    known, decided = endpoints(), set(ENDPOINTS)
    assert decided == known, (
        f"not decided: {sorted(known - decided)}; gone: {sorted(decided - known)}"
    )


async def test_the_tools_named_are_those_of_the_server(api: Api, scene: Scene) -> None:
    tools = {tool["name"] for tool in await listed_tools(api, scene.headers["admin"])}
    served = {
        target
        for target in ENDPOINTS.values()
        if isinstance(target, str) and not isinstance(target, Excluded)
    }
    assert served <= tools, f"no such tool: {sorted(served - tools)}"
    planned = {target.tool for target in ENDPOINTS.values() if isinstance(target, Planned)}
    assert tools <= served | planned, f"a tool without an endpoint: {sorted(tools - served)}"
    for target in ENDPOINTS.values():
        if isinstance(target, Planned):
            assert target.pr in PLANNED_PRS and split_name(target.tool) is not None, target
