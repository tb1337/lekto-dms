"""Webhooks: a user's subscription to document events, and the log of the deliveries.

A webhook has a target URL, the event types it wants (or all of them), headers of its own and,
if it signs, a secret. Secret and header values are stored encrypted (they are needed to send,
so a hash would not do); the secret's plain text exists only in the answer to creating or
renewing it, the header values only in what the owner gives (the names stay readable).

Requests follow the Standard Webhooks scheme (https://www.standardwebhooks.com): the headers
`webhook-id` (the event id, for receivers to recognise repetitions), `webhook-timestamp`
(Unix seconds of the attempt) and, with a secret, `webhook-signature` (`v1,<base64
HMAC-SHA256>` of `<id>.<timestamp>.<body>`, several separated by spaces while a renewed secret
still has its predecessor alongside). A webhook without a secret is not signed (Tobi,
25.10.2026: Home Assistant, Node-RED and others check a header instead).

The body (`BodyFormat`) is thin (the event's type, id, time and document), full (the document
too, as it is when the request goes) or what the webhook's template (Liquid) makes of the
event and the document, which must be JSON.
"""

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.events import DOCUMENT_EVENT_TYPES
from lekto.core.domain.ids import DeliveryId, DocumentId, EventId, UserId, WebhookId, new_id
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.validation import (
    MAX_URL_LENGTH,
    has_control_characters,
    require_name,
    require_utc,
)

ALL_EVENTS = "*"
"""In `event_types`: every event type, also those that come later."""
TEST_EVENT = "webhook.test"
"""The event type of the test request; it has no document."""

SECRET_PREFIX = "whsec_"
SECRET_BYTES = 32
MAX_NAME_LENGTH = 100
MAX_ERROR_LENGTH = 300
DISABLED_FAILING = "failing"
"""`Webhook.disabled_reason` of a webhook that Lekto switched off after repeated failures."""

SIGNATURE_VERSION = "v1"
ID_HEADER = "webhook-id"
TIMESTAMP_HEADER = "webhook-timestamp"
SIGNATURE_HEADER = "webhook-signature"

MAX_BODY_TEMPLATE = 10_000


class BodyFormat(StrEnum):
    THIN = "thin"  # the event: type, id, time, document id
    FULL = "full"  # the event and the document as it is
    TEMPLATE = "template"  # what the webhook's template makes of them (JSON)


MAX_HEADERS = 20
MAX_HEADER_VALUE = 4096
_HEADER_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,100}")
"""A header name: a token of RFC 9110 (section 5.1), at most 100 characters."""
RESERVED_HEADERS = frozenset(
    {"content-type", "content-length", "host", "connection", "transfer-encoding"}
)
RESERVED_PREFIXES = ("webhook-", "lekto-")
"""Headers Lekto or HTTP set themselves; a webhook cannot set them (compared in lower case)."""


def event_type_names() -> list[str]:
    return sorted(DOCUMENT_EVENT_TYPES)


def validate_url(url: str) -> str:
    """The target URL: `http` or `https` with a host, no credentials, no fragment. Targets in
    the own network are fine. ValidationError otherwise."""
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise ValidationError(because(ReasonCode.URL_LENGTH, max=MAX_URL_LENGTH))
    if has_control_characters(url):
        raise ValidationError(because(ReasonCode.URL_SPACES))
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018  (raises ValueError for a bad port)
    except ValueError:
        raise ValidationError(because(ReasonCode.URL_INVALID)) from None
    if parts.scheme not in ("http", "https"):
        raise ValidationError(because(ReasonCode.URL_SCHEME))
    if not parts.hostname:
        raise ValidationError(because(ReasonCode.URL_NO_HOST))
    if parts.username is not None or parts.password is not None:
        raise ValidationError(because(ReasonCode.URL_CREDENTIALS))
    if parts.fragment:
        raise ValidationError(because(ReasonCode.URL_FRAGMENT))
    return url


def validate_header_names(names: Iterable[str]) -> tuple[str, ...]:
    """The names of a webhook's own headers, as given: tokens, none reserved, none twice
    (ignoring case), at most `MAX_HEADERS`. ValidationError otherwise."""
    checked: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
            raise ValidationError(because(ReasonCode.HEADER_NAME_INVALID, name=str(name)))
        key = name.lower()
        if key in RESERVED_HEADERS or key.startswith(RESERVED_PREFIXES):
            raise ValidationError(because(ReasonCode.HEADER_RESERVED, name=name))
        if key in seen:
            raise ValidationError(because(ReasonCode.HEADER_TWICE, name=name))
        seen.add(key)
        checked.append(name)
    if len(checked) > MAX_HEADERS:
        raise ValidationError(because(ReasonCode.HEADERS_LIMIT, max=MAX_HEADERS))
    return tuple(checked)


_HEADER_VALUE = re.compile(r"[!-~]([ !-~]*[!-~])?")
"""Printable ASCII, spaces only inside: no line break can start another header, and every HTTP
client sends it as it is."""


def validate_header_value(name: str, value: str) -> str:
    """A header's value: 1 to `MAX_HEADER_VALUE` characters of printable ASCII, spaces only
    inside. ValidationError otherwise."""
    if (
        not isinstance(value, str)
        or len(value) > MAX_HEADER_VALUE
        or not _HEADER_VALUE.fullmatch(value)
    ):
        raise ValidationError(
            because(ReasonCode.HEADER_VALUE_INVALID, name=name, max=MAX_HEADER_VALUE)
        )
    return value


def headers_to_bytes(headers: Mapping[str, str]) -> bytes:
    """The header values as they are encrypted: a JSON object, name to value."""
    return json.dumps(dict(headers), separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def headers_from_bytes(data: bytes) -> dict[str, str]:
    """The header values from their decrypted form; ValueError if it is not that form."""
    try:
        loaded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not the header values of a webhook") from error
    if not isinstance(loaded, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in loaded.items()
    ):
        raise ValueError("not the header values of a webhook")
    return loaded


def validate_event_types(types: Collection[str]) -> frozenset[str]:
    """The known event types, or `*` (then only that). ValidationError for none or unknown."""
    chosen = frozenset(types)
    if not chosen:
        raise ValidationError(because(ReasonCode.NO_EVENT_TYPES))
    unknown = sorted(chosen - DOCUMENT_EVENT_TYPES.keys() - {ALL_EVENTS})
    if unknown:
        raise ValidationError(
            f"unknown event types: {', '.join(unknown)}; "
            f"known: {', '.join(event_type_names())} or {ALL_EVENTS}"
        )
    return frozenset({ALL_EVENTS}) if ALL_EVENTS in chosen else chosen


def new_secret() -> str:
    """A new signing secret: `whsec_` and 32 random bytes in Base64."""
    return SECRET_PREFIX + base64.b64encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii")


def _key(secret: str) -> bytes:
    if not secret.startswith(SECRET_PREFIX):
        raise ValueError("not a webhook secret")
    try:
        return base64.b64decode(secret.removeprefix(SECRET_PREFIX), validate=True)
    except binascii.Error:
        raise ValueError("not a webhook secret") from None


def sign(secret: str, message_id: str, timestamp: int, body: bytes) -> str:
    """`v1,<base64>`: HMAC-SHA256 of `<message_id>.<timestamp>.<body>` with the secret's key."""
    content = f"{message_id}.{timestamp}.".encode() + body
    digest = hmac.new(_key(secret), content, hashlib.sha256).digest()
    return f"{SIGNATURE_VERSION},{base64.b64encode(digest).decode('ascii')}"


def signed_headers(
    secrets_in_use: Iterable[str], message_id: str, timestamp: int, body: bytes
) -> dict[str, str]:
    """The headers of a request: id, timestamp and one signature per secret in use; without a
    secret, no signature."""
    headers = {ID_HEADER: message_id, TIMESTAMP_HEADER: str(timestamp)}
    signatures = [sign(secret, message_id, timestamp, body) for secret in secrets_in_use]
    if signatures:
        headers[SIGNATURE_HEADER] = " ".join(signatures)
    return headers


def event_body(
    *,
    event_id: EventId | UUID,
    type: str,
    occurred_at: datetime,
    document_id: DocumentId | None,
    document: JsonObject | None = None,
    full: bool = False,
) -> bytes:
    """The body of a request: compact JSON in UTF-8, signed exactly as sent. Thin: the event;
    `full`: with `document` too (None: the document is gone, or there is none)."""
    occurred_at = require_utc(occurred_at, "occurred_at")
    payload: JsonObject = {
        "id": str(event_id),
        "type": type,
        "occurred_at": occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "document_id": None if document_id is None else str(document_id),
    }
    if full:
        payload["document"] = document
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def rendered_body(text: str) -> bytes:
    """What a template made, as the body goes: the text in UTF-8, as it is. ValueError if it is
    not JSON."""
    try:
        json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"the template does not make JSON: {error.msg} at line {error.lineno}, "
            f"column {error.colno}"
        ) from None
    return text.encode("utf-8")


def validate_body(body: BodyFormat, template: str | None) -> str | None:
    """The template of a body: given exactly for `template`, 1 to `MAX_BODY_TEMPLATE`
    characters (its syntax and values are checked where it is saved: the renderer is a port).
    ValidationError otherwise."""
    if body is not BodyFormat.TEMPLATE:
        if template is not None:
            raise ValidationError("body_template is given only for the body 'template'")
        return None
    if template is None or not template.strip():
        raise ValidationError("the body 'template' needs a template")
    if len(template) > MAX_BODY_TEMPLATE:
        raise ValidationError(f"body_template: at most {MAX_BODY_TEMPLATE} characters")
    return template


@dataclass(kw_only=True)
class Webhook:
    """A user's subscription. `encrypted_secret` is the secret as `SecretCipher` made it, None
    if the webhook does not sign; `previous_secret` still signs next to it until
    `previous_valid_until`. `header_names`: the webhook's own headers, in the order given;
    `encrypted_headers` their values (`headers_to_bytes`, encrypted), None without headers."""

    id: WebhookId
    owner_id: UserId
    name: str
    url: str
    event_types: frozenset[str]
    encrypted_secret: bytes | None = field(repr=False)
    header_names: tuple[str, ...] = ()
    encrypted_headers: bytes | None = field(default=None, repr=False)
    body: BodyFormat = BodyFormat.THIN
    body_template: str | None = None
    active: bool = True
    disabled_reason: str | None = None
    failed_streak: int = 0
    previous_secret: bytes | None = field(default=None, repr=False)
    previous_valid_until: datetime | None = None
    created_at: datetime
    updated_at: datetime
    version: int = 1

    def __post_init__(self) -> None:
        self.name = require_name(self.name, "webhook name", max_length=MAX_NAME_LENGTH)
        self.url = validate_url(self.url)
        self.event_types = validate_event_types(self.event_types)
        self.header_names = validate_header_names(self.header_names)
        self.body = BodyFormat(self.body)
        self.body_template = validate_body(self.body, self.body_template)
        if bool(self.header_names) != (self.encrypted_headers is not None):
            raise ValidationError("a webhook has header values exactly when it has headers")
        if self.encrypted_secret is None and self.previous_secret is not None:
            raise ValidationError("a webhook without a secret has no previous one")
        self.created_at = require_utc(self.created_at, "created_at")
        self.updated_at = require_utc(self.updated_at, "updated_at")

    @classmethod
    def create(
        cls,
        *,
        owner_id: UserId,
        name: str,
        url: str,
        event_types: Collection[str],
        encrypted_secret: bytes | None,
        now: datetime,
        active: bool = True,
        id: WebhookId | None = None,
    ) -> "Webhook":
        """`id`: given when the secret or header values were encrypted for it beforehand."""
        return cls(
            id=WebhookId(new_id()) if id is None else id,
            owner_id=owner_id,
            name=name,
            url=url,
            event_types=frozenset(event_types),
            encrypted_secret=encrypted_secret,
            active=active,
            created_at=now,
            updated_at=now,
        )

    @property
    def signed(self) -> bool:
        return self.encrypted_secret is not None

    def wants(self, event_type: str) -> bool:
        return ALL_EVENTS in self.event_types or event_type in self.event_types

    def change(
        self,
        *,
        now: datetime,
        name: str | None = None,
        url: str | None = None,
        event_types: Collection[str] | None = None,
        active: bool | None = None,
    ) -> None:
        """Change what is given. Switching on (again) clears the failures and the reason."""
        if name is not None:
            self.name = require_name(name, "webhook name", max_length=MAX_NAME_LENGTH)
        if url is not None:
            self.url = validate_url(url)
        if event_types is not None:
            self.event_types = validate_event_types(event_types)
        if active is not None:
            if active and not self.active:
                self.failed_streak = 0
            self.active = active
            self.disabled_reason = None
        self.updated_at = now

    def renew_secret(self, encrypted_secret: bytes, *, now: datetime, grace: timedelta) -> None:
        """A new secret; the old one keeps signing for `grace` (renewing again drops it). A
        webhook that did not sign signs from now on."""
        if self.encrypted_secret is None:
            self.previous_secret = self.previous_valid_until = None
        else:
            self.previous_secret = self.encrypted_secret
            self.previous_valid_until = now + grace
        self.encrypted_secret = encrypted_secret
        self.updated_at = now

    def remove_secret(self, now: datetime) -> None:
        """Stop signing: the secret and its predecessor are gone."""
        self.encrypted_secret = self.previous_secret = self.previous_valid_until = None
        self.updated_at = now

    def set_body(self, body: BodyFormat, template: str | None, *, now: datetime) -> None:
        """What the requests carry (`BodyFormat`); `template` exactly for `template`."""
        self.body_template = validate_body(BodyFormat(body), template)
        self.body = BodyFormat(body)
        self.updated_at = now

    def set_headers(self, names: Iterable[str], encrypted: bytes | None, *, now: datetime) -> None:
        """The webhook's own headers: their names and their values (encrypted; None for no
        headers)."""
        checked = validate_header_names(names)
        if bool(checked) != (encrypted is not None):
            raise ValidationError("a webhook has header values exactly when it has headers")
        self.header_names, self.encrypted_headers = checked, encrypted
        self.updated_at = now

    def drop_expired_secret(self, now: datetime) -> bool:
        """Forget the previous secret once its grace period is over. Returns True if it did."""
        if self.previous_secret is None or (
            self.previous_valid_until is not None and now < self.previous_valid_until
        ):
            return False
        self.previous_secret = None
        self.previous_valid_until = None
        return True

    def encrypted_secrets(self, now: datetime) -> list[bytes]:
        """The secrets that sign a request now: the current one, and the previous one during
        the grace period; none if the webhook does not sign."""
        if self.encrypted_secret is None:
            return []
        current = [self.encrypted_secret]
        if (
            self.previous_secret is not None
            and self.previous_valid_until is not None
            and now < self.previous_valid_until
        ):
            current.append(self.previous_secret)
        return current

    def delivered(self) -> None:
        self.failed_streak = 0

    def gave_up(self, *, disable_after: int, now: datetime) -> bool:
        """A delivery was given up. Returns True if this switched the webhook off."""
        self.failed_streak += 1
        if self.active and self.failed_streak >= disable_after:
            self.active = False
            self.disabled_reason = DISABLED_FAILING
            self.updated_at = now
            return True
        return False


class DeliveryOutcome(StrEnum):
    DELIVERED = "delivered"  # answered with 2xx
    RETRYING = "retrying"  # the attempt failed, another follows
    GAVE_UP = "gave_up"  # failed for good
    DROPPED = "dropped"  # not sent: the right to see the document is gone, or the webhook is off


@dataclass(kw_only=True)
class WebhookDelivery:
    """One attempt to deliver an event. The answer of the receiver is not kept."""

    id: DeliveryId
    webhook_id: WebhookId
    event_id: EventId
    event_type: str
    document_id: DocumentId | None
    attempt: int
    started_at: datetime
    duration_ms: int
    outcome: DeliveryOutcome
    status_code: int | None = None
    error: str | None = None
    next_attempt_at: datetime | None = None

    def __post_init__(self) -> None:
        self.started_at = require_utc(self.started_at, "started_at")
        if self.next_attempt_at is not None:
            self.next_attempt_at = require_utc(self.next_attempt_at, "next_attempt_at")
        if self.error is not None:
            self.error = self.error[:MAX_ERROR_LENGTH]

    @classmethod
    def record(
        cls,
        *,
        webhook_id: WebhookId,
        event_id: EventId,
        event_type: str,
        document_id: DocumentId | None,
        attempt: int,
        started_at: datetime,
        duration_ms: int,
        outcome: DeliveryOutcome,
        status_code: int | None = None,
        error: str | None = None,
        next_attempt_at: datetime | None = None,
    ) -> "WebhookDelivery":
        """A new attempt, with an id of its own."""
        return cls(
            id=DeliveryId(new_id()),
            webhook_id=webhook_id,
            event_id=event_id,
            event_type=event_type,
            document_id=document_id,
            attempt=attempt,
            started_at=started_at,
            duration_ms=duration_ms,
            outcome=outcome,
            status_code=status_code,
            error=error,
            next_attempt_at=next_attempt_at,
        )
