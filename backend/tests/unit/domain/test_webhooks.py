import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.events import DOCUMENT_EVENT_TYPES
from lekto.core.domain.ids import DocumentId, EventId, UserId, new_id
from lekto.core.domain.webhooks import (
    ALL_EVENTS,
    DISABLED_FAILING,
    ID_HEADER,
    MAX_BODY_TEMPLATE,
    MAX_HEADER_VALUE,
    MAX_HEADERS,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    BodyFormat,
    DeliveryOutcome,
    Webhook,
    WebhookDelivery,
    event_body,
    headers_from_bytes,
    headers_to_bytes,
    new_secret,
    rendered_body,
    sign,
    signed_headers,
    validate_event_types,
    validate_header_names,
    validate_header_value,
    validate_url,
)
from tests.builders import NOW


def hook(**fields: object) -> Webhook:
    values: dict[str, object] = {
        "owner_id": UserId(new_id()),
        "name": "n8n",
        "url": "http://n8n.lan:5678/webhook/lekto",
        "event_types": [ALL_EVENTS],
        "encrypted_secret": b"secret-1",
        "now": NOW,
    }
    return Webhook.create(**{**values, **fields})  # type: ignore[arg-type]


# --- URL and event types ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/hook",
        "http://n8n.lan:5678/webhook/lekto?token=1",
        "http://192.168.1.20/hook",
        "http://[fd00::1]:8123/api/webhook/x",
        "  https://example.org/a  ",
    ],
)
def test_urls_with_http_or_https_and_a_host_are_valid_also_in_the_own_network(url: str) -> None:
    assert validate_url(url) == url.strip()


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://example.org/hook",
        "example.org/hook",
        "https:///hook",
        "https://user:pass@example.org/hook",
        "https://user@example.org/hook",
        "https://example.org/hook#frag",
        "https://example.org/a b",
        "https://example.org:99999/hook",
        "https://example.org/" + "a" * 2000,
        "javascript:alert(1)",
    ],
)
def test_other_urls_are_refused(url: str) -> None:
    with pytest.raises(ValidationError):
        validate_url(url)


def test_event_types_must_be_known_and_may_be_none() -> None:
    assert validate_event_types(["document.filed", "document.deleted"]) == {
        "document.filed",
        "document.deleted",
    }
    assert validate_event_types(DOCUMENT_EVENT_TYPES) == frozenset(DOCUMENT_EVENT_TYPES)
    # None: a webhook only rules use.
    assert validate_event_types([]) == frozenset()
    with pytest.raises(ValidationError, match=r"classifier\.trained"):
        validate_event_types(["classifier.trained"])
    with pytest.raises(ValidationError, match=r"document\.fild"):
        validate_event_types(["document.fild"])


def test_all_events_swallows_the_others() -> None:
    assert validate_event_types([ALL_EVENTS, "document.filed"]) == {ALL_EVENTS}
    assert hook(event_types=[ALL_EVENTS]).wants("document.somethingnew")
    assert not hook(event_types=["document.filed"]).wants("document.updated")


# --- signature ----------------------------------------------------------------------------------


def test_the_signature_matches_the_standard_webhooks_example() -> None:
    signature = sign(
        "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw",
        "msg_p5jXN8AQM9LWM0D4loKWxJek",
        1614265330,
        b'{"test": 2432232314}',
    )
    assert signature == "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="


def test_a_request_carries_one_signature_per_secret_in_use() -> None:
    first, second = new_secret(), new_secret()
    body = b'{"id":"e"}'
    headers = signed_headers([first, second], "e", 1700000000, body)
    assert headers["webhook-id"] == "e"
    assert headers["webhook-timestamp"] == "1700000000"
    assert headers[SIGNATURE_HEADER].split(" ") == [
        sign(first, "e", 1700000000, body),
        sign(second, "e", 1700000000, body),
    ]


def test_new_secrets_are_random_and_have_the_prefix() -> None:
    a, b = new_secret(), new_secret()
    assert a != b
    assert a.startswith("whsec_") and len(a) > 40


def test_the_body_is_thin_compact_json() -> None:
    event, document = EventId(UUID(int=1)), DocumentId(UUID(int=2))
    body = event_body(
        event_id=event,
        type="document.filed",
        occurred_at=datetime(2026, 10, 8, 6, 36, 46, 123456, tzinfo=UTC),
        document_id=document,
    )
    assert body == (
        b'{"id":"00000000-0000-0000-0000-000000000001","type":"document.filed",'
        b'"occurred_at":"2026-10-08T06:36:46Z",'
        b'"document_id":"00000000-0000-0000-0000-000000000002"}'
    )
    test = event_body(event_id=event, type="webhook.test", occurred_at=NOW, document_id=None)
    assert test.endswith(b'"document_id":null}')


# --- the aggregate ------------------------------------------------------------------------------


def test_a_webhook_validates_its_fields() -> None:
    with pytest.raises(ValidationError):
        hook(name="  ")
    with pytest.raises(ValidationError):
        hook(name="x" * 101)
    with pytest.raises(ValidationError):
        hook(url="ftp://x")
    assert not hook(event_types=[]).wants("document.filed")


def test_change_updates_what_is_given_and_switching_on_clears_the_failures() -> None:
    webhook = hook()
    webhook.failed_streak = 3
    webhook.active, webhook.disabled_reason = False, DISABLED_FAILING
    later = NOW + timedelta(hours=1)
    webhook.change(now=later, name="HA", event_types=["document.filed"])
    assert (webhook.name, webhook.event_types, webhook.updated_at) == (
        "HA",
        frozenset({"document.filed"}),
        later,
    )
    assert not webhook.active and webhook.failed_streak == 3
    webhook.change(now=later, active=True)
    assert webhook.active and webhook.failed_streak == 0 and webhook.disabled_reason is None


def test_the_old_secret_signs_next_to_the_new_one_during_the_grace_period() -> None:
    webhook = hook()
    webhook.renew_secret(b"secret-2", now=NOW, grace=timedelta(hours=24))
    assert webhook.encrypted_secrets(NOW + timedelta(hours=23)) == [b"secret-2", b"secret-1"]
    assert webhook.encrypted_secrets(NOW + timedelta(hours=24)) == [b"secret-2"]
    webhook.renew_secret(b"secret-3", now=NOW, grace=timedelta(hours=24))
    assert webhook.encrypted_secrets(NOW) == [b"secret-3", b"secret-2"]


def test_repeated_failures_switch_a_webhook_off_and_a_success_resets_the_count() -> None:
    webhook = hook()
    assert not webhook.gave_up(disable_after=3, now=NOW)
    assert not webhook.gave_up(disable_after=3, now=NOW)
    webhook.delivered()
    assert webhook.failed_streak == 0
    for _ in range(2):
        assert not webhook.gave_up(disable_after=3, now=NOW)
    assert webhook.gave_up(disable_after=3, now=NOW)
    assert not webhook.active and webhook.disabled_reason == DISABLED_FAILING


def test_a_delivery_keeps_only_a_short_error() -> None:
    delivery = WebhookDelivery.record(
        webhook_id=hook().id,
        event_id=EventId(new_id()),
        event_type="document.filed",
        document_id=None,
        attempt=1,
        started_at=NOW,
        duration_ms=5,
        outcome=DeliveryOutcome.RETRYING,
        error="x" * 1000,
    )
    assert delivery.error is not None and len(delivery.error) == 300


# --- headers of its own and the secret ----------------------------------------------------------


def test_header_names_are_tokens_kept_in_order() -> None:
    names = ["Authorization", "X-Tenant", "x-api-key", "A!#$%&'*+-.^_`|~1"]
    assert validate_header_names(names) == tuple(names)


@pytest.mark.parametrize(
    "name",
    [
        "Content-Type",
        "content-length",
        "Host",
        "Connection",
        "Transfer-Encoding",
        "Webhook-Signature",
        "webhook-id",
        "Lekto-Task-Token",
        "lekto-anything",
    ],
)
def test_headers_lekto_or_http_set_cannot_be_set(name: str) -> None:
    with pytest.raises(ValidationError, match="Lekto sets the header"):
        validate_header_names([name])


@pytest.mark.parametrize("name", ["", "X Tenant", "X:Tenant", "Ü", "x" * 101, "a\nb"])
def test_a_header_name_is_a_token(name: str) -> None:
    with pytest.raises(ValidationError, match="no valid header name"):
        validate_header_names([name])


def test_a_header_name_comes_once_ignoring_case_and_their_number_is_limited() -> None:
    with pytest.raises(ValidationError, match="given twice"):
        validate_header_names(["X-Token", "x-token"])
    with pytest.raises(ValidationError, match=f"at most {MAX_HEADERS} headers"):
        validate_header_names([f"X-{index}" for index in range(MAX_HEADERS + 1)])


@pytest.mark.parametrize(
    "value",
    ["", "a\nb", "a\rb", "a\x00b", "a\tb", " a", "a ", "ä", "x" * (MAX_HEADER_VALUE + 1)],
    ids=["empty", "newline", "return", "nul", "tab", "leading", "trailing", "umlaut", "long"],
)
def test_a_header_value_is_one_line_of_limited_length(value: str) -> None:
    with pytest.raises(ValidationError, match="the value of 'X'"):
        validate_header_value("X", value)
    assert validate_header_value("X", "Bearer abc 123") == "Bearer abc 123"


def test_header_values_round_trip_as_bytes_and_other_bytes_are_refused() -> None:
    values = {"Authorization": "Bearer ä", "X-Tenant": "home"}  # bytes take any text
    assert headers_from_bytes(headers_to_bytes(values)) == values
    for data in (b"\xff", b"[]", b'{"a": 1}'):
        with pytest.raises(ValueError):
            headers_from_bytes(data)


def test_a_webhook_has_header_values_exactly_when_it_has_headers() -> None:
    webhook = hook()
    assert not webhook.header_names and webhook.encrypted_headers is None
    webhook.set_headers(["Authorization"], b"encrypted", now=NOW + timedelta(minutes=1))
    assert webhook.header_names == ("Authorization",)
    assert webhook.updated_at == NOW + timedelta(minutes=1)
    with pytest.raises(ValidationError):
        webhook.set_headers(["Authorization"], None, now=NOW)
    with pytest.raises(ValidationError):
        webhook.set_headers([], b"encrypted", now=NOW)
    webhook.set_headers([], None, now=NOW)
    assert not webhook.header_names and webhook.encrypted_headers is None


def test_a_webhook_without_a_secret_signs_nothing_until_it_gets_one() -> None:
    webhook = hook(encrypted_secret=None)
    assert not webhook.signed and webhook.encrypted_secrets(NOW) == []
    webhook.renew_secret(b"first", now=NOW, grace=timedelta(hours=24))
    # Nothing signed before: no predecessor with a grace period.
    assert webhook.signed and webhook.encrypted_secrets(NOW) == [b"first"]
    assert webhook.previous_secret is None and webhook.previous_valid_until is None


def test_removing_the_secret_ends_signing_with_the_predecessor_too() -> None:
    webhook = hook()
    webhook.renew_secret(b"second", now=NOW, grace=timedelta(hours=24))
    webhook.remove_secret(NOW + timedelta(minutes=1))
    assert not webhook.signed and webhook.encrypted_secrets(NOW) == []
    assert webhook.previous_secret is None and webhook.previous_valid_until is None
    assert webhook.updated_at == NOW + timedelta(minutes=1)


def test_without_a_secret_a_request_has_id_and_timestamp_but_no_signature() -> None:
    headers = signed_headers([], "msg_1", 1_700_000_000, b"{}")
    assert headers == {ID_HEADER: "msg_1", TIMESTAMP_HEADER: "1700000000"}
    assert SIGNATURE_HEADER not in headers


# --- body -----------------------------------------------------------------------------------------


def body_of(webhook: Webhook) -> tuple[BodyFormat, str | None]:
    return webhook.body, webhook.body_template


def test_a_webhook_is_thin_unless_set_otherwise_and_a_template_comes_with_its_body() -> None:
    webhook = hook()
    assert body_of(webhook) == (BodyFormat.THIN, None)
    template = '{"title": {{ title | json }}}'
    webhook.set_body(BodyFormat.TEMPLATE, template, now=NOW)
    assert body_of(webhook) == (BodyFormat.TEMPLATE, template)
    webhook.set_body(BodyFormat.FULL, None, now=NOW)
    assert body_of(webhook) == (BodyFormat.FULL, None)
    for body, given in (
        (BodyFormat.TEMPLATE, None),
        (BodyFormat.TEMPLATE, "  "),
        (BodyFormat.TEMPLATE, "x" * (MAX_BODY_TEMPLATE + 1)),
        (BodyFormat.THIN, "{}"),
        (BodyFormat.FULL, "{}"),
    ):
        with pytest.raises(ValidationError):
            webhook.set_body(body, given, now=NOW)
    assert body_of(webhook) == (BodyFormat.FULL, None)


def test_a_full_body_carries_the_document_and_a_thin_one_does_not() -> None:
    event, document = EventId(new_id()), DocumentId(new_id())
    thin = event_body(event_id=event, type="document.filed", occurred_at=NOW, document_id=document)
    assert "document" not in json.loads(thin)
    full = event_body(
        event_id=event,
        type="document.filed",
        occurred_at=NOW,
        document_id=document,
        document={"title": "Rechnung"},
        full=True,
    )
    assert json.loads(full)["document"] == {"title": "Rechnung"}
    gone = event_body(
        event_id=event, type="document.deleted", occurred_at=NOW, document_id=document, full=True
    )
    assert json.loads(gone)["document"] is None


def test_a_rendered_body_must_be_json_and_goes_as_it_is() -> None:
    text = '{ "title": "Rechnung März" }\n'
    assert rendered_body(text) == text.encode("utf-8")
    with pytest.raises(ValueError, match="does not make JSON"):
        rendered_body('{"title": Rechnung}')
