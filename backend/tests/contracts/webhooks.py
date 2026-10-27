"""Contract suite for `WebhookRepository` in the unit of work: webhooks and the log of their
deliveries."""

from datetime import timedelta

import pytest

from lekto.core.domain.errors import ConcurrencyError, NotFoundError
from lekto.core.domain.ids import DeliveryId, DocumentId, EventId, new_id
from lekto.core.domain.users import User
from lekto.core.domain.webhooks import (
    ALL_EVENTS,
    BodyFormat,
    DeliveryOutcome,
    ModelCallKind,
    ModelCallRole,
    Webhook,
    WebhookDelivery,
)
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from tests import builders
from tests.builders import HOUR, NOW
from tests.contracts.unit_of_work import a_user


def a_webhook(
    owner: User,
    *,
    types: tuple[str, ...] = (ALL_EVENTS,),
    at: timedelta = timedelta(0),
    **fields: object,
) -> Webhook:
    values: dict[str, object] = {
        "owner_id": owner.id,
        "name": "n8n",
        "url": "http://n8n.lan:5678/webhook/lekto",
        "event_types": types,
        "encrypted_secret": b"\x01encrypted",
        "now": NOW + at,
    }
    return Webhook.create(**{**values, **fields})  # type: ignore[arg-type]


def a_delivery(
    webhook: Webhook,
    *,
    at: timedelta = timedelta(0),
    outcome: DeliveryOutcome = DeliveryOutcome.DELIVERED,
    event_type: str = "document.filed",
) -> WebhookDelivery:
    return WebhookDelivery.record(
        webhook_id=webhook.id,
        event_id=EventId(new_id()),
        event_type=event_type,
        document_id=DocumentId(new_id()),
        attempt=1,
        started_at=NOW + at,
        duration_ms=12,
        outcome=outcome,
        status_code=200,
    )


class WebhookRepositoryContract:
    async def test_a_webhook_round_trips_with_all_its_fields(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner = await a_user(uow_factory)
        webhook = a_webhook(owner, types=("document.filed", "document.deleted"))
        webhook.renew_secret(b"\x01second", now=NOW + HOUR, grace=timedelta(hours=24))
        webhook.failed_streak = 4
        webhook.change(now=NOW + HOUR, max_open_tasks=7)
        webhook.serve(ModelCallRole(ModelCallKind.EXTRACT, timedelta(minutes=20)), now=NOW + HOUR)
        async with uow_factory() as uow:
            await uow.webhooks.add(webhook)
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.webhooks.get(webhook.id) == webhook
            assert await uow.webhooks.find(webhook.id) == webhook

    async def test_a_webhook_round_trips_with_headers_and_without_a_secret(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner = await a_user(uow_factory)
        webhook = a_webhook(owner, encrypted_secret=None)
        webhook.set_headers(["Authorization", "X-Tenant"], b"\x02values", now=NOW)
        webhook.set_body(BodyFormat.TEMPLATE, '{"t": {{ title | json }}}', now=NOW)
        async with uow_factory() as uow:
            await uow.webhooks.add(webhook)
            await uow.commit()
        async with uow_factory() as uow:
            stored = await uow.webhooks.get(webhook.id)
        assert stored == webhook
        assert stored.header_names == ("Authorization", "X-Tenant") and not stored.signed

    async def test_a_missing_webhook_is_not_found(self, uow_factory: UnitOfWorkFactory) -> None:
        async with uow_factory() as uow:
            assert await uow.webhooks.find(a_webhook(builders.user()).id) is None
            with pytest.raises(NotFoundError):
                await uow.webhooks.get(a_webhook(builders.user()).id)

    async def test_update_checks_the_version(self, uow_factory: UnitOfWorkFactory) -> None:
        owner = await a_user(uow_factory)
        webhook = a_webhook(owner)
        async with uow_factory() as uow:
            await uow.webhooks.add(webhook)
            await uow.commit()
        async with uow_factory() as first, uow_factory() as second:
            one, other = await first.webhooks.get(webhook.id), await second.webhooks.get(webhook.id)
            one.change(now=NOW + HOUR, name="first")
            await first.webhooks.update(one)
            await first.commit()
            other.change(now=NOW + HOUR, name="second")
            with pytest.raises(ConcurrencyError):
                await second.webhooks.update(other)
                await second.commit()
        async with uow_factory() as uow:
            stored = await uow.webhooks.get(webhook.id)
            assert (stored.name, stored.version) == ("first", 2)
        assert one.version == 2

    async def test_reads_return_copies(self, uow_factory: UnitOfWorkFactory) -> None:
        owner = await a_user(uow_factory)
        webhook = a_webhook(owner)
        async with uow_factory() as uow:
            await uow.webhooks.add(webhook)
            await uow.commit()
        async with uow_factory() as uow:
            (await uow.webhooks.get(webhook.id)).change(now=NOW, name="changed")
            assert (await uow.webhooks.get(webhook.id)).name == "n8n"

    async def test_lists_are_oldest_first_and_per_owner(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner, other = await a_user(uow_factory), await a_user(uow_factory)
        second = a_webhook(owner, at=HOUR, name="second")
        first = a_webhook(owner, name="first")
        foreign = a_webhook(other, at=2 * HOUR, name="foreign")
        async with uow_factory() as uow:
            for webhook in (second, first, foreign):
                await uow.webhooks.add(webhook)
            await uow.commit()
        async with uow_factory() as uow:
            assert [w.name for w in await uow.webhooks.list_for_owner(owner.id)] == [
                "first",
                "second",
            ]
            assert [w.name for w in await uow.webhooks.list_all()] == ["first", "second", "foreign"]
            assert await uow.webhooks.count_for_owner(owner.id) == 2
            assert await uow.webhooks.count_for_owner(other.id) == 1

    async def test_active_for_an_event_type_lists_those_that_want_it(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner = await a_user(uow_factory)
        everything = a_webhook(owner, name="all")
        filed = a_webhook(owner, types=("document.filed",), name="filed", at=HOUR)
        updated = a_webhook(owner, types=("document.updated",), name="updated", at=2 * HOUR)
        off = a_webhook(owner, name="off", at=3 * HOUR, active=False)
        async with uow_factory() as uow:
            for webhook in (everything, filed, updated, off):
                await uow.webhooks.add(webhook)
            await uow.commit()
        async with uow_factory() as uow:
            names = [w.name for w in await uow.webhooks.list_active_for("document.filed")]
            assert names == ["all", "filed"]
            assert [w.name for w in await uow.webhooks.list_active_for("webhook.other")] == ["all"]

    async def test_model_calls_are_listed_active_or_not(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner = await a_user(uow_factory)
        extract = a_webhook(owner, name="extract", at=HOUR, active=False)
        extract.serve(ModelCallRole(ModelCallKind.EXTRACT), now=NOW)
        propose = a_webhook(owner, name="propose")
        propose.serve(ModelCallRole(ModelCallKind.PROPOSE), now=NOW)
        plain = a_webhook(owner, name="plain", at=2 * HOUR)
        async with uow_factory() as uow:
            for webhook in (extract, propose, plain):
                await uow.webhooks.add(webhook)
            await uow.commit()
        async with uow_factory() as uow:
            listed = await uow.webhooks.list_model_calls()
        assert [webhook.name for webhook in listed] == ["propose", "extract"]
        assert listed[1].model_call == ModelCallRole(ModelCallKind.EXTRACT)

    async def test_remove_takes_the_deliveries_along_and_missing_is_a_no_op(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner = await a_user(uow_factory)
        webhook, keep = a_webhook(owner), a_webhook(owner, name="keep")
        async with uow_factory() as uow:
            await uow.webhooks.add(webhook)
            await uow.webhooks.add(keep)
            await uow.webhooks.add_delivery(a_delivery(webhook))
            await uow.webhooks.add_delivery(a_delivery(keep))
            await uow.commit()
        async with uow_factory() as uow:
            await uow.webhooks.remove(webhook.id)
            await uow.webhooks.remove(webhook.id)
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.webhooks.find(webhook.id) is None
            assert await uow.webhooks.deliveries(webhook.id) == []
            assert len(await uow.webhooks.deliveries(keep.id)) == 1

    async def test_remove_for_owner_removes_their_webhooks_only(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner, other = await a_user(uow_factory), await a_user(uow_factory)
        mine, theirs = a_webhook(owner), a_webhook(other)
        async with uow_factory() as uow:
            await uow.webhooks.add(mine)
            await uow.webhooks.add(theirs)
            await uow.webhooks.add_delivery(a_delivery(mine))
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.webhooks.remove_for_owner(owner.id) == 1
            assert await uow.webhooks.remove_for_owner(owner.id) == 0
            await uow.commit()
        async with uow_factory() as uow:
            assert [w.id for w in await uow.webhooks.list_all()] == [theirs.id]

    async def test_deliveries_round_trip_newest_first_in_pages(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner = await a_user(uow_factory)
        webhook = a_webhook(owner)
        deliveries = [a_delivery(webhook, at=timedelta(minutes=n)) for n in range(5)]
        deliveries[3].outcome = DeliveryOutcome.RETRYING
        deliveries[3].status_code = 503
        deliveries[3].error = "HTTP 503"
        deliveries[3].next_attempt_at = NOW + HOUR
        async with uow_factory() as uow:
            await uow.webhooks.add(webhook)
            for delivery in deliveries:
                await uow.webhooks.add_delivery(delivery)
            await uow.commit()
        newest_first = sorted(deliveries, key=lambda delivery: delivery.id, reverse=True)
        async with uow_factory() as uow:
            page = await uow.webhooks.deliveries(webhook.id, limit=2)
            assert page == newest_first[:2]
            after = await uow.webhooks.deliveries(webhook.id, before=page[-1].id, limit=10)
            assert after == newest_first[2:]
            assert await uow.webhooks.deliveries(webhook.id) == newest_first

    async def test_deliveries_filter_by_outcome_and_event_and_count(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner = await a_user(uow_factory)
        webhook, other = a_webhook(owner), a_webhook(owner)
        failed, retrying = DeliveryOutcome.GAVE_UP, DeliveryOutcome.RETRYING
        deliveries = [
            a_delivery(webhook, at=timedelta(minutes=0)),
            a_delivery(webhook, at=timedelta(minutes=1), outcome=failed),
            a_delivery(webhook, at=timedelta(minutes=2), event_type="webhook.test"),
            a_delivery(webhook, at=timedelta(minutes=3), outcome=retrying),
            a_delivery(webhook, at=timedelta(minutes=4), outcome=failed, event_type="rule.send"),
            a_delivery(other, at=timedelta(minutes=5), outcome=failed),
        ]
        async with uow_factory() as uow:
            await uow.webhooks.add(webhook)
            await uow.webhooks.add(other)
            for delivery in deliveries:
                await uow.webhooks.add_delivery(delivery)
            await uow.commit()
        mine = deliveries[:5]

        def newest(*picked: int) -> list[DeliveryId]:
            return sorted((mine[n].id for n in picked), reverse=True)

        async with uow_factory() as uow:
            problems = await uow.webhooks.deliveries(webhook.id, outcomes={failed, retrying})
            assert [d.id for d in problems] == newest(1, 3, 4)
            filed = await uow.webhooks.deliveries(webhook.id, event_type="document.filed")
            assert [d.id for d in filed] == newest(0, 1, 3)
            both = await uow.webhooks.deliveries(
                webhook.id, outcomes={failed}, event_type="document.filed"
            )
            assert [d.id for d in both] == newest(1)
            page = await uow.webhooks.deliveries(webhook.id, offset=1, limit=2)
            assert [d.id for d in page] == newest(0, 1, 2, 3, 4)[1:3]
            assert await uow.webhooks.deliveries(webhook.id, outcomes=set()) == []
            assert await uow.webhooks.delivery_counts(webhook.id) == {
                DeliveryOutcome.DELIVERED: 2,
                failed: 2,
                retrying: 1,
            }
            assert await uow.webhooks.delivery_counts(webhook.id, event_type="rule.send") == {
                failed: 1
            }
            assert await uow.webhooks.delivery_event_types(webhook.id) == [
                "document.filed",
                "rule.send",
                "webhook.test",
            ]

    async def test_a_delivery_needs_its_webhook(self, uow_factory: UnitOfWorkFactory) -> None:
        owner = await a_user(uow_factory)
        gone = a_webhook(owner)
        async with uow_factory() as uow:
            with pytest.raises(NotFoundError):
                await uow.webhooks.add_delivery(a_delivery(gone))

    async def test_purge_removes_old_deliveries(self, uow_factory: UnitOfWorkFactory) -> None:
        owner = await a_user(uow_factory)
        webhook = a_webhook(owner)
        old, edge, recent = (
            a_delivery(webhook, at=timedelta(days=-3)),
            a_delivery(webhook, at=timedelta(days=-2)),
            a_delivery(webhook, at=timedelta(days=-1)),
        )
        async with uow_factory() as uow:
            await uow.webhooks.add(webhook)
            for delivery in (old, edge, recent):
                await uow.webhooks.add_delivery(delivery)
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.webhooks.purge_deliveries(before=NOW - timedelta(days=2)) == 1
            await uow.commit()
        async with uow_factory() as uow:
            kept = {delivery.id for delivery in await uow.webhooks.deliveries(webhook.id)}
            assert kept == {edge.id, recent.id}

    async def test_a_rolled_back_unit_leaves_nothing(self, uow_factory: UnitOfWorkFactory) -> None:
        owner = await a_user(uow_factory)
        webhook = a_webhook(owner)
        async with uow_factory() as uow:
            await uow.webhooks.add(webhook)
            await uow.webhooks.add_delivery(a_delivery(webhook))
            await uow.rollback()
        async with uow_factory() as uow:
            assert await uow.webhooks.find(webhook.id) is None
