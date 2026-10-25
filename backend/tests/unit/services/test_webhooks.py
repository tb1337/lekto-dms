"""Managing webhooks: who sees and changes what, the secret, the limit."""

from dataclasses import replace
from datetime import timedelta

import pytest

from lekto.core.domain.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from lekto.core.domain.ids import WebhookId, new_id
from lekto.core.domain.users import Role
from lekto.core.domain.webhooks import DISABLED_FAILING, headers_from_bytes, new_secret
from lekto.core.services.webhooks import WebhookService
from lekto.core.services.webhooks.management import headers_context, secret_context
from tests import builders
from tests.unit.services.support import World

URL = "http://n8n.lan:5678/webhook/lekto"


async def test_a_user_creates_a_webhook_and_sees_the_secret_once(world: World) -> None:
    user = await world.user()
    created = await world.webhooks.create(
        user.id, name="n8n", url=URL, event_types=["document.filed"]
    )
    assert created.secret is not None and created.secret.startswith("whsec_")
    assert created.webhook.owner_id == user.id and created.webhook.active
    async with world.uow() as uow:
        stored = await uow.webhooks.get(created.webhook.id)
    # Stored encrypted, bound to the webhook: not the plain secret.
    assert stored.encrypted_secret is not None
    assert created.secret.encode() not in stored.encrypted_secret
    assert (
        world.cipher.decrypt(stored.encrypted_secret, context=secret_context(stored.id)).decode()
        == created.secret
    )
    listed = await world.webhooks.list_webhooks(user.id)
    assert [webhook.id for webhook in listed] == [created.webhook.id]


async def test_a_bad_url_or_event_type_is_refused(world: World) -> None:
    user = await world.user()
    with pytest.raises(ValidationError):
        await world.webhooks.create(user.id, name="x", url="ftp://x", event_types=["*"])
    with pytest.raises(ValidationError):
        await world.webhooks.create(user.id, name="x", url=URL, event_types=["nonsense"])
    assert await world.webhooks.list_webhooks(user.id) == []


async def test_the_number_of_webhooks_per_user_is_limited(world: World) -> None:
    user, other = await world.user(), await world.user()
    service = WebhookService(
        world.uow, world.clock, world.cipher, replace(builders.WEBHOOKS, per_user=2)
    )
    for _ in range(2):
        await service.create(user.id, name="x", url=URL, event_types=["*"])
    with pytest.raises(ConflictError):
        await service.create(user.id, name="x", url=URL, event_types=["*"])
    await service.create(other.id, name="x", url=URL, event_types=["*"])


async def test_others_do_not_find_a_webhook_but_admins_read_it(world: World) -> None:
    owner, other = await world.user(), await world.user()
    admin = await world.user(role=Role.ADMIN)
    service = world.webhooks
    hook = (await service.create(owner.id, name="x", url=URL, event_types=["*"])).webhook
    with pytest.raises(NotFoundError):
        await service.get(other.id, hook.id)
    with pytest.raises(NotFoundError):
        await service.deliveries(other.id, hook.id)
    with pytest.raises(NotFoundError):
        await service.update(other.id, hook.id, name="mine")
    assert await service.list_webhooks(other.id) == []
    assert (await service.get(admin.id, hook.id)).id == hook.id
    assert await service.deliveries(admin.id, hook.id) == []
    assert [webhook.id for webhook in await service.list_webhooks(admin.id)] == [hook.id]
    owned = await service.list_webhooks(admin.id, owner=owner.id)
    assert [webhook.id for webhook in owned] == [hook.id]
    assert await service.list_webhooks(admin.id, owner=other.id) == []
    assert await service.list_webhooks(other.id, owner=owner.id) == []


async def test_admins_change_renew_and_delete_other_users_webhooks(world: World) -> None:
    owner, admin = await world.user(), await world.user(role=Role.ADMIN)
    service = world.webhooks
    hook = (await service.create(owner.id, name="x", url=URL, event_types=["*"])).webhook
    assert (await service.update(admin.id, hook.id, name="by admin")).name == "by admin"
    renewed = await service.renew_secret(admin.id, hook.id)
    assert renewed.secret is not None and renewed.secret.startswith("whsec_")
    assert (await service.get(owner.id, hook.id)).owner_id == owner.id
    await service.delete(admin.id, hook.id)
    with pytest.raises(NotFoundError):
        await service.get(owner.id, hook.id)


async def test_the_owner_changes_and_switches_off_and_on(world: World) -> None:
    user = await world.user()
    service = world.webhooks
    hook = (await service.create(user.id, name="x", url=URL, event_types=["*"])).webhook
    changed = await service.update(
        user.id, hook.id, name="HA", url="https://ha.example.org/h", event_types=["document.filed"]
    )
    assert (changed.name, changed.url, changed.event_types) == (
        "HA",
        "https://ha.example.org/h",
        frozenset({"document.filed"}),
    )
    assert not (await service.update(user.id, hook.id, active=False)).active
    with pytest.raises(ValidationError):
        await service.update(user.id, hook.id, url="javascript:x")
    async with world.uow() as uow:
        webhook = await uow.webhooks.get(hook.id)
        webhook.active, webhook.disabled_reason, webhook.failed_streak = (
            False,
            DISABLED_FAILING,
            20,
        )
        await uow.webhooks.update(webhook)
        await uow.commit()
    again = await service.update(user.id, hook.id, active=True)
    assert (again.active, again.disabled_reason, again.failed_streak) == (True, None, 0)


async def test_renewing_the_secret_keeps_the_old_one_for_the_grace_period(world: World) -> None:
    user = await world.user()
    service = world.webhooks
    created = await service.create(user.id, name="x", url=URL, event_types=["*"])
    renewed = await service.renew_secret(user.id, created.webhook.id)
    assert renewed.secret != created.secret
    webhook = await service.get(user.id, created.webhook.id)
    assert webhook.previous_valid_until == world.clock.now() + timedelta(hours=24)
    secrets = [
        world.cipher.decrypt(item, context=secret_context(webhook.id)).decode()
        for item in webhook.encrypted_secrets(world.clock.now())
    ]
    assert secrets == [renewed.secret, created.secret]


async def test_delete_removes_the_webhook_and_a_deleted_user_loses_theirs(world: World) -> None:
    admin, user = await world.user(role=Role.ADMIN), await world.user()
    service = world.webhooks
    first = (await service.create(user.id, name="x", url=URL, event_types=["*"])).webhook
    await service.create(user.id, name="y", url=URL, event_types=["*"])
    await service.delete(user.id, first.id)
    with pytest.raises(NotFoundError):
        await service.get(user.id, first.id)
    with pytest.raises(NotFoundError):
        await service.delete(user.id, WebhookId(new_id()))
    await world.users.delete_user(admin.id, user.id)
    async with world.uow() as uow:
        assert await uow.webhooks.list_all() == []


async def test_a_deactivated_user_cannot_use_webhooks(world: World) -> None:
    admin, user = await world.user(role=Role.ADMIN), await world.user()
    await world.webhooks.create(user.id, name="x", url=URL, event_types=["*"])
    await world.users.update(admin.id, user.id, active=False)
    with pytest.raises(AuthenticationError):
        await world.webhooks.list_webhooks(user.id)
    with pytest.raises(AuthenticationError):
        await world.webhooks.create(user.id, name="y", url=URL, event_types=["*"])


async def test_a_webhook_may_go_unsigned_and_sign_again_later(world: World) -> None:
    user = await world.user()
    service = world.webhooks
    created = await service.create(user.id, name="HA", url=URL, event_types=["*"], signed=False)
    assert created.secret is None and not created.webhook.signed
    renewed = await service.renew_secret(user.id, created.webhook.id)
    assert renewed.secret is not None and renewed.webhook.signed
    # Nothing signed before: no old secret with a grace period.
    assert renewed.webhook.previous_valid_until is None
    removed = await service.remove_secret(user.id, created.webhook.id)
    assert not removed.signed and removed.previous_secret is None
    assert not (await service.get(user.id, created.webhook.id)).signed


def stored_headers(world: World, webhook_id: WebhookId, encrypted: bytes | None) -> dict[str, str]:
    assert encrypted is not None
    return headers_from_bytes(world.cipher.decrypt(encrypted, context=headers_context(webhook_id)))


async def test_header_values_are_stored_encrypted_and_kept_by_name(world: World) -> None:
    user = await world.user()
    service = world.webhooks
    created = await service.create(
        user.id,
        name="HA",
        url=URL,
        event_types=["*"],
        headers={"Authorization": "Bearer t0ken", "X-Tenant": "home"},
    )
    hook = created.webhook
    assert hook.header_names == ("Authorization", "X-Tenant")
    assert hook.encrypted_headers is not None and b"t0ken" not in hook.encrypted_headers
    assert stored_headers(world, hook.id, hook.encrypted_headers) == {
        "Authorization": "Bearer t0ken",
        "X-Tenant": "home",
    }
    # A value left out keeps the stored one (by name, ignoring case); the order follows.
    changed = await service.update(
        user.id, hook.id, headers=[("X-Tenant", "work"), ("authorization", None)]
    )
    assert changed.header_names == ("X-Tenant", "authorization")
    assert stored_headers(world, hook.id, changed.encrypted_headers) == {
        "X-Tenant": "work",
        "authorization": "Bearer t0ken",
    }
    with pytest.raises(ValidationError, match="new header 'X-New'"):
        await service.update(user.id, hook.id, headers=[("X-New", None)])
    cleared = await service.update(user.id, hook.id, headers=[])
    assert cleared.header_names == () and cleared.encrypted_headers is None


async def test_reserved_or_broken_headers_are_refused(world: World) -> None:
    user = await world.user()
    for headers in ({"Webhook-Signature": "x"}, {"Lekto-Task-Token": "x"}, {"X": "a\nb"}):
        with pytest.raises(ValidationError):
            await world.webhooks.create(
                user.id, name="x", url=URL, event_types=["*"], headers=headers
            )
    assert await world.webhooks.list_webhooks(user.id) == []


async def test_header_values_that_cannot_be_decrypted_must_be_given_anew(world: World) -> None:
    user = await world.user()
    hook = (
        await world.webhooks.create(
            user.id, name="x", url=URL, event_types=["*"], headers={"X-Token": "a"}
        )
    ).webhook
    async with world.uow() as uow:
        webhook = await uow.webhooks.get(hook.id)
        webhook.encrypted_headers = b"garbage"
        await uow.webhooks.update(webhook)
        await uow.commit()
    with pytest.raises(ValidationError, match="new header 'X-Token'"):
        await world.webhooks.update(user.id, hook.id, headers=[("X-Token", None)])
    changed = await world.webhooks.update(user.id, hook.id, headers=[("X-Token", "b")])
    assert stored_headers(world, hook.id, changed.encrypted_headers) == {"X-Token": "b"}


def test_new_secrets_do_not_repeat() -> None:
    assert new_secret() != new_secret()
