"""`/webhooks`: managing webhooks over the API."""

from datetime import datetime
from uuid import UUID

from lekto.adapters.inbound.rest import PREFIX
from lekto.adapters.outbound.memory import FakeWebhookSender
from lekto.core.domain.identity import TokenScope
from lekto.core.domain.ids import DocumentId, EventId, WebhookId, new_id
from lekto.core.domain.users import Role
from lekto.core.domain.webhooks import DeliveryOutcome, WebhookDelivery
from tests.api import auth, bearer
from tests.builders import RETENTION
from tests.unit.adapters.rest.support import Api, post

BODY = {
    "name": "n8n",
    "url": "http://n8n.lan:5678/webhook/lekto",
    "event_types": ["document.filed", "document.lane_changed"],
}


async def test_a_webhook_is_created_changed_switched_off_and_deleted(api: Api) -> None:
    user = await api.user()
    created = await post(api, "/webhooks", BODY, auth(user))
    assert created["secret"].startswith("whsec_")
    assert created["max_open_tasks"] == 4
    assert created["active"] is True and created["event_types"] == [
        "document.filed",
        "document.lane_changed",
    ]
    url = f"{PREFIX}/webhooks/{created['id']}"

    shown = (await api.client.get(url, headers=auth(user))).json()
    assert "secret" not in shown and shown["id"] == created["id"]
    listed = (await api.client.get(f"{PREFIX}/webhooks", headers=auth(user))).json()
    assert [item["id"] for item in listed] == [created["id"]]
    assert all("secret" not in item for item in listed)

    changed = await api.client.patch(
        url,
        json={"name": "HA", "event_types": ["*"], "active": False, "max_open_tasks": 8},
        headers=auth(user),
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["name"], changed.json()["event_types"], changed.json()["active"]) == (
        "HA",
        ["*"],
        False,
    )
    assert changed.json()["max_open_tasks"] == 8
    too_many = await api.client.patch(url, json={"max_open_tasks": 65}, headers=auth(user))
    assert too_many.status_code == 422
    assert (await api.client.delete(url, headers=auth(user))).status_code == 204
    assert (await api.client.get(url, headers=auth(user))).status_code == 404


async def test_the_secret_is_renewed_once_with_the_old_one_still_valid(api: Api) -> None:
    user = await api.user()
    created = await post(api, "/webhooks", BODY, auth(user))
    response = await api.client.post(
        f"{PREFIX}/webhooks/{created['id']}/secret", headers=auth(user)
    )
    assert response.status_code == 200, response.text
    renewed = response.json()
    assert renewed["secret"] != created["secret"]
    assert renewed["previous_secret_valid_until"] is not None
    shown = (await api.client.get(f"{PREFIX}/webhooks/{created['id']}", headers=auth(user))).json()
    assert "secret" not in shown and shown["previous_secret_valid_until"] is not None


async def test_a_webhook_with_own_headers_and_without_a_secret(api: Api) -> None:
    user = await api.user()
    body = {
        **BODY,
        "signed": False,
        "headers": [
            {"name": "Authorization", "value": "Bearer t0ken"},
            {"name": "X-Tenant", "value": "home"},
        ],
    }
    created = await post(api, "/webhooks", body, auth(user))
    assert created["secret"] is None and created["signed"] is False
    assert created["headers"] == ["Authorization", "X-Tenant"]
    assert "t0ken" not in str(created)
    url = f"{PREFIX}/webhooks/{created['id']}"

    # A value left out is kept; only the names are ever shown.
    changed = await api.client.patch(
        url,
        json={"headers": [{"name": "Authorization"}, {"name": "X-Other", "value": "1"}]},
        headers=auth(user),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["headers"] == ["Authorization", "X-Other"]
    missing = await api.client.patch(url, json={"headers": [{"name": "X-New"}]}, headers=auth(user))
    assert missing.status_code == 422, missing.text

    signed = await api.client.post(f"{url}/secret", headers=auth(user))
    assert signed.status_code == 200 and signed.json()["secret"].startswith("whsec_")
    assert signed.json()["signed"] is True
    unsigned = await api.client.delete(f"{url}/secret", headers=auth(user))
    assert unsigned.status_code == 200, unsigned.text
    assert unsigned.json()["signed"] is False
    assert unsigned.json()["previous_secret_valid_until"] is None


async def test_reserved_or_repeated_headers_are_a_422(api: Api) -> None:
    user = await api.user()
    for headers in (
        [{"name": "Content-Type", "value": "text/plain"}],
        [{"name": "webhook-signature", "value": "v1,x"}],
        [{"name": "X", "value": "a"}, {"name": "X", "value": "b"}],
        [{"name": "X", "value": "a"}, {"name": "x", "value": "b"}],
        [{"name": "X Y", "value": "a"}],
        [{"name": "X", "value": "line\nbreak"}],
    ):
        response = await api.client.post(
            f"{PREFIX}/webhooks", json={**BODY, "headers": headers}, headers=auth(user)
        )
        assert response.status_code == 422, (headers, response.text)


async def test_a_webhook_with_a_template_body_and_its_preview(api: Api) -> None:
    user = await api.user()
    template = '{"message": {{ title | json }}, "event": {{ event.type | json }}}'
    created = await post(
        api, "/webhooks", {**BODY, "body": "template", "body_template": template}, auth(user)
    )
    assert (created["body"], created["body_template"]) == ("template", template)
    bad = await api.client.post(
        f"{PREFIX}/webhooks",
        json={**BODY, "body": "template", "body_template": '{"x": {{ nonsense }}}'},
        headers=auth(user),
    )
    assert bad.status_code == 422, bad.text
    changed = await api.client.patch(
        f"{PREFIX}/webhooks/{created['id']}", json={"body": "full"}, headers=auth(user)
    )
    assert (changed.json()["body"], changed.json()["body_template"]) == ("full", None)

    preview = await api.client.post(
        f"{PREFIX}/templates/preview",
        json={"template": template, "purpose": "webhook"},
        headers=auth(user),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["error"] is None
    assert set(preview.json()["used"]) == {"title", "event.type"}
    rule = await api.client.post(
        f"{PREFIX}/templates/preview", json={"template": "{{ event.type }}"}, headers=auth(user)
    )
    assert rule.json()["error"] == "unknown value event.type"


async def test_invalid_input_is_a_422(api: Api) -> None:
    user = await api.user()
    for body in (
        {**BODY, "url": "ftp://x"},
        {**BODY, "url": "https://user:pw@example.org"},
        {**BODY, "event_types": ["document.nonsense"]},
        {**BODY, "name": ""},
        {**BODY, "extra": 1},
    ):
        response = await api.client.post(f"{PREFIX}/webhooks", json=body, headers=auth(user))
        assert response.status_code == 422, body
    url = f"{PREFIX}/webhooks"
    created = await post(api, "/webhooks", BODY, auth(user))
    response = await api.client.patch(
        f"{url}/{created['id']}", json={"url": "nonsense"}, headers=auth(user)
    )
    assert response.status_code == 422


async def test_users_see_only_their_webhooks_and_admins_all(api: Api) -> None:
    owner, other, admin = await api.user(), await api.user(), await api.admin()
    mine = await post(api, "/webhooks", BODY, auth(owner))
    url = f"{PREFIX}/webhooks/{mine['id']}"
    assert (await api.client.get(url, headers=auth(other))).status_code == 404
    assert (await api.client.get(f"{url}/deliveries", headers=auth(other))).status_code == 404
    assert (await api.client.patch(url, json={"name": "x"}, headers=auth(other))).status_code == 404
    assert (await api.client.get(f"{PREFIX}/webhooks", headers=auth(other))).json() == []

    assert (await api.client.get(url, headers=auth(admin))).status_code == 200
    assert (await api.client.get(f"{url}/deliveries", headers=auth(admin))).json() == []
    everything = await api.client.get(f"{PREFIX}/webhooks", headers=auth(admin))
    assert [item["id"] for item in everything.json()] == [mine["id"]]
    narrowed = await api.client.get(
        f"{PREFIX}/webhooks", params={"owner": str(new_id())}, headers=auth(admin)
    )
    assert narrowed.json() == []
    # Admins change, renew and delete as well.
    changed = await api.client.patch(url, json={"name": "x"}, headers=auth(admin))
    assert (changed.status_code, changed.json()["name"]) == (200, "x")
    renewed = await api.client.post(f"{url}/secret", headers=auth(admin))
    assert renewed.status_code == 200 and renewed.json()["secret"].startswith("whsec_")
    assert (await api.client.delete(url, headers=auth(admin))).status_code == 204
    assert (await api.client.get(url, headers=auth(owner))).status_code == 404


async def test_a_read_token_reads_but_changes_nothing(api: Api) -> None:
    user = await api.user()
    created = await post(api, "/webhooks", BODY, auth(user))
    _, token = await api.services.auth.create_api_token(user.id, "reader", TokenScope.READ)
    headers = bearer(token)
    url = f"{PREFIX}/webhooks"
    assert (await api.client.get(url, headers=headers)).status_code == 200
    assert (await api.client.get(f"{url}/{created['id']}", headers=headers)).status_code == 200
    assert (
        await api.client.get(f"{url}/{created['id']}/deliveries", headers=headers)
    ).status_code == 200
    assert (await api.client.post(url, json=BODY, headers=headers)).status_code == 403
    assert (
        await api.client.patch(f"{url}/{created['id']}", json={}, headers=headers)
    ).status_code == 403
    assert (await api.client.delete(f"{url}/{created['id']}", headers=headers)).status_code == 403
    assert (
        await api.client.post(f"{url}/{created['id']}/secret", headers=headers)
    ).status_code == 403


async def test_webhooks_need_authentication_and_the_limit_is_a_409(api: Api) -> None:
    assert (await api.client.get(f"{PREFIX}/webhooks")).status_code == 401
    user = await api.user()
    for _ in range(20):
        await post(api, "/webhooks", BODY, auth(user))
    response = await api.client.post(f"{PREFIX}/webhooks", json=BODY, headers=auth(user))
    assert response.status_code == 409


async def test_the_deliveries_are_listed_newest_first_in_pages(api: Api) -> None:
    user = await api.user()
    created = await post(api, "/webhooks", BODY, auth(user))
    ids = []
    async with api.container.unit_of_work() as uow:
        for attempt in range(1, 4):
            delivery = WebhookDelivery.record(
                webhook_id=WebhookId(UUID(created["id"])),
                event_id=EventId(new_id()),
                event_type="document.filed",
                document_id=DocumentId(new_id()),
                attempt=attempt,
                started_at=api.clock.now(),
                duration_ms=7,
                outcome=DeliveryOutcome.DELIVERED,
                status_code=204,
            )
            ids.append(str(delivery.id))
            await uow.webhooks.add_delivery(delivery)
        await uow.commit()
    url = f"{PREFIX}/webhooks/{created['id']}/deliveries"
    first = (await api.client.get(url, params={"limit": 2}, headers=auth(user))).json()
    assert [item["id"] for item in first] == sorted(ids, reverse=True)[:2]
    assert first[0]["outcome"] == "delivered" and first[0]["status_code"] == 204
    rest = await api.client.get(url, params={"before": first[-1]["id"]}, headers=auth(user))
    assert [item["id"] for item in rest.json()] == sorted(ids, reverse=True)[2:]


async def test_the_deliveries_filter_by_outcome_and_event_and_are_counted(api: Api) -> None:
    user, other = await api.user(), await api.user()
    created = await post(api, "/webhooks", BODY, auth(user))
    entries = [
        ("document.filed", DeliveryOutcome.DELIVERED),
        ("document.filed", DeliveryOutcome.GAVE_UP),
        ("webhook.test", DeliveryOutcome.DELIVERED),
        ("rule.send", DeliveryOutcome.RETRYING),
    ]
    async with api.container.unit_of_work() as uow:
        for event_type, outcome in entries:
            await uow.webhooks.add_delivery(
                WebhookDelivery.record(
                    webhook_id=WebhookId(UUID(created["id"])),
                    event_id=EventId(new_id()),
                    event_type=event_type,
                    document_id=None,
                    attempt=1,
                    started_at=api.clock.now(),
                    duration_ms=7,
                    outcome=outcome,
                )
            )
        await uow.commit()
    url = f"{PREFIX}/webhooks/{created['id']}/deliveries"

    async def listed(params: dict[str, str | int | list[str]]) -> list[tuple[str, str]]:
        response = await api.client.get(url, params=params, headers=auth(user))
        assert response.status_code == 200, response.text
        return sorted((item["event_type"], item["outcome"]) for item in response.json())

    problems = await listed({"outcome": ["gave_up", "retrying"]})
    assert problems == [("document.filed", "gave_up"), ("rule.send", "retrying")]
    assert await listed({"event_type": "webhook.test"}) == [("webhook.test", "delivered")]
    assert len(await listed({"offset": 3})) == 1
    first = (await api.client.get(url, headers=auth(user))).json()[0]
    assert (first["document"], first["document_hidden"]) == (None, False)

    summary = await api.client.get(f"{url}/summary", headers=auth(user))
    assert summary.status_code == 200, summary.text
    counted = summary.json()
    kept_since = datetime.fromisoformat(counted.pop("kept_since"))
    assert counted == {
        "delivered": 2,
        "retrying": 1,
        "gave_up": 1,
        "dropped": 0,
        "event_types": ["document.filed", "rule.send", "webhook.test"],
    }
    assert kept_since == api.clock.now() - RETENTION
    filed = await api.client.get(
        f"{url}/summary", params={"event_type": "document.filed"}, headers=auth(user)
    )
    assert (filed.json()["delivered"], filed.json()["gave_up"]) == (1, 1)
    assert (await api.client.get(f"{url}/summary", headers=auth(other))).status_code == 404


async def test_a_test_request_is_sent_and_logged(api: Api) -> None:
    user, other, admin = await api.user(), await api.user(), await api.admin()
    created = await post(api, "/webhooks", BODY, auth(user))
    url = f"{PREFIX}/webhooks/{created['id']}/test"
    response = await api.client.post(url, headers=auth(user))
    assert response.status_code == 200, response.text
    row = response.json()
    assert (row["outcome"], row["event_type"], row["document_id"]) == (
        "delivered",
        "webhook.test",
        None,
    )
    sender = api.container.webhook_sender
    assert isinstance(sender, FakeWebhookSender) and len(sender.requests) == 1
    listed = await api.client.get(
        f"{PREFIX}/webhooks/{created['id']}/deliveries", headers=auth(user)
    )
    assert [item["id"] for item in listed.json()] == [row["id"]]

    assert (await api.client.post(url, headers=auth(other))).status_code == 404
    _, token = await api.services.auth.create_api_token(user.id, "reader", TokenScope.READ)
    assert (await api.client.post(url, headers=bearer(token))).status_code == 403
    assert (await api.client.post(url)).status_code == 401
    assert len(sender.requests) == 1
    assert (await api.client.post(url, headers=auth(admin))).status_code == 200
    assert len(sender.requests) == 2


async def test_test_requests_answer_429_beyond_the_limit(api: Api) -> None:
    user = await api.user()
    created = await post(api, "/webhooks", BODY, auth(user))
    url = f"{PREFIX}/webhooks/{created['id']}/test"
    for _ in range(10):
        assert (await api.client.post(url, headers=auth(user))).status_code == 200
    refused = await api.client.post(url, headers=auth(user))
    assert refused.status_code == 429, refused.text
    assert refused.headers["Retry-After"] == "60"
    sender = api.container.webhook_sender
    assert isinstance(sender, FakeWebhookSender) and len(sender.requests) == 10


async def test_an_admins_webhook_serves_as_a_model_call(api: Api) -> None:
    admin, user = await api.user(role=Role.ADMIN), await api.user()
    body = BODY | {"event_types": [], "model_call": {"kind": "propose"}}
    created = await post(api, "/webhooks", body, auth(admin))
    assert created["model_call"] == {"kind": "propose", "timeout_seconds": 300}
    url = f"{PREFIX}/webhooks/{created['id']}"
    # Left out it stays, given it changes, null ends it.
    kept = await api.client.patch(url, json={"name": "agent"}, headers=auth(admin))
    assert kept.json()["model_call"] == {"kind": "propose", "timeout_seconds": 300}
    changed = await api.client.patch(
        url, json={"model_call": {"kind": "extract", "timeout_seconds": 900}}, headers=auth(admin)
    )
    assert changed.json()["model_call"] == {"kind": "extract", "timeout_seconds": 900}
    # A second one of the same kind conflicts; a user may not; the time is limited.
    second = await api.client.post(
        f"{PREFIX}/webhooks",
        json=BODY | {"model_call": {"kind": "extract"}},
        headers=auth(admin),
    )
    assert second.status_code == 409
    assert second.json()["reason"]["code"] == "model_call_taken"
    refused = await api.client.post(f"{PREFIX}/webhooks", json=body, headers=auth(user))
    assert refused.status_code == 403
    assert refused.json()["reason"]["code"] == "model_call_admins"
    short = await api.client.patch(
        url, json={"model_call": {"kind": "extract", "timeout_seconds": 5}}, headers=auth(admin)
    )
    assert short.status_code == 422
    ended = await api.client.patch(url, json={"model_call": None}, headers=auth(admin))
    assert ended.json()["model_call"] is None
