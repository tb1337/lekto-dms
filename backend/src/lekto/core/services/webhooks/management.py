"""Creating, changing and deleting webhooks, and reading their delivery log.

Who may do what: a webhook belongs to its owner, who changes and deletes it, renews or removes
its secret and tests it. Admins may do all of that to every webhook (Tobi, 08.10.2026); a secret
they renew is shown to them, once. The secret is never shown again, nor are the values of the
webhook's own headers (their names are). Other users do not learn that someone else's webhook
exists (NotFoundError).
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from lekto.core.domain.errors import ConflictError, NotFoundError, ValidationError
from lekto.core.domain.ids import DeliveryId, UserId, WebhookId, new_id
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.templates import WEBHOOK_NAMES, unknown_values
from lekto.core.domain.users import User
from lekto.core.domain.webhooks import (
    BodyFormat,
    Webhook,
    WebhookDelivery,
    headers_from_bytes,
    headers_to_bytes,
    new_secret,
    validate_header_names,
    validate_header_value,
)
from lekto.core.ports.clock import Clock
from lekto.core.ports.identity import DecryptionError, SecretCipher
from lekto.core.ports.repository import PAGE_LIMIT, PAGE_SIZE
from lekto.core.ports.templates import TemplateRenderer
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_actor
from lekto.core.services.rules.references import disable_rules, refers_to
from lekto.core.services.webhooks.policy import WebhookPolicy


@dataclass(frozen=True)
class CreatedWebhook:
    """A new or renewed secret is shown here and nowhere else; None for a webhook created
    without one."""

    webhook: Webhook
    secret: str | None = field(repr=False)


def secret_context(id: WebhookId) -> bytes:
    """Binds an encrypted secret to its webhook."""
    return b"webhook:" + id.bytes


def headers_context(id: WebhookId) -> bytes:
    """Binds the encrypted header values to their webhook."""
    return b"webhook-headers:" + id.bytes


class WebhookService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        cipher: SecretCipher,
        policy: WebhookPolicy,
        templates: TemplateRenderer,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._cipher = cipher
        self._policy = policy
        self._templates = templates

    async def create(
        self,
        actor: UserId,
        *,
        name: str,
        url: str,
        event_types: Collection[str],
        active: bool = True,
        signed: bool = True,
        headers: Mapping[str, str] | None = None,
        body: BodyFormat = BodyFormat.THIN,
        body_template: str | None = None,
    ) -> CreatedWebhook:
        """`signed`: with a secret (shown once in the answer); `headers`: the webhook's own,
        name to value; `body`, with its template for `template`. ValidationError for a bad URL,
        event type, header or template, ConflictError at the user's limit."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            if await uow.webhooks.count_for_owner(user.id) >= self._policy.per_user:
                raise ConflictError(because(ReasonCode.WEBHOOKS_LIMIT, max=self._policy.per_user))
            id = WebhookId(new_id())
            secret = new_secret() if signed else None
            now = self._clock.now()
            webhook = Webhook.create(
                id=id,
                owner_id=user.id,
                name=name,
                url=url,
                event_types=event_types,
                encrypted_secret=None if secret is None else self._encrypt(id, secret),
                now=now,
                active=active,
            )
            given = dict(headers or {})
            webhook.set_headers(given, self._encrypt_headers(id, given), now=now)
            webhook.set_body(body, await self._checked(uow, body, body_template), now=now)
            await uow.webhooks.add(webhook)
            await uow.commit()
        return CreatedWebhook(webhook, secret)

    async def list_webhooks(self, actor: UserId, *, owner: UserId | None = None) -> list[Webhook]:
        """The caller's webhooks, oldest first. Admins get everybody's; `owner` narrows to one
        user's."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            if not user.is_active_admin:
                if owner is not None and owner != user.id:
                    return []
                return await uow.webhooks.list_for_owner(user.id)
            if owner is not None:
                return await uow.webhooks.list_for_owner(owner)
            return await uow.webhooks.list_all()

    async def get(self, actor: UserId, id: WebhookId) -> Webhook:
        async with self._uow() as uow:
            return await visible_webhook(uow, await load_actor(uow, actor), id)

    async def update(
        self,
        actor: UserId,
        id: WebhookId,
        *,
        name: str | None = None,
        url: str | None = None,
        event_types: Collection[str] | None = None,
        active: bool | None = None,
        headers: Sequence[tuple[str, str | None]] | None = None,
        body: BodyFormat | None = None,
        body_template: str | None = None,
    ) -> Webhook:
        """`headers`: all of the webhook's own headers from now on, in order; a value None keeps
        the value the header has (ValidationError for a header it does not have yet). `body`:
        with its template for `template` (None: both stay)."""
        async with self._uow() as uow:
            webhook = await manageable_webhook(uow, await load_actor(uow, actor), id)
            now = self._clock.now()
            webhook.change(now=now, name=name, url=url, event_types=event_types, active=active)
            if headers is not None:
                given = self._merge_headers(webhook, headers)
                webhook.set_headers(given, self._encrypt_headers(webhook.id, given), now=now)
            if body is not None:
                webhook.set_body(body, await self._checked(uow, body, body_template), now=now)
            elif body_template is not None:
                raise ValidationError("give body_template together with body")
            await uow.webhooks.update(webhook)
            await uow.commit()
            return webhook

    async def delete(self, actor: UserId, id: WebhookId) -> None:
        """The webhook and its log. Deliveries that are queued find it gone and stop; the rules
        that send through it are disabled, with the reason (as when master data they refer to
        is deleted)."""
        async with self._uow() as uow:
            webhook = await manageable_webhook(uow, await load_actor(uow, actor), id)
            await disable_sending_rules(uow, [webhook], self._clock.now())
            await uow.webhooks.remove(webhook.id)
            await uow.commit()

    async def renew_secret(self, actor: UserId, id: WebhookId) -> CreatedWebhook:
        """A new secret, shown once. The old one signs next to it for the grace period; a
        webhook that did not sign signs from now on."""
        async with self._uow() as uow:
            webhook = await manageable_webhook(uow, await load_actor(uow, actor), id)
            secret = new_secret()
            webhook.renew_secret(
                self._encrypt(webhook.id, secret),
                now=self._clock.now(),
                grace=self._policy.secret_grace,
            )
            await uow.webhooks.update(webhook)
            await uow.commit()
        return CreatedWebhook(webhook, secret)

    async def remove_secret(self, actor: UserId, id: WebhookId) -> Webhook:
        """The webhook signs no more: its requests go without `webhook-signature`."""
        async with self._uow() as uow:
            webhook = await manageable_webhook(uow, await load_actor(uow, actor), id)
            webhook.remove_secret(self._clock.now())
            await uow.webhooks.update(webhook)
            await uow.commit()
            return webhook

    async def deliveries(
        self,
        actor: UserId,
        id: WebhookId,
        *,
        before: DeliveryId | None = None,
        limit: int = PAGE_SIZE,
    ) -> list[WebhookDelivery]:
        """The log of a webhook, newest first."""
        limit = max(1, min(limit, PAGE_LIMIT))
        async with self._uow() as uow:
            webhook = await visible_webhook(uow, await load_actor(uow, actor), id)
            return await uow.webhooks.deliveries(webhook.id, before=before, limit=limit)

    async def _checked(self, uow: UnitOfWork, body: BodyFormat, template: str | None) -> str | None:
        """The template of a `template` body, checked: its syntax, and that it uses only what a
        webhook's template sees (a field by its key). ValidationError otherwise."""
        if body is not BodyFormat.TEMPLATE or template is None:
            return template
        used = self._templates.check(template)
        keys = {item.key for item in await uow.fields.list_all()}
        unknown = unknown_values(used, keys, WEBHOOK_NAMES)
        if unknown:
            raise ValidationError(f"body_template: unknown value {unknown[0]}")
        return template

    def _encrypt(self, id: WebhookId, secret: str) -> bytes:
        return self._cipher.encrypt(secret.encode("ascii"), context=secret_context(id))

    def _encrypt_headers(self, id: WebhookId, headers: Mapping[str, str]) -> bytes | None:
        """The values encrypted, None without headers. ValidationError for a bad name or
        value."""
        names = validate_header_names(headers)
        values = {name: validate_header_value(name, headers[name]) for name in names}
        if not values:
            return None
        return self._cipher.encrypt(headers_to_bytes(values), context=headers_context(id))

    def _merge_headers(
        self, webhook: Webhook, headers: Sequence[tuple[str, str | None]]
    ) -> dict[str, str]:
        """The headers given, a missing value taken from the webhook (by name, ignoring case)."""
        known: dict[str, str] = {}
        if any(value is None for _, value in headers) and webhook.encrypted_headers is not None:
            try:
                stored = headers_from_bytes(
                    self._cipher.decrypt(
                        webhook.encrypted_headers, context=headers_context(webhook.id)
                    )
                )
            except (DecryptionError, ValueError):
                stored = {}  # unreadable (another secret key): every value must be given anew
            known = {name.lower(): value for name, value in stored.items()}
        merged: dict[str, str] = {}
        for name, value in headers:
            if value is None:
                value = known.get(name.lower())
                if value is None:
                    raise ValidationError(because(ReasonCode.HEADER_VALUE_MISSING, name=name))
            if name in merged:
                raise ValidationError(because(ReasonCode.HEADER_TWICE, name=name))
            merged[name] = value
        return merged


async def disable_sending_rules(
    uow: UnitOfWork, webhooks: Iterable[Webhook], now: datetime
) -> None:
    """Disable the rules that send through `webhooks`, which are about to go."""
    for webhook in webhooks:
        await disable_rules(
            uow,
            now,
            because(ReasonCode.RULE_DISABLED_DELETED, kind="webhook", name=webhook.name),
            refers_to(lambda references: references.webhooks, webhook.id),
        )


async def visible_webhook(uow: UnitOfWork, user: User, id: WebhookId) -> Webhook:
    webhook = await uow.webhooks.find(id)
    if webhook is None or not (webhook.owner_id == user.id or user.is_active_admin):
        raise NotFoundError("webhook", id)
    return webhook


async def manageable_webhook(uow: UnitOfWork, user: User, id: WebhookId) -> Webhook:
    """The caller's own webhook, or any webhook for an admin: whoever may see it may change it."""
    return await visible_webhook(uow, user, id)
