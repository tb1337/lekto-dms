"""What a migration needs from the API: uploading in another user's name with the metadata of
the source system, spaces with their members and users created by an admin's token, the
original's hash."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from lekto.adapters.inbound.rest import PREFIX
from lekto.core.domain.documents import Document
from lekto.core.domain.errors import UnprocessableDocumentError
from lekto.core.domain.identity import TokenScope
from lekto.core.domain.pipeline import SIGNALS, Node, NodeResult
from lekto.core.domain.users import User
from lekto.core.services.imports import ImportedFieldsNode, ImportedJudgeNode, ImportedSignal
from lekto.core.services.pipeline import DeferredResult, NodeExecutor
from tests.api import auth, bearer
from tests.builders import SAMPLES, PlaceholderNode
from tests.unit.adapters.rest.support import DOCUMENTS, Api, post, sample_file


@pytest.fixture(autouse=True)
def imported_steps(api: Api) -> None:
    """The signals, the judge and the fields node as the container builds them, around nodes
    that do nothing (there is no language model)."""
    uow = api.container.unit_of_work
    pipeline = api.services.pipeline
    for signal in SIGNALS:
        pipeline.replace_executor(signal, ImportedSignal(uow, PlaceholderNode()))
    pipeline.replace_executor(Node.JUDGE, ImportedJudgeNode(uow, PlaceholderNode()))
    pipeline.replace_executor(Node.FIELDS, ImportedFieldsNode(uow, PlaceholderNode()))


async def upload(
    api: Api, headers: dict[str, str], *, name: str = "scan.pdf", **fields: str
) -> Any:
    return await api.client.post(DOCUMENTS, files=sample_file(name), data=fields, headers=headers)


async def master_data(api: Api, admin: User) -> dict[str, Any]:
    a = auth(admin)
    return {
        "contact": await post(api, "/contacts", {"name": "ACME Energy"}, a),
        "type": await post(api, "/document-types", {"name": "Invoice"}, a),
        "tag": await post(api, "/tags", {"name": "tax"}, a),
        "amount": await post(api, "/fields", {"name": "Amount", "data_type": "amount"}, a),
        "note": await post(api, "/fields", {"name": "Notes", "data_type": "text"}, a),
    }


def metadata(data: dict[str, Any], **changes: Any) -> str:
    body = {
        "title": "Electricity March",
        "contact_id": data["contact"]["id"],
        "document_type_id": data["type"]["id"],
        "tag_ids": [data["tag"]["id"]],
        "document_date": "2026-03-31",
        "fields": {
            data["amount"]["id"]: {"amount": "84.20", "currency": "EUR"},
            data["note"]["id"]: "paid by transfer",
        },
    } | changes
    return json.dumps(body)


# --- owner and metadata -----------------------------------------------------------------------


async def test_an_admin_uploads_for_another_owner_with_the_metadata(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    data = await master_data(api, admin)
    response = await upload(
        api, auth(admin), channel="migration", uploaded_by=str(owner.id), metadata=metadata(data)
    )
    assert response.status_code == 202, response.text
    await api.drain()

    document = (await api.client.get(response.json()["status_url"], headers=auth(owner))).json()
    assert document["uploaded_by"] == str(owner.id)
    assert document["channel"] == "migration"
    assert (document["lane"], document["processing"]["status"]) == ("green", "completed")
    assert document["title"] == "Electricity March"
    assert document["contact_id"] == data["contact"]["id"]
    assert document["document_type_id"] == data["type"]["id"]
    assert document["tag_ids"] == [data["tag"]["id"]]
    assert document["document_date"] == "2026-03-31"
    assert document["fields"] == {
        data["amount"]["id"]: {"amount": "84.20", "currency": "EUR"},
        data["note"]["id"]: "paid by transfer",
    }
    spaces = (await api.client.get(f"{PREFIX}/spaces", headers=auth(owner))).json()
    default = next(item for item in spaces if item["personal_of"] == str(owner.id))
    assert document["space_id"] == default["id"]

    log = (await api.client.get(f"{DOCUMENTS}/{document['id']}/log", headers=auth(owner))).json()
    receive = log[0]
    assert receive["output"]["uploaded_by"] == str(admin.id)
    assert receive["output"]["imported"]["title"] == "Electricity March"
    applied = {entry["node"]: entry for entry in log if entry["node"] in ("judge", "fields")}
    assert applied["judge"]["outcome"] == "ok"
    assert applied["judge"]["reason"] == "taken over from the source system"
    assert applied["judge"]["model_version"] == "imported"
    assert applied["fields"]["model_version"] == "imported"
    # It lies in the owner's personal space, not in the admin's reach.
    other = await api.client.get(f"{DOCUMENTS}?limit=50", headers=auth(admin))
    assert other.json()["items"] == []


async def test_the_metadata_say_when_the_document_came_in_at_the_source(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    data = await master_data(api, admin)

    async def migrated(created_at: str) -> Any:
        return await upload(
            api,
            auth(admin),
            channel="migration",
            uploaded_by=str(owner.id),
            metadata=metadata(data, created_at=created_at),
        )

    # Never ahead, always with a time zone; nothing is stored then.
    for wrong in ("2999-01-01T00:00:00Z", "2023-01-02T09:30:00"):
        response = await migrated(wrong)
        assert response.status_code == 422, (wrong, response.text)
    response = await migrated("2023-01-02T09:30:00+01:00")
    assert response.status_code == 202, response.text
    await api.drain()
    document = (await api.client.get(response.json()["status_url"], headers=auth(owner))).json()
    assert datetime.fromisoformat(document["created_at"]) == datetime(2023, 1, 2, 8, 30, tzinfo=UTC)
    log = (await api.client.get(f"{DOCUMENTS}/{document['id']}/log", headers=auth(owner))).json()
    assert log[0]["output"]["imported"]["created_at"] == "2023-01-02T08:30:00+00:00"


class FailsOnce:
    """An OCR that cannot process the first document it sees (red at once), then works."""

    def __init__(self, inner: NodeExecutor) -> None:
        self.inner = inner
        self.calls = 0

    async def run(self, document: Document) -> NodeResult | DeferredResult:
        self.calls += 1
        if self.calls == 1:
            raise UnprocessableDocumentError("the file is damaged or not a valid document")
        return await self.inner.run(document)


async def test_a_red_document_keeps_the_metadata_and_gets_them_when_retried(api: Api) -> None:
    """The metadata is applied by the classification nodes, so a document whose OCR fails is
    red without it; the receive entry keeps it, and a retry applies it (decision 8, M13)."""
    pipeline = api.services.pipeline
    pipeline.replace_executor(Node.OCR, FailsOnce(pipeline.executor(Node.OCR)))
    admin, owner = await api.admin(), await api.user()
    data = await master_data(api, admin)
    response = await upload(
        api, auth(admin), channel="migration", uploaded_by=str(owner.id), metadata=metadata(data)
    )
    assert response.status_code == 202, response.text
    await api.drain()
    url = response.json()["status_url"]
    document = (await api.client.get(url, headers=auth(owner))).json()
    failed = [n["node"] for n in document["processing"]["nodes"] if n["outcome"] == "failed"]
    assert (document["lane"], failed) == ("red", ["ocr"])
    assert (document["title"], document["contact_id"], document["fields"]) == (
        "scan",
        None,
        {},
    )
    log = (await api.client.get(f"{DOCUMENTS}/{document['id']}/log", headers=auth(owner))).json()
    assert log[0]["output"]["imported"]["contact_id"] == data["contact"]["id"]

    retried = await api.client.post(f"{DOCUMENTS}/{document['id']}/retry", headers=auth(owner))
    assert retried.status_code == 202, retried.text
    await api.drain()
    document = (await api.client.get(url, headers=auth(owner))).json()
    assert (document["lane"], document["processing"]["status"]) == ("green", "completed")
    assert document["title"] == "Electricity March"
    assert document["contact_id"] == data["contact"]["id"]
    assert document["document_type_id"] == data["type"]["id"]
    assert document["tag_ids"] == [data["tag"]["id"]]
    assert document["document_date"] == "2026-03-31"
    assert document["fields"][data["amount"]["id"]] == {"amount": "84.20", "currency": "EUR"}


async def test_the_original_hash_is_in_the_details(api: Api) -> None:
    owner = await api.user()
    response = await upload(api, auth(owner))
    document = (await api.client.get(response.json()["status_url"], headers=auth(owner))).json()
    assert document["sha256"] == hashlib.sha256((SAMPLES / "scan.pdf").read_bytes()).hexdigest()


async def test_an_admin_files_into_any_space_in_another_users_name(api: Api) -> None:
    admin, owner, other = await api.admin(), await api.user(), await api.user()
    theirs = await post(api, "/spaces", {"name": "Work"}, auth(other))
    response = await upload(
        api, auth(admin), uploaded_by=str(owner.id), space_id=theirs["id"], channel="migration"
    )
    assert response.status_code == 202, response.text
    url = response.json()["status_url"]
    document = (await api.client.get(url, headers=auth(other))).json()
    assert (document["space_id"], document["uploaded_by"]) == (theirs["id"], str(owner.id))
    assert (await api.client.get(url, headers=auth(owner))).status_code == 404  # no member
    # A user files only into spaces they edit.
    refused = await upload(api, auth(owner), name="photo.jpg", space_id=theirs["id"])
    assert refused.status_code == 404
    members = [{"user_id": str(owner.id), "role": "edit"}]
    mine = await post(api, "/spaces", {"name": "Mine", "members": members}, auth(admin))
    assert _roles(mine["members"]) == members
    response = await upload(
        api, auth(admin), uploaded_by=str(owner.id), space_id=mine["id"], name="photo.jpg"
    )
    assert response.status_code == 202, response.text
    document = (await api.client.get(response.json()["status_url"], headers=auth(owner))).json()
    assert document["space_id"] == mine["id"]


async def test_a_file_uploaded_for_anyone_exists_once(api: Api) -> None:
    admin, one, two = await api.admin(), await api.user(), await api.user()
    first = await upload(api, auth(admin), uploaded_by=str(one.id))
    assert first.status_code == 202
    for fields in ({"uploaded_by": str(one.id)}, {"uploaded_by": str(two.id)}, {}):
        again = await upload(api, auth(admin), **fields)
        assert again.status_code == 409
        assert again.json()["existing_document_id"] == first.json()["id"]  # admins read it


async def test_only_admins_name_the_uploader_or_give_metadata(api: Api) -> None:
    admin, user, owner = await api.admin(), await api.user(), await api.user()
    data = await master_data(api, admin)
    response = await upload(api, auth(user), uploaded_by=str(owner.id))
    assert response.status_code == 403
    response = await upload(api, auth(user), channel="migration", metadata=metadata(data))
    assert response.status_code == 403
    # Naming themselves is no change.
    assert (await upload(api, auth(user), uploaded_by=str(user.id))).status_code == 202


async def test_an_uploader_who_is_gone_or_inactive_is_not_found(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    unknown = await upload(api, auth(admin), uploaded_by=str(UUID(int=5)))
    assert unknown.status_code == 404
    await api.services.users.update(admin.id, owner.id, active=False)
    inactive = await upload(api, auth(admin), uploaded_by=str(owner.id))
    assert inactive.status_code == 404
    assert (await upload(api, auth(admin), uploaded_by="not-a-uuid")).status_code == 422


async def test_a_deactivated_admin_and_a_read_token_can_neither(api: Api) -> None:
    admin, owner, boss = await api.admin(), await api.user(), await api.admin()
    _, token = await api.services.auth.create_api_token(admin.id, "read", TokenScope.READ)
    response = await upload(api, bearer(token), uploaded_by=str(owner.id))
    assert response.status_code == 403
    await api.services.users.update(boss.id, admin.id, active=False)
    response = await upload(api, auth(admin), uploaded_by=str(owner.id))
    assert response.status_code == 401


async def test_metadata_needs_the_channel_and_must_fit_the_master_data(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    data = await master_data(api, admin)
    headers = auth(admin)
    for fields, text in [
        ({"metadata": metadata(data)}, "channel 'migration'"),
        ({"channel": "migration", "metadata": "{"}, "metadata"),
        (
            {"channel": "migration", "metadata": metadata(data, contact_id=str(UUID(int=9)))},
            "contact",
        ),
        (
            {"channel": "migration", "metadata": metadata(data, tag_ids=[str(UUID(int=9))])},
            "tag",
        ),
        (
            {"channel": "migration", "metadata": metadata(data, fields={str(UUID(int=9)): 1})},
            "field",
        ),
        (
            {
                "channel": "migration",
                "metadata": metadata(data, fields={data["amount"]["id"]: "12"}),
            },
            "field",
        ),
        ({"channel": "migration", "metadata": metadata(data, unknown=1)}, "unknown"),
        ({"channel": "migration", "metadata": metadata(data, title="  ")}, "title"),
        (
            {"channel": "migration", "metadata": metadata(data, review=[{"reason": ""}])},
            "reason",
        ),
        (
            {
                "channel": "migration",
                "metadata": metadata(data, review=[{"reason": "who?", "field": "owner"}]),
            },
            "review",
        ),
        (
            {
                "channel": "migration",
                "metadata": metadata(
                    data, review=[{"reason": "gone", "field": f"field:{UUID(int=9)}"}]
                ),
            },
            "review",
        ),
    ]:
        response = await upload(api, headers, uploaded_by=str(owner.id), **fields)
        assert response.status_code == 422, (fields, response.text)
        assert text in response.json()["detail"], response.json()
    # Nothing was stored.
    assert (await api.client.get(f"{DOCUMENTS}?all_users=true", headers=headers)).json()[
        "items"
    ] == []


async def test_metadata_may_be_long(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    data = await master_data(api, admin)
    notes = {data["note"]["id"]: "x" * 20_000}
    response = await upload(
        api,
        auth(admin),
        uploaded_by=str(owner.id),
        channel="migration",
        metadata=metadata(data, fields=notes),
    )
    assert response.status_code == 202, response.text
    too_long = {data["note"]["id"]: "x" * 60_000}
    response = await upload(
        api,
        auth(admin),
        name="photo.jpg",
        uploaded_by=str(owner.id),
        channel="migration",
        metadata=metadata(data, fields=too_long),
    )
    assert response.status_code == 400


async def test_a_migrated_document_without_metadata_is_processed_as_usual(api: Api) -> None:
    admin = await api.admin()
    response = await upload(api, auth(admin), channel="migration")
    assert response.status_code == 202
    await api.drain()
    document = (await api.client.get(response.json()["status_url"], headers=auth(admin))).json()
    assert (document["channel"], document["lane"]) == ("migration", "green")
    assert document["title"] == "scan"


async def test_reprocessing_applies_the_metadata_again(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    data = await master_data(api, admin)
    response = await upload(
        api, auth(admin), channel="migration", uploaded_by=str(owner.id), metadata=metadata(data)
    )
    await api.drain()
    url = response.json()["status_url"]
    await api.client.patch(url, json={"title": "Changed", "tag_ids": []}, headers=auth(owner))
    reprocess = await api.client.post(
        f"{url}/reprocess", json={"from_node": "judge"}, headers=auth(owner)
    )
    assert reprocess.status_code == 202, reprocess.text
    await api.drain()
    document = (await api.client.get(url, headers=auth(owner))).json()
    assert document["title"] == "Electricity March"
    assert document["tag_ids"] == [data["tag"]["id"]]
    assert document["lane"] == "green"


# --- spaces and users ------------------------------------------------------------------------


async def test_a_review_holds_the_document_until_a_person_decides(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    data = await master_data(api, admin)
    contact = "Paperless correspondent 'Sonstiges': resolve it in Lekto"
    review = [{"reason": contact, "field": "contact"}, {"reason": "owned by 'scanner'"}]
    response = await upload(
        api,
        auth(admin),
        channel="migration",
        uploaded_by=str(owner.id),
        metadata=metadata(data, contact_id=None, review=review),
    )
    assert response.status_code == 202, response.text
    url = response.json()["status_url"]
    await api.drain()

    document = (await api.client.get(url, headers=auth(owner))).json()
    assert (document["lane"], document["processing"]["status"]) == ("yellow", "review")
    assert document["confirmed_at"] is None
    assert document["document_type_id"] == data["type"]["id"]  # the values are applied
    (item,) = (await api.client.get(f"{PREFIX}/inbox", headers=auth(owner))).json()["items"]
    (open,) = item["open"]
    assert (open["node"], open["outcome"]) == ("judge", "uncertain")
    assert open["reason"] == f"{contact}; owned by 'scanner'"
    assert [(field["field"], field["reason"]) for field in open["fields"]] == [("contact", contact)]

    undecided = await api.client.post(f"{url}/confirm", json={}, headers=auth(owner))
    assert undecided.status_code == 422
    assert undecided.json()["open_fields"] == ["contact"]
    confirmed = await api.client.post(
        f"{url}/confirm",
        json={"changes": {"contact_id": data["contact"]["id"]}},
        headers=auth(owner),
    )
    assert confirmed.status_code == 202, confirmed.text
    await api.drain()
    document = (await api.client.get(url, headers=auth(owner))).json()
    assert (document["lane"], document["contact_id"]) == ("green", data["contact"]["id"])
    assert document["confirmed_at"] is not None


async def test_what_the_source_system_lacks_a_person_decides(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    data = await master_data(api, admin)
    response = await upload(
        api,
        auth(admin),
        channel="migration",
        uploaded_by=str(owner.id),
        metadata=metadata(data, contact_id=None, document_type_id=None),
    )
    assert response.status_code == 202, response.text
    url = response.json()["status_url"]
    await api.drain()

    document = (await api.client.get(url, headers=auth(owner))).json()
    assert (document["lane"], document["processing"]["status"]) == ("yellow", "review")
    assert document["title"] == "Electricity March"  # the values there are applied
    (item,) = (await api.client.get(f"{PREFIX}/inbox", headers=auth(owner))).json()["items"]
    (open,) = item["open"]
    assert (open["node"], open["outcome"]) == ("judge", "uncertain")
    assert open["reason"] == (
        "no contact in the source system; no document type in the source system"
    )
    assert [field["field"] for field in open["fields"]] == ["contact", "document_type"]

    changes = {"contact_id": data["contact"]["id"], "document_type_id": data["type"]["id"]}
    confirmed = await api.client.post(
        f"{url}/confirm", json={"changes": changes}, headers=auth(owner)
    )
    assert confirmed.status_code == 202, confirmed.text
    await api.drain()
    assert (await api.client.get(url, headers=auth(owner))).json()["lane"] == "green"

    # Processed again, the metadata lack them still, but the document has them now.
    reprocess = await api.client.post(
        f"{url}/reprocess", json={"from_node": "judge"}, headers=auth(owner)
    )
    assert reprocess.status_code == 202, reprocess.text
    await api.drain()
    document = (await api.client.get(url, headers=auth(owner))).json()
    assert (document["lane"], document["contact_id"]) == ("green", data["contact"]["id"])


async def test_a_review_of_a_field_with_a_value_keeps_it(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    data = await master_data(api, admin)
    amount = f"field:{data['amount']['id']}"
    response = await upload(
        api,
        auth(admin),
        channel="migration",
        uploaded_by=str(owner.id),
        metadata=metadata(data, review=[{"reason": "currency guessed", "field": amount}]),
    )
    url = response.json()["status_url"]
    await api.drain()

    (item,) = (await api.client.get(f"{PREFIX}/inbox", headers=auth(owner))).json()["items"]
    (open,) = item["open"]
    assert (open["node"], open["reason"]) == ("fields", "currency guessed")
    assert [field["field"] for field in open["fields"]] == [amount]
    confirmed = await api.client.post(f"{url}/confirm", json={}, headers=auth(owner))
    assert confirmed.status_code == 202, confirmed.text
    await api.drain()
    document = (await api.client.get(url, headers=auth(owner))).json()
    assert document["lane"] == "green"
    assert document["fields"][data["amount"]["id"]] == {"amount": "84.20", "currency": "EUR"}


async def test_an_admin_aligns_a_migrated_document_without_confirming_it(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    data = await master_data(api, admin)
    other = await post(api, "/contacts", {"name": "Nord Strom"}, auth(admin))
    household = await post(
        api,
        "/spaces",
        {"name": "Household", "members": [{"user_id": str(owner.id), "role": "edit"}]},
        auth(admin),
    )
    await post(
        api,
        "/rules",
        {
            "name": "Nord Strom to the household",
            "triggers": ["change"],
            "conditions": {"all": [{"field": "contact", "op": "is", "value": other["id"]}]},
            "actions": [{"type": "set_space", "space_id": household["id"]}],
        },
        auth(owner),
    )
    response = await upload(
        api, auth(admin), channel="migration", uploaded_by=str(owner.id), metadata=metadata(data)
    )
    url = response.json()["status_url"]
    await api.drain()
    taken_over = (await api.client.get(url, headers=auth(owner))).json()["confirmed_at"]
    assert taken_over is not None

    body = {"contact_id": other["id"]}
    preview = await api.client.post(f"{url}/dry-run?confirm=false", json=body, headers=auth(admin))
    assert preview.status_code == 200, preview.text
    assert [effect["field"] for effect in preview.json()["rules"][0]["applied"]] == ["space"]
    changed = await api.client.patch(f"{url}?confirm=false", json=body, headers=auth(admin))
    assert changed.status_code == 200, changed.text
    assert changed.json()["space_id"] == household["id"]  # the rules ran
    document = (await api.client.get(url, headers=auth(owner))).json()
    assert (document["contact_id"], document["confirmed_at"]) == (other["id"], taken_over)

    # One that waits for a review stays unconfirmed; the person's confirmation keeps the value.
    review = [{"reason": "resolve the contact", "field": "contact"}]
    response = await upload(
        api,
        auth(admin),
        channel="migration",
        uploaded_by=str(owner.id),
        name="photo.jpg",
        metadata=metadata(data, contact_id=None, review=review),
    )
    url = response.json()["status_url"]
    await api.drain()
    changed = await api.client.patch(f"{url}?confirm=false", json=body, headers=auth(admin))
    assert changed.status_code == 200, changed.text
    document = (await api.client.get(url, headers=auth(owner))).json()
    assert (document["lane"], document["confirmed_at"]) == ("yellow", None)
    confirmed = await api.client.post(f"{url}/confirm", json={}, headers=auth(owner))
    assert confirmed.status_code == 202, confirmed.text
    await api.drain()
    document = (await api.client.get(url, headers=auth(owner))).json()
    assert (document["lane"], document["contact_id"]) == ("green", other["id"])


async def test_only_an_admin_aligns_and_only_a_migrated_document(api: Api) -> None:
    admin, owner = await api.admin(), await api.user()
    data = await master_data(api, admin)
    migrated = await upload(
        api, auth(admin), channel="migration", uploaded_by=str(owner.id), metadata=metadata(data)
    )
    own = await upload(api, auth(owner), name="photo.jpg")
    await api.drain()
    body = {"title": "Aligned"}
    for path in ("", "/dry-run"):
        method = api.client.patch if path == "" else api.client.post
        url = migrated.json()["status_url"] + path + "?confirm=false"
        response = await method(url, json=body, headers=auth(owner))
        assert response.status_code == 403, (path, response.text)
        url = own.json()["status_url"] + path + "?confirm=false"
        response = await method(url, json=body, headers=auth(admin))
        assert response.status_code == 422, (path, response.text)
        assert "migration" in response.json()["detail"]
    document = (await api.client.get(own.json()["status_url"], headers=auth(owner))).json()
    assert document["title"] != "Aligned"


async def test_spaces_with_members(api: Api) -> None:
    admin, owner, other = await api.admin(), await api.user(), await api.user()
    members = [{"user_id": str(owner.id), "role": "edit"}]
    created = await api.client.post(
        f"{PREFIX}/spaces", json={"name": "Shared", "members": members}, headers=auth(admin)
    )
    assert created.status_code == 201, created.text
    assert _roles(created.json()["members"]) == members  # the admin alone gives the members
    assert created.json()["personal_of"] is None
    # Names of spaces are unique.
    again = await api.client.post(f"{PREFIX}/spaces", json={"name": "shared"}, headers=auth(admin))
    assert again.status_code == 409
    # Anyone else always edits what they create.
    readers = [{"user_id": str(owner.id), "role": "read"}]
    theirs = await api.client.post(
        f"{PREFIX}/spaces", json={"name": "X", "members": readers}, headers=auth(other)
    )
    assert theirs.status_code == 201
    assert {(m["user_id"], m["role"]) for m in theirs.json()["members"]} == {
        (str(other.id), "edit"),
        (str(owner.id), "read"),
    }
    nobody_edits = await api.client.post(
        f"{PREFIX}/spaces", json={"name": "Z", "members": readers}, headers=auth(admin)
    )
    assert nobody_edits.status_code == 422
    unknown = [{"user_id": str(UUID(int=4)), "role": "read"}]
    missing = await api.client.post(
        f"{PREFIX}/spaces", json={"name": "Y", "members": unknown}, headers=auth(admin)
    )
    assert missing.status_code == 404
    added = await api.client.put(
        f"{PREFIX}/spaces/{created.json()['id']}/members/{other.id}",
        json={"role": "read"},
        headers=auth(admin),
    )
    assert added.status_code == 200
    removed = await api.client.delete(
        f"{PREFIX}/spaces/{created.json()['id']}/members/{other.id}", headers=auth(owner)
    )
    assert removed.status_code == 200
    assert _roles(removed.json()["members"]) == members


def _roles(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The members by id and role (without their names)."""
    return [{"user_id": member["user_id"], "role": member["role"]} for member in members]


async def test_an_admin_token_creates_users_without_password(api: Api) -> None:
    admin, user = await api.admin(), await api.user()
    created = await api.client.post(
        f"{PREFIX}/users", json={"username": "newcomer"}, headers=auth(admin)
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "user"
    for body in (
        {"username": "pw", "password": "a-long-enough-password"},
        {"username": "boss", "role": "admin"},
    ):
        refused = await api.client.post(f"{PREFIX}/users", json=body, headers=auth(admin))
        assert refused.status_code == 403, body
    assert (
        await api.client.post(f"{PREFIX}/users", json={"username": "x"}, headers=auth(user))
    ).status_code == 403
    _, read = await api.services.auth.create_api_token(admin.id, "r", TokenScope.READ)
    assert (
        await api.client.post(f"{PREFIX}/users", json={"username": "y"}, headers=bearer(read))
    ).status_code == 403
    # With a session, a password and the role admin work as before.
    async with api.sign_in(admin) as session:
        response = await session.client.post(
            f"{PREFIX}/users",
            json={"username": "root", "role": "admin", "password": "a-long-enough-password"},
            headers=session.headers,
        )
        assert response.status_code == 201, response.text


async def test_rules_run_and_trust_the_imported_values(api: Api) -> None:
    admin, owner, reader = await api.admin(), await api.user(), await api.user()
    data = await master_data(api, admin)
    shared = await post(api, "/spaces", {"name": "Shared"}, auth(owner))
    await api.client.put(
        f"{PREFIX}/spaces/{shared['id']}/shares/{reader.id}",
        json={"level": "read"},
        headers=auth(owner),
    )
    await post(
        api,
        "/rules",
        {
            "name": "Energy",
            "conditions": {
                "all": [
                    {"field": "channel", "op": "is", "value": "migration"},
                    {"field": "contact", "op": "is", "value": data["contact"]["id"]},
                ]
            },
            "actions": [{"type": "set_space", "space_id": shared["id"]}],
        },
        auth(owner),
    )
    response = await upload(
        api, auth(admin), channel="migration", uploaded_by=str(owner.id), metadata=metadata(data)
    )
    await api.drain()
    document = (await api.client.get(response.json()["status_url"], headers=auth(owner))).json()
    # Taken over from the source system, not guessed by a model: the rule files it for sharing.
    assert (document["lane"], document["space_id"]) == ("green", shared["id"])
