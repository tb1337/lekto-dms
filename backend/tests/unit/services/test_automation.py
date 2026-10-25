"""The numbers of the page "System" about the automation (`services.automation`)."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from lekto.core.domain.classification import (
    CONTACT,
    DOCUMENT_DATE,
    SPACE,
    TOPIC,
    field_key,
)
from lekto.core.domain.documents import Channel, Document
from lekto.core.domain.fields import FieldDefinition, FieldType
from lekto.core.domain.first_runs import Decision, FieldVerdict, FirstRun, Verdict
from lekto.core.domain.ids import FieldId, new_id
from lekto.core.domain.pipeline import Lane, Node
from lekto.core.domain.users import User
from lekto.core.services.automation import AutomationService, Flow, Month, Period, Times
from tests import builders
from tests.builders import FAILED, NOW, UNCERTAIN
from tests.unit.services.support import World

SECOND = timedelta(seconds=1)
BERLIN = ZoneInfo("Europe/Berlin")
# NOW is 6 October 2026, 12:00 UTC.


async def seed(
    world: World,
    owner: User,
    *,
    lane: Lane = Lane.GREEN,
    channel: Channel = Channel.WEB,
    stopped: datetime = NOW - timedelta(days=1),
    took: timedelta = 60 * SECOND,
    steps: dict[Node, timedelta] | None = None,
    verdicts: dict[str, Verdict] | None = None,
    decided: datetime | None = None,
    signals: dict[str, dict[Node, bool]] | None = None,
) -> Document:
    space = await world.personal_space(owner)
    results = {Lane.YELLOW: {Node.JUDGE: UNCERTAIN}, Lane.RED: {Node.OCR: FAILED}}.get(lane, {})
    document = builders.processed(owner, space, results)
    document.channel = channel
    async with world.uow() as uow:
        await uow.documents.add(document)
        await uow.processing_facts.add_first_run(
            FirstRun(
                document_id=document.id,
                started_at=stopped - took,
                stopped_at=stopped,
                steps={Node.RECEIVE: SECOND, Node.OCR: 10 * SECOND} if steps is None else steps,
            )
        )
        await uow.processing_facts.add_verdicts(
            [
                FieldVerdict(
                    document_id=document.id,
                    field=field,
                    verdict=verdict,
                    decided_at=decided or stopped + timedelta(hours=1),
                    decision=Decision.INBOX,
                    signals=(signals or {}).get(field, {}),
                )
                for field, verdict in (verdicts or {}).items()
            ]
        )
        await uow.commit()
    return document


def service(world: World) -> AutomationService:
    return AutomationService(world.uow, world.clock)


async def test_the_report_counts_lanes_flow_and_who_decided(world: World) -> None:
    owner = await world.user()
    await seed(world, owner)
    await seed(world, owner, verdicts={CONTACT: Verdict.TAKEN})
    await seed(world, owner, lane=Lane.YELLOW, verdicts={CONTACT: Verdict.ACCEPTED})
    await seed(world, owner, lane=Lane.RED)
    await seed(world, owner, channel=Channel.MIGRATION)  # not by default

    report = await service(world).report(owner.id, zone=UTC)

    assert report.channels == {Channel.WEB, Channel.API}
    assert report.lanes == {Lane.GREEN: 2, Lane.YELLOW: 1, Lane.RED: 1}
    assert report.flow == (
        Flow(Lane.GREEN, Lane.GREEN, 2),
        Flow(Lane.YELLOW, Lane.YELLOW, 1),
        Flow(Lane.RED, Lane.RED, 1),
    )
    assert (report.decided, report.untouched) == (2, 1)
    every = await service(world).report(
        owner.id, channels={Channel.WEB, Channel.MIGRATION}, zone=UTC
    )
    assert every.lanes[Lane.GREEN] == 3


async def test_times_are_median_and_p90_per_document_and_step(world: World) -> None:
    owner = await world.user()
    for seconds in (10, 20, 30, 40, 1000):
        await seed(
            world,
            owner,
            took=seconds * SECOND,
            steps={Node.RECEIVE: SECOND, Node.SIGNAL_LLM: seconds * SECOND},
        )

    report = await service(world).report(owner.id, zone=UTC)

    assert report.duration == Times(5, 30 * SECOND, 1000 * SECOND)
    assert report.work == Times(5, 31 * SECOND, 1001 * SECOND)
    assert list(report.steps) == [Node.RECEIVE, Node.SIGNAL_LLM]  # graph order
    assert report.steps[Node.SIGNAL_LLM] == Times(5, 30 * SECOND, 1000 * SECOND)


async def test_no_documents_no_times(world: World) -> None:
    owner = await world.user()
    report = await service(world).report(owner.id, zone=UTC)
    assert report.duration == Times(0, None, None)
    assert report.lanes == {Lane.GREEN: 0, Lane.YELLOW: 0, Lane.RED: 0}
    assert len(report.months) == 12


async def test_the_months_begin_in_the_viewers_time_zone(world: World) -> None:
    owner = await world.user()
    # 1 October, 00:30 in Berlin: still September in UTC.
    await seed(world, owner, stopped=datetime(2026, 9, 30, 22, 30, tzinfo=UTC))
    await seed(world, owner, lane=Lane.YELLOW, stopped=datetime(2026, 8, 15, tzinfo=UTC))

    report = await service(world).report(owner.id, zone=BERLIN)

    assert [month.start for month in report.months][-3:] == [
        date(2026, 8, 1),
        date(2026, 9, 1),
        date(2026, 10, 1),
    ]
    assert report.months[-1] == Month(date(2026, 10, 1), {Lane.GREEN: 1})
    assert report.months[-3] == Month(date(2026, 8, 1), {Lane.YELLOW: 1})
    assert report.months[0].start == date(2025, 11, 1)
    assert report.since == datetime(2025, 10, 31, 23, tzinfo=UTC)  # 1 November in Berlin


async def test_the_period_limits_what_is_counted(world: World) -> None:
    owner = await world.user()
    await seed(world, owner, stopped=NOW - timedelta(days=10))
    await seed(world, owner, stopped=NOW - timedelta(days=100))
    await seed(world, owner, stopped=NOW - timedelta(days=800))

    counted = {
        period: sum((await service(world).report(owner.id, period=period, zone=UTC)).lanes.values())
        for period in Period
    }

    assert counted == {Period.DAYS_30: 1, Period.MONTHS_12: 2, Period.ALL: 3}
    every = await service(world).report(owner.id, period=Period.ALL, zone=UTC)
    assert every.months[0].start == date(2024, 7, 1)  # from the first month with documents
    assert every.since is None


async def test_verdicts_per_field_with_custom_fields_by_name(world: World) -> None:
    owner = await world.user()
    amount = FieldDefinition.create(name="Betrag", data_type=FieldType.AMOUNT, now=NOW)
    async with world.uow() as uow:
        await uow.fields.add(amount)
        await uow.commit()
    gone = field_key(FieldId(new_id()))
    await seed(
        world,
        owner,
        verdicts={
            field_key(amount.id): Verdict.ADDED,
            CONTACT: Verdict.TAKEN,
            gone: Verdict.TAKEN,
            DOCUMENT_DATE: Verdict.EARLY,
        },
    )
    await seed(world, owner, verdicts={CONTACT: Verdict.CORRECTED, SPACE: Verdict.TAKEN})

    report = await service(world).report(owner.id, zone=UTC)

    fields = {item.field: item for item in report.fields}
    assert list(fields) == [CONTACT, DOCUMENT_DATE, SPACE, field_key(amount.id)]
    assert fields[CONTACT].counts == {Verdict.TAKEN: 1, Verdict.CORRECTED: 1}
    assert fields[CONTACT].decided == 2
    assert (fields[DOCUMENT_DATE].counts, fields[DOCUMENT_DATE].early) == ({}, 1)
    assert fields[field_key(amount.id)].name == "Betrag"


async def test_signals_hit_and_the_language_model_reads_the_date(world: World) -> None:
    owner = await world.user()
    llm, classifier = Node.SIGNAL_LLM, Node.SIGNAL_CLASSIFIER
    await seed(
        world,
        owner,
        verdicts={CONTACT: Verdict.TAKEN, DOCUMENT_DATE: Verdict.TAKEN, TOPIC: Verdict.ADDED},
        signals={CONTACT: {llm: True, classifier: False}},
    )
    await seed(
        world,
        owner,
        verdicts={CONTACT: Verdict.CORRECTED, DOCUMENT_DATE: Verdict.CORRECTED},
        signals={CONTACT: {llm: False}},
    )
    await seed(world, owner, verdicts={DOCUMENT_DATE: Verdict.ADDED, CONTACT: Verdict.ADDED})

    report = await service(world).signals(owner.id, zone=UTC)

    found = {(item.field, item.signal): item for item in report.signals}
    assert list(found) == [(CONTACT, llm), (CONTACT, classifier), (DOCUMENT_DATE, llm)]
    assert (found[CONTACT, llm].hits, found[CONTACT, llm].misses) == (1, 1)
    assert found[CONTACT, llm].decided == 3
    assert (found[DOCUMENT_DATE, llm].hits, found[DOCUMENT_DATE, llm].misses) == (1, 1)


async def test_a_report_is_kept_for_a_minute(world: World) -> None:
    owner = await world.user()
    automation = service(world)
    await seed(world, owner)
    assert (await automation.report(owner.id, zone=UTC)).lanes[Lane.GREEN] == 1

    await seed(world, owner)
    assert (await automation.report(owner.id, zone=UTC)).lanes[Lane.GREEN] == 1
    assert (await automation.report(owner.id, zone=BERLIN)).lanes[Lane.GREEN] == 2  # another
    world.clock.advance(timedelta(minutes=1))
    assert (await automation.report(owner.id, zone=UTC)).lanes[Lane.GREEN] == 2
