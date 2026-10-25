"""Creating, changing and deleting webhooks, and reading their delivery log.

Who may do what: a webhook belongs to its owner, who changes and deletes it, renews or removes
its secret and tests it. Admins may do all of that to every webhook (Tobi, 08.10.2026); a secret
they renew is shown to them, once. The secret is never shown again, nor are the values of the
webhook's own headers (their names are). Other users do not learn that someone else's webhook
exists (NotFoundError).

Only an admin makes an admin's webhook serve as a model call (`ModelCallRole`), and of the
webhooks that serve (active, an active admin's) at most one serves each kind
(`serving_model_call`).
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from lekto.core.domain.documents import UNSET, Unset
from lekto.core.domain.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from lekto.core.domain.ids import DeliveryId, UserId, WebhookId, new_id
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.templates import WEBHOOK_NAMES, unknown_values
from lekto.core.domain.users import User
from lekto.core.domain.webhooks import (
    DEFAULT_OPEN_TASKS,
    BodyFormat,
    ModelCallKind,
    ModelCallRole,
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
from lekto.core.services.tasks.settling import drop_queued, wake_queue
from lekto.core.services.webhooks.policy import WebhookPolicy

MODEL_CALLS_LOCK = "model-calls"
"""The name a unit of work locks while it checks which webhook serves a model call, so two
never come to serve the same kind."""


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
        max_open_tasks: int = DEFAULT_OPEN_TASKS,
        model_call: ModelCallRole | None = None,
    ) -> CreatedWebhook:
        """`signed`: with a secret (shown once in the answer); `headers`: the webhook's own,
        name to value; `body`, with its template for `template`; `max_open_tasks`: how many
        tasks it takes at the same time; `model_call`: the model call it serves as (admins
        only). ValidationError for a bad URL, event type, header, template or number,
        ConflictError at the user's limit or for a model call another webhook serves,
        PermissionDeniedError for a model call of a user who is not an admin."""
        async with self._uow() as uow:
            if model_call is not None:
                await uow.lock(MODEL_CALLS_LOCK)
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
                max_open_tasks=max_open_tasks,
            )
            given = dict(headers or {})
            webhook.set_headers(given, self._encrypt_headers(id, given), now=now)
            webhook.set_body(body, await self._checked(uow, body, body_template), now=now)
            if model_call is not None:
                webhook.serve(model_call, now=now)
                await _check_model_call(uow, user, webhook)
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
        max_open_tasks: int | None = None,
        model_call: ModelCallRole | Unset | None = UNSET,
    ) -> Webhook:
        """`headers`: all of the webhook's own headers from now on, in order; a value None keeps
        the value the header has (ValidationError for a header it does not have yet). `body`:
        with its template for `template` (None: both stay). More room for tasks goes to those
        that wait at once. `model_call`: the model call it serves as from now on (None: none;
        left out: it stays), as for `create`."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            webhook = await manageable_webhook(uow, user, id)
            now = self._clock.now()
            switched_on = active is True and not webhook.active
            if isinstance(model_call, ModelCallRole) or (
                switched_on and webhook.model_call is not None
            ):
                await uow.lock(MODEL_CALLS_LOCK)
            more_room = max_open_tasks is not None and max_open_tasks > webhook.max_open_tasks
            webhook.change(
                now=now,
                name=name,
                url=url,
                event_types=event_types,
                active=active,
                max_open_tasks=max_open_tasks,
            )
            if headers is not None:
                given = self._merge_headers(webhook, headers)
                webhook.set_headers(given, self._encrypt_headers(webhook.id, given), now=now)
            if body is not None:
                webhook.set_body(body, await self._checked(uow, body, body_template), now=now)
            elif body_template is not None:
                raise ValidationError("give body_template together with body")
            if not isinstance(model_call, Unset) and model_call != webhook.model_call:
                webhook.serve(model_call, now=now)
                await _check_model_call(uow, user, webhook)
            elif switched_on and webhook.model_call is not None:
                await _check_model_call(uow, user, webhook, granted=True)
            await uow.webhooks.update(webhook)
            if more_room:
                await wake_queue(uow, webhook.id, now)
            await uow.commit()
            return webhook

    async def delete(self, actor: UserId, id: WebhookId) -> None:
        """The webhook and its log. Deliveries that are queued find it gone and stop; the rules
        that send through it are disabled, with the reason (as when master data they refer to
        is deleted). Its tasks that wait to be sent fail; its open tasks run to their deadline
        (an answer is still taken)."""
        async with self._uow() as uow:
            webhook = await manageable_webhook(uow, await load_actor(uow, actor), id)
            now = self._clock.now()
            await disable_sending_rules(uow, [webhook], now)
            await drop_queued(uow, webhook, now)
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


async def serving_model_call(uow: UnitOfWork, kind: ModelCallKind) -> Webhook | None:
    """The webhook that serves as the model call `kind`: an active one with that role whose
    owner is an active admin (the oldest, should there be two); None: the language model of
    the configuration answers, if there is one."""
    for webhook in await uow.webhooks.list_model_calls():
        if (
            webhook.active
            and webhook.model_call is not None
            and webhook.model_call.kind is kind
            and await _admins(uow, webhook)
        ):
            return webhook
    return None


async def _admins(uow: UnitOfWork, webhook: Webhook) -> bool:
    owner = await uow.users.find(webhook.owner_id)
    return owner is not None and owner.is_active_admin


async def _check_model_call(
    uow: UnitOfWork, actor: User, webhook: Webhook, *, granted: bool = False
) -> None:
    """The model call `webhook` serves as from now on may be: an admin gives it to an admin's
    webhook (`granted`: it was given before), and no other webhook serves that kind.
    PermissionDeniedError or ConflictError otherwise."""
    role = webhook.model_call
    if role is None:
        return
    admins = await _admins(uow, webhook)
    if not granted and not (actor.is_active_admin and admins):
        raise PermissionDeniedError(because(ReasonCode.MODEL_CALL_ADMINS))
    if not (webhook.active and admins):
        return  # it does not serve
    serving = await serving_model_call(uow, role.kind)
    if serving is not None and serving.id != webhook.id:
        raise ConflictError(
            because(ReasonCode.MODEL_CALL_TAKEN, webhook=serving.name, kind=role.kind.value)
        )


async def visible_webhook(uow: UnitOfWork, user: User, id: WebhookId) -> Webhook:
    webhook = await uow.webhooks.find(id)
    if webhook is None or not (webhook.owner_id == user.id or user.is_active_admin):
        raise NotFoundError("webhook", id)
    return webhook


async def manageable_webhook(uow: UnitOfWork, user: User, id: WebhookId) -> Webhook:
    """The caller's own webhook, or any webhook for an admin: whoever may see it may change it."""
    return await visible_webhook(uow, user, id)
