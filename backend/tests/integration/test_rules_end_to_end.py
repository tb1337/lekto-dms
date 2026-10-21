"""Milestone M7 end to end: a user rule made over the REST API files arriving documents into
another space of the owner and tags them; the processing log names the rule and its version.
Real API server (Uvicorn) and worker; OCR and parser are fakes that bring the text of the test.
Two set-ups: SQLite with the filesystem, Postgres with S3 (Garage)."""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from lekto.adapters.inbound.rest import PREFIX
from lekto.adapters.outbound.sql import Database
from lekto.core.domain.users import Role, User
from lekto.core.ports.object_store import ObjectStore
from tests.api import auth
from tests.integration.e2e import DOCUMENTS, System, TextOcr, TextParser, running_system


class RulesSystem(System):
    async def rules_entry(self, user: User, id: str) -> dict[str, Any]:
        """The log entry of the node `apply_rules`."""
        response = await self.client.get(f"{DOCUMENTS}/{id}/log", headers=auth(user))
        assert response.status_code == 200, response.text
        (entry,) = [item for item in response.json() if item["node"] == "apply_rules"]
        found: dict[str, Any] = entry
        return found


@pytest.fixture
async def system(stores: tuple[Database, ObjectStore]) -> AsyncIterator[RulesSystem]:
    async with running_system(RulesSystem, stores, ocr=TextOcr(), parser=TextParser()) as system:
        yield system


async def test_a_rule_of_the_personal_space_files_and_tags_arrivals(system: RulesSystem) -> None:
    admin, owner = await system.user(Role.ADMIN), await system.user()
    energy = await system.post(admin, "/tags", {"name": "Energie"})
    space = await system.post(owner, "/spaces", {"name": "Strom"})
    body: dict[str, Any] = {
        "name": "Stromrechnungen",
        "triggers": ["ingest"],
        "conditions": {
            "all": [
                {"field": "text", "op": "matches", "value": r"Strom\s*rechnung"},
                {"any": [{"field": "text", "op": "contains", "value": "Mahnung"}], "not": True},
            ]
        },
        "actions": [
            {"type": "set_space", "space_id": space["id"]},
            {"type": "add_tags", "tag_ids": [energy["id"]]},
        ],
    }
    rule = await system.post(owner, "/rules", body)
    assert (rule["version"], rule["scope"]) == (1, "space")

    bill = await system.upload(owner, "Stromrechnung der Stadtwerke, Nr. 4711")
    reminder = await system.upload(owner, "Mahnung zur Stromrechnung Nr. 4711")

    # The bill is filed into the rule's space and tagged, without a review.
    filed = await system.settled(owner, bill)
    assert filed["lane"] == "green", filed
    assert filed["processing"]["status"] == "completed"
    outcomes = {n["node"]: n["outcome"] for n in filed["processing"]["nodes"]}
    assert outcomes["apply_rules"] == "ok"
    assert outcomes["file"] == "ok"
    assert filed["space_id"] == space["id"]
    assert filed["tag_ids"] == [energy["id"]]
    entry = await system.rules_entry(owner, bill)
    assert entry["outcome"] == "ok", entry
    assert entry["model_version"] == "rules"
    assert entry["input"]["trigger"] == "ingest"
    assert {"id": rule["id"], "version": 1} in entry["input"]["rules"]
    (report,) = entry["output"]["rules"]
    assert (report["rule_id"], report["version"], report["scope"]) == (rule["id"], 1, "space")
    assert report["name"] == "Stromrechnungen"
    applied = {(effect["field"], effect["new"]) for effect in report["applied"]}
    assert applied == {("space", space["id"]), ("tags", energy["id"])}

    # The negated group keeps the reminder where it arrived.
    kept = await system.settled(owner, reminder)
    assert kept["lane"] == "green", kept
    assert kept["space_id"] != space["id"]
    assert kept["tag_ids"] == []
    entry = await system.rules_entry(owner, reminder)
    assert {"id": rule["id"], "version": 1} in entry["input"]["rules"]
    assert entry["output"].get("rules", []) == []

    # A changed rule acts with its new version, and the log says so.
    body["conditions"]["all"][0]["value"] = "Gasrechnung"
    changed = await system.client.put(
        f"{PREFIX}/rules/{rule['id']}", json=body, headers=auth(owner)
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2
    gas = await system.upload(owner, "Gasrechnung der Stadtwerke, Nr. 4712")
    filed = await system.settled(owner, gas)
    assert (filed["lane"], filed["space_id"]) == ("green", space["id"]), filed
    entry = await system.rules_entry(owner, gas)
    assert {"id": rule["id"], "version": 2} in entry["input"]["rules"]
    assert [(item["rule_id"], item["version"]) for item in entry["output"]["rules"]] == [
        (rule["id"], 2)
    ]
