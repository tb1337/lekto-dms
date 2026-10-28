"""`/automation`: the numbers of the page "System" about the automation, for every user."""

from datetime import timedelta

from lekto.adapters.inbound.rest import PREFIX
from lekto.core.domain.classification import CONTACT
from lekto.core.domain.documents import Channel
from lekto.core.domain.first_runs import Decision, FieldVerdict, FirstRun, Verdict
from lekto.core.domain.pipeline import Node
from tests import builders
from tests.api import auth
from tests.builders import NOW
from tests.unit.adapters.rest.support import Api

AUTOMATION = f"{PREFIX}/automation"


async def seed(api: Api) -> None:
    """A green document of the web whose contact a person took over, and a migrated one."""
    owner = await api.user()
    async with api.container.unit_of_work() as uow:
        space = await uow.spaces.get_personal(owner.id)
        for channel in (Channel.WEB, Channel.MIGRATION):
            document = builders.processed(owner, space, content=channel.value)
            document.channel = channel
            await uow.documents.add(document)
            await uow.processing_facts.add_first_run(
                FirstRun(
                    document_id=document.id,
                    started_at=NOW - timedelta(minutes=2),
                    stopped_at=NOW - timedelta(minutes=1),
                    steps={Node.RECEIVE: timedelta(seconds=2)},
                )
            )
            await uow.processing_facts.add_verdicts(
                [
                    FieldVerdict(
                        document_id=document.id,
                        field=CONTACT,
                        verdict=Verdict.TAKEN,
                        decided_at=NOW,
                        decision=Decision.CHANGE,
                        signals={Node.SIGNAL_LLM: True},
                    )
                ]
            )
        await uow.commit()


async def test_every_user_sees_the_automation_of_the_web_and_the_api(api: Api) -> None:
    await seed(api)
    user = await api.user()

    response = await api.client.get(AUTOMATION, headers=auth(user))

    assert response.status_code == 200
    body = response.json()
    assert (body["channels"], body["period"]) == (["api", "web"], "12m")
    assert body["lanes"] == {"green": 1, "yellow": 0, "red": 0}
    assert body["flow"] == [{"first_lane": "green", "lane": "green", "count": 1}]
    assert (body["decided"], body["untouched"]) == (1, 0)
    assert len(body["months"]) == 12
    assert body["months"][-1] == {
        "start": "2026-10-01",
        "lanes": {"green": 1, "yellow": 0, "red": 0},
    }
    assert body["duration"] == {"count": 1, "median_ms": 60000.0, "p90_ms": 60000.0}
    assert body["steps"] == [{"node": "receive", "count": 1, "median_ms": 2000.0, "p90_ms": 2000.0}]
    assert body["fields"] == [
        {
            "field": "contact",
            "name": None,
            "verdicts": {"taken": 1, "accepted": 0, "corrected": 0, "added": 0},
            "early": 0,
        }
    ]


async def test_channels_period_and_time_zone_are_chosen(api: Api) -> None:
    await seed(api)
    user = await api.user()
    query = "?channel=web&channel=migration&period=all&tz=Europe/Berlin"

    body = (await api.client.get(AUTOMATION + query, headers=auth(user))).json()

    assert (body["channels"], body["period"], body["since"]) == (
        ["migration", "web"],
        "all",
        None,
    )
    assert body["lanes"]["green"] == 2
    bad = await api.client.get(f"{AUTOMATION}?tz=Mars/Olympus", headers=auth(user))
    assert bad.status_code == 422
    assert (await api.client.get(f"{AUTOMATION}?period=1y", headers=auth(user))).status_code == 422


async def test_the_signals_hit_rates(api: Api) -> None:
    await seed(api)
    user = await api.user()

    body = (await api.client.get(f"{AUTOMATION}/signals", headers=auth(user))).json()

    assert body["signals"] == [
        {"field": "contact", "signal": "signal_llm", "hits": 1, "misses": 0, "decided": 1}
    ]


async def test_signed_out_nobody_sees_them(api: Api) -> None:
    assert (await api.client.get(AUTOMATION)).status_code == 401


async def test_admins_see_the_holders_against_their_decisions(api: Api) -> None:
    user, admin = await api.user(), await api.admin()
    refused = await api.client.get(f"{PREFIX}/automation/holders", headers=auth(user))
    assert refused.status_code == 403
    response = await api.client.get(f"{PREFIX}/automation/holders", headers=auth(admin))
    assert response.status_code == 200, response.text
    body = response.json()
    zero = {"right": 0, "learned_rejected": 0, "refused_confirmed": 0, "unclear": 0, "unread": 0}
    assert [item["kind"] for item in body["kinds"]] == [
        "creditor_id",
        "email_domain",
        "iban",
        "vat_id",
    ]
    assert body["recommendation"] == zero  # nothing decided yet
