"""A decision through an API token carries the token (Tobi, 01.11.2026, umsetzungsplan "MCP",
decision 11): in the log, with the verdicts and under done; one in the web UI carries none."""

from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

from lekto.adapters.inbound.rest import PREFIX
from lekto.core.domain.classification import FieldCheck, checks_to_json
from lekto.core.domain.ids import DocumentId
from lekto.core.domain.master_data import Contact
from lekto.core.domain.pipeline import (
    PERSON,
    PERSON_SPACE,
    RULES_APPLY,
    RULES_CHANGE,
    VIA_TOKEN,
    Node,
    NodeResult,
    Outcome,
)
from lekto.core.domain.reasons import written
from lekto.core.domain.relations import RelationOrigin, RelationState
from tests import builders
from tests.api import auth
from tests.builders import NOW, Returns
from tests.unit.adapters.rest.support import DOCUMENTS, Api, post, unique_pdf, upload

TOKEN = "tests"
"""The name of the token `auth` sends."""


def uncertain_contact(contact: Contact) -> NodeResult:
    check = FieldCheck(
        field="contact",
        outcome=Outcome.UNCERTAIN,
        confidence=0.6,
        reasons=(written("two contacts are alike"),),
        suggestion=str(contact.id),
    )
    return NodeResult(
        outcome=Outcome.UNCERTAIN,
        reasons=(written("contact"),),
        output={"fields": checks_to_json([check])},
    )


async def log_of(api: Api, id: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = await api.client.get(f"{DOCUMENTS}/{id}/log", headers=headers)
    assert response.status_code == 200, response.text
    entries: list[dict[str, Any]] = response.json()
    return entries


async def verdict_tokens(api: Api, id: str) -> set[str | None]:
    async with api.container.unit_of_work() as uow:
        verdicts = await uow.processing_facts.verdicts(DocumentId(UUID(id)))
    assert verdicts
    return {None if verdict.via is None else verdict.via.name for verdict in verdicts}


async def test_a_confirmation_through_a_token_carries_it(api: Api) -> None:
    owner = await api.user()
    contact = Contact.create(name="Stadtwerke", now=NOW)
    async with api.container.unit_of_work() as uow:
        await uow.contacts.add(contact)
        await uow.commit()
    api.services.pipeline.replace_executor(Node.JUDGE, Returns(uncertain_contact(contact)))
    id = await upload(api, auth(owner), content=unique_pdf("yellow"))

    confirmed = await api.client.post(
        f"{DOCUMENTS}/{id}/confirm", json={"accept_suggestions": True}, headers=auth(owner)
    )
    assert confirmed.status_code == 202, confirmed.text
    await api.drain()

    done = await api.client.get(f"{PREFIX}/inbox", params={"tab": "done"}, headers=auth(owner))
    (item,) = done.json()["items"]
    assert item["done"]["how"] == "confirmed"
    assert item["done"]["via_token"] == TOKEN
    confirmations = [
        entry for entry in await log_of(api, id, auth(owner)) if entry["model_version"] == PERSON
    ]
    assert confirmations
    for entry in confirmations:
        assert entry["output"][VIA_TOKEN]["name"] == TOKEN
    assert await verdict_tokens(api, id) == {TOKEN}


async def test_a_change_through_a_token_carries_it(api: Api) -> None:
    owner = await api.user()
    id = await upload(api, auth(owner), content=unique_pdf("changed"))

    changed = await api.client.patch(
        f"{DOCUMENTS}/{id}", json={"document_date": "2026-03-31"}, headers=auth(owner)
    )
    assert changed.status_code == 200, changed.text

    (entry,) = [
        entry
        for entry in await log_of(api, id, auth(owner))
        if entry["model_version"] == RULES_CHANGE
    ]
    (token,) = await api.services.auth.list_api_tokens(owner.id)
    assert entry["input"][VIA_TOKEN] == {"id": str(token.id), "name": TOKEN}
    assert await verdict_tokens(api, id) == {TOKEN}


async def test_a_change_in_the_web_ui_carries_no_token(api: Api) -> None:
    owner = await api.user()
    id = await upload(api, auth(owner), content=unique_pdf("in a session"))

    async with api.sign_in(owner) as session:
        changed = await session.client.patch(
            f"{DOCUMENTS}/{id}", json={"document_date": "2026-03-31"}, headers=session.headers
        )
        assert changed.status_code == 200, changed.text
        seen = await session.client.put(f"{DOCUMENTS}/{id}/seen", headers=session.headers)
        assert seen.status_code == 204

    (entry,) = [
        entry
        for entry in await log_of(api, id, auth(owner))
        if entry["model_version"] == RULES_CHANGE
    ]
    assert VIA_TOKEN not in entry["input"]
    assert await verdict_tokens(api, id) == {None}
    done = await api.client.get(f"{PREFIX}/inbox", params={"tab": "done"}, headers=auth(owner))
    (item,) = done.json()["items"]
    assert (item["done"]["how"], item["done"]["via_token"]) == ("seen", None)


async def test_a_mark_through_a_token_carries_it(api: Api) -> None:
    owner = await api.user()
    id = await upload(api, auth(owner), content=unique_pdf("seen"))

    seen = await api.client.put(f"{DOCUMENTS}/{id}/seen", headers=auth(owner))
    assert seen.status_code == 204

    done = await api.client.get(f"{PREFIX}/inbox", params={"tab": "done"}, headers=auth(owner))
    (item,) = done.json()["items"]
    assert (item["done"]["how"], item["done"]["via_token"]) == ("seen", TOKEN)


async def entries_of(api: Api, id: str, model_version: str) -> list[dict[str, Any]]:
    """The input and output of the document's log entries of `model_version`, whoever reads it
    now."""
    async with api.container.unit_of_work() as uow:
        log = await uow.processing_log.list_for(DocumentId(UUID(id)))
    return [
        {"input": entry.result.input, "output": entry.result.output}
        for entry in log
        if entry.result.model_version == model_version
    ]


async def test_relations_carry_the_token(api: Api) -> None:
    owner = await api.user()
    older = await upload(api, auth(owner), content=unique_pdf("older"))
    api.clock.advance(timedelta(minutes=1))
    newer = await upload(api, auth(owner), content=unique_pdf("newer"))

    related = await api.client.post(
        f"{DOCUMENTS}/{newer}/relations", json={"document_id": older}, headers=auth(owner)
    )
    assert related.status_code == 200, related.text

    async with api.container.unit_of_work() as uow:
        relation = await uow.document_relations.find(
            DocumentId(UUID(newer)), DocumentId(UUID(older))
        )
    assert relation is not None and relation.decided_via is not None
    assert relation.decided_via.name == TOKEN
    assert await verdict_tokens(api, newer) == {TOKEN}

    # Lekto's suggestion, rejected through the token: it stays, rejected, with the token.
    async with api.container.unit_of_work() as uow:
        suggested = replace(
            relation,
            origin=RelationOrigin.LEKTO,
            state=RelationState.SUGGESTED,
            decided_by=None,
            decided_at=None,
            decided_via=None,
        )
        await uow.document_relations.put(suggested)
        await uow.commit()
    rejected = await api.client.delete(
        f"{DOCUMENTS}/{newer}/relations/{older}", headers=auth(owner)
    )
    assert rejected.status_code == 200, rejected.text
    async with api.container.unit_of_work() as uow:
        relation = await uow.document_relations.find(
            DocumentId(UUID(newer)), DocumentId(UUID(older))
        )
    assert relation is not None and relation.state is RelationState.REJECTED
    assert relation.decided_via is not None and relation.decided_via.name == TOKEN


async def test_moves_bulk_changes_and_applied_rules_carry_the_token(api: Api) -> None:
    admin, owner, friend = await api.admin(), await api.user(), await api.user()
    o = auth(owner)
    tax = await post(api, "/tags", {"name": "Steuer"}, auth(admin))
    tagged = await upload(api, o, content=unique_pdf("tagged"))
    titled = await upload(api, o, content=unique_pdf("titled"))
    moved = await upload(api, o, content=unique_pdf("moved"))

    bulk = await api.client.post(
        f"{DOCUMENTS}/bulk",
        json={
            "document_ids": [tagged],
            "action": {"kind": "change_tags", "add_tag_ids": [tax["id"]]},
        },
        headers=o,
    )
    assert bulk.status_code == 202, bulk.text
    await builders.drain(api.services.bulk)
    (change,) = await entries_of(api, tagged, RULES_CHANGE)
    assert change["input"][VIA_TOKEN]["name"] == TOKEN

    rule = await post(
        api,
        "/rules",
        {
            "name": "Titel",
            "conditions": {"all": [{"field": "channel", "op": "is", "value": "api"}]},
            "actions": [{"type": "set_title", "template": "Steuer {{ filename }}"}],
        },
        o,
    )
    applied = await api.client.post(
        f"{PREFIX}/rules/{rule['id']}/apply",
        json={"version": 1, "document_ids": [titled]},
        headers=o,
    )
    assert applied.status_code == 202, applied.text
    await builders.drain(api.services.rule_applications)
    (application,) = await entries_of(api, titled, RULES_APPLY)
    assert application["input"][VIA_TOKEN]["name"] == TOKEN

    theirs = (await api.client.get(f"{PREFIX}/users/{friend.id}", headers=o)).json()
    handed = await api.client.post(
        f"{DOCUMENTS}/{moved}/move", json={"space_id": theirs["personal_space_id"]}, headers=o
    )
    assert handed.status_code == 204, handed.text
    (choice,) = await entries_of(api, moved, PERSON_SPACE)
    assert choice["input"][VIA_TOKEN]["name"] == TOKEN
    assert await verdict_tokens(api, moved) == {TOKEN}


async def test_moves_on_deleting_a_user_carry_the_token(api: Api) -> None:
    """Documents move as an admin moves them by hand, through their token too."""
    admin, anna = await api.admin("root"), await api.user("anna")
    document = await upload(api, auth(anna), content=unique_pdf("anna's"))
    url = f"{PREFIX}/users/{anna.id}"
    (blocking,) = (await api.client.get(f"{url}/removal", headers=auth(admin))).json()[
        "blocking_spaces"
    ]
    mine = await api.client.get(f"{PREFIX}/users/{admin.id}", headers=auth(admin))
    settle = {
        "spaces": [{"space_id": blocking["space_id"], "move_to": mine.json()["personal_space_id"]}]
    }

    deleted = await api.client.request("DELETE", url, json=settle, headers=auth(admin))
    assert deleted.status_code == 204, deleted.text

    (choice,) = await entries_of(api, document, PERSON_SPACE)
    assert choice["input"][VIA_TOKEN]["name"] == TOKEN


async def test_all_seen_through_a_token_carries_it(api: Api) -> None:
    owner = await api.user()
    id = await upload(api, auth(owner), content=unique_pdf("all seen"))

    marked = await api.client.post(f"{PREFIX}/inbox/seen", headers=auth(owner))
    assert marked.status_code == 200, marked.text

    done = await api.client.get(f"{PREFIX}/inbox", params={"tab": "done"}, headers=auth(owner))
    (item,) = done.json()["items"]
    assert (item["document"]["id"], item["done"]["via_token"]) == (id, TOKEN)


async def test_an_upload_into_a_chosen_space_carries_the_token(api: Api) -> None:
    owner = await api.user()
    space = (await api.client.get(f"{PREFIX}/users/{owner.id}", headers=auth(owner))).json()
    id = await upload(
        api, auth(owner), content=unique_pdf("chosen"), space=space["personal_space_id"]
    )

    (choice,) = await entries_of(api, id, PERSON_SPACE)
    assert choice["input"][VIA_TOKEN]["name"] == TOKEN
