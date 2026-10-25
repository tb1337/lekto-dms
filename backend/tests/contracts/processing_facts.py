"""Contract of the facts of processing (`ProcessingFacts`): the first runs and verdicts, kept
once, and the statistics over them."""

from datetime import timedelta

import pytest

from lekto.core.domain.classification import CONTACT, DOCUMENT_DATE, SPACE, TOPIC
from lekto.core.domain.documents import Channel, Document
from lekto.core.domain.errors import ConflictError
from lekto.core.domain.first_runs import Decision, FieldVerdict, FirstRun, Verdict
from lekto.core.domain.ids import DocumentId, new_id
from lekto.core.domain.pipeline import Lane, Node
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import User
from lekto.core.ports.repository import FactsScope, LaneCount, SignalCount
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from tests import builders
from tests.builders import FAILED, NOW, UNCERTAIN
from tests.contracts.unit_of_work import owner_with_space

SECOND = timedelta(seconds=1)
MICROSECOND = timedelta(microseconds=1)
MICROS = SECOND // MICROSECOND  # a second in microseconds
DAY = timedelta(days=1)


def first_run(
    document: Document,
    *,
    stopped: timedelta = 10 * SECOND,
    steps: dict[Node, timedelta] | None = None,
) -> FirstRun:
    return FirstRun(
        document_id=document.id,
        started_at=NOW,
        stopped_at=NOW + stopped,
        steps={Node.RECEIVE: SECOND, Node.OCR: 4 * SECOND} if steps is None else steps,
    )


def verdict(
    document: Document,
    field: str = CONTACT,
    kind: Verdict = Verdict.TAKEN,
    *,
    at: timedelta = timedelta(0),
    signals: dict[Node, bool] | None = None,
) -> FieldVerdict:
    return FieldVerdict(
        document_id=document.id,
        field=field,
        verdict=kind,
        decided_at=NOW + at,
        decision=Decision.INBOX,
        signals={} if signals is None else signals,
    )


async def store(uow_factory: UnitOfWorkFactory, *documents: Document) -> None:
    async with uow_factory() as uow:
        for document in documents:
            await uow.documents.add(document)
        await uow.commit()


def green(owner: User, space: Space, channel: Channel = Channel.WEB) -> Document:
    document = builders.processed(owner, space)
    document.channel = channel
    return document


def yellow(owner: User, space: Space, channel: Channel = Channel.WEB) -> Document:
    document = builders.processed(owner, space, {Node.JUDGE: UNCERTAIN})
    document.channel = channel
    return document


def confirmed(document: Document) -> Document:
    """`document` confirmed out of yellow or red and processed to green."""
    document.confirm(Node.APPLY_RULES, NOW)
    builders.run_pipeline(document)
    document.pull_events()
    return document


class ProcessingFactsContract:
    async def test_a_first_run_is_kept_once(self, uow_factory: UnitOfWorkFactory) -> None:
        owner, space = await owner_with_space(uow_factory)
        document = green(owner, space)
        await store(uow_factory, document)
        run = first_run(document, steps={Node.RECEIVE: SECOND, Node.SIGNAL_LLM: 1500 * SECOND})

        async with uow_factory() as uow:
            await uow.processing_facts.add_first_run(run)
            assert await uow.processing_facts.first_run(document.id) == run  # its own write
            await uow.commit()
        async with uow_factory() as uow:
            await uow.processing_facts.add_first_run(first_run(document, stopped=99 * SECOND))
            await uow.commit()

        async with uow_factory() as uow:
            assert await uow.processing_facts.first_run(document.id) == run
            assert await uow.processing_facts.first_run(DocumentId(new_id())) is None

    async def test_a_field_keeps_its_first_verdict(self, uow_factory: UnitOfWorkFactory) -> None:
        owner, space = await owner_with_space(uow_factory)
        document = yellow(owner, space)
        await store(uow_factory, document)
        first = [
            verdict(document, CONTACT, Verdict.ACCEPTED, signals={Node.SIGNAL_LLM: True}),
            verdict(document, DOCUMENT_DATE, Verdict.EARLY),
        ]
        later = [
            verdict(document, CONTACT, Verdict.CORRECTED, at=DAY),
            verdict(document, TOPIC, Verdict.ADDED, at=DAY),
        ]

        async with uow_factory() as uow:
            await uow.processing_facts.add_verdicts(first)
            await uow.commit()
        async with uow_factory() as uow:
            await uow.processing_facts.add_verdicts(later)
            await uow.processing_facts.add_verdicts([])
            await uow.commit()

        async with uow_factory() as uow:
            assert await uow.processing_facts.verdicts(document.id) == [
                first[0],
                first[1],
                later[1],
            ]

    async def test_facts_are_stored_on_commit_only(self, uow_factory: UnitOfWorkFactory) -> None:
        owner, space = await owner_with_space(uow_factory)
        document = green(owner, space)
        await store(uow_factory, document)
        async with uow_factory() as uow:
            await uow.processing_facts.add_first_run(first_run(document))
            await uow.processing_facts.add_verdicts([verdict(document)])
            await uow.rollback()
        async with uow_factory() as uow:
            assert await uow.processing_facts.first_run(document.id) is None
            assert await uow.processing_facts.verdicts(document.id) == []

    async def test_facts_need_their_document(self, uow_factory: UnitOfWorkFactory) -> None:
        owner, space = await owner_with_space(uow_factory)
        missing = green(owner, space)
        with pytest.raises(ConflictError):
            async with uow_factory() as uow:
                await uow.processing_facts.add_first_run(first_run(missing))
                await uow.commit()
        with pytest.raises(ConflictError):
            async with uow_factory() as uow:
                await uow.processing_facts.add_verdicts([verdict(missing)])
                await uow.commit()

    async def test_facts_go_with_their_document(self, uow_factory: UnitOfWorkFactory) -> None:
        owner, space = await owner_with_space(uow_factory)
        document = green(owner, space)
        await store(uow_factory, document)
        async with uow_factory() as uow:
            await uow.processing_facts.add_first_run(first_run(document))
            await uow.processing_facts.add_verdicts([verdict(document)])
            await uow.commit()
        async with uow_factory() as uow:
            await uow.documents.remove(document.id)
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.processing_facts.first_run(document.id) is None
            assert await uow.processing_facts.verdicts(document.id) == []
            assert await uow.processing_facts.lane_counts(FactsScope()) == []

    async def test_lanes_count_the_first_lane_the_lane_now_and_decided(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner, space = await owner_with_space(uow_factory)
        documents = [
            green(owner, space),
            green(owner, space),
            confirmed(yellow(owner, space)),
            yellow(owner, space),
            builders.processed(owner, space, {Node.OCR: FAILED}),
        ]
        untold = green(owner, space)  # its first run is not known
        untold.first_lane = None
        without = green(owner, space)  # no first run kept
        await store(uow_factory, *documents, untold, without)
        async with uow_factory() as uow:
            for document in [*documents, untold]:
                await uow.processing_facts.add_first_run(first_run(document))
            await uow.processing_facts.add_verdicts(
                [verdict(documents[1]), verdict(documents[2]), verdict(documents[2], TOPIC)]
            )
            await uow.commit()

        async with uow_factory() as uow:
            counts = await uow.processing_facts.lane_counts(FactsScope())

        assert sorted(counts, key=_lane_key) == sorted(
            [
                LaneCount(first_lane=Lane.GREEN, lane=Lane.GREEN, decided=False, count=1),
                LaneCount(first_lane=Lane.GREEN, lane=Lane.GREEN, decided=True, count=1),
                LaneCount(first_lane=Lane.YELLOW, lane=Lane.GREEN, decided=True, count=1),
                LaneCount(first_lane=Lane.YELLOW, lane=Lane.YELLOW, decided=False, count=1),
                LaneCount(first_lane=Lane.RED, lane=Lane.RED, decided=False, count=1),
            ],
            key=_lane_key,
        )

    async def test_a_document_being_processed_lies_in_no_lane(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner, space = await owner_with_space(uow_factory)
        document = yellow(owner, space)
        document.confirm(Node.APPLY_RULES, NOW)
        document.pull_events()
        await store(uow_factory, document)
        async with uow_factory() as uow:
            await uow.processing_facts.add_first_run(first_run(document))
            await uow.commit()
        async with uow_factory() as uow:
            assert await uow.processing_facts.lane_counts(FactsScope()) == [
                LaneCount(first_lane=Lane.YELLOW, lane=None, decided=False, count=1)
            ]

    async def test_the_scope_selects_channels_and_when_the_first_run_stopped(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner, space = await owner_with_space(uow_factory)
        web, api, migrated, old = (
            green(owner, space, Channel.WEB),
            yellow(owner, space, Channel.API),
            green(owner, space, Channel.MIGRATION),
            green(owner, space, Channel.WEB),
        )
        await store(uow_factory, web, api, migrated, old)
        async with uow_factory() as uow:
            for document in (web, api, migrated):
                await uow.processing_facts.add_first_run(first_run(document, stopped=DAY))
            await uow.processing_facts.add_first_run(first_run(old, stopped=SECOND))
            await uow.commit()

        scope = FactsScope(channels=frozenset({Channel.WEB, Channel.API}), since=NOW + DAY)
        async with uow_factory() as uow:
            counts = await uow.processing_facts.lane_counts(scope)
            times = await uow.processing_facts.run_times(scope)
            every = await uow.processing_facts.run_times(FactsScope())

        assert sorted(counts, key=_lane_key) == [
            LaneCount(first_lane=Lane.GREEN, lane=Lane.GREEN, decided=False, count=1),
            LaneCount(first_lane=Lane.YELLOW, lane=Lane.YELLOW, decided=False, count=1),
        ]
        assert sorted(times.durations) == [DAY // MICROSECOND] * 2
        assert len(every.durations) == 4

    async def test_lanes_by_period_count_from_each_start_to_the_next(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner, space = await owner_with_space(uow_factory)
        stops = {
            "before": -DAY,
            "first": timedelta(0),  # a stop at the start belongs to its period
            "first_late": DAY - SECOND,
            "second": DAY,
            "open": 40 * DAY,
        }
        documents = {name: green(owner, space) for name in stops}
        documents["second"] = yellow(owner, space)
        await store(uow_factory, *documents.values())
        async with uow_factory() as uow:
            for name, at in stops.items():
                run = FirstRun(
                    document_id=documents[name].id,
                    started_at=NOW + at - SECOND,
                    stopped_at=NOW + at,
                )
                await uow.processing_facts.add_first_run(run)
            await uow.commit()

        async with uow_factory() as uow:
            periods = await uow.processing_facts.lanes_by_period(
                FactsScope(), [NOW, NOW + DAY, NOW + 2 * DAY]
            )
            assert await uow.processing_facts.lanes_by_period(FactsScope(), []) == []

        assert periods == [{Lane.GREEN: 2}, {Lane.YELLOW: 1}, {Lane.GREEN: 1}]

    async def test_run_times_give_each_documents_duration_work_and_steps(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner, space = await owner_with_space(uow_factory)
        quick, slow = green(owner, space), green(owner, space)
        await store(uow_factory, quick, slow)
        async with uow_factory() as uow:
            await uow.processing_facts.add_first_run(
                first_run(quick, stopped=10 * SECOND, steps={Node.RECEIVE: SECOND})
            )
            await uow.processing_facts.add_first_run(
                first_run(
                    slow,
                    stopped=600 * SECOND,
                    steps={Node.RECEIVE: 2 * SECOND, Node.SIGNAL_LLM: 30 * SECOND},
                )
            )
            await uow.commit()

        async with uow_factory() as uow:
            times = await uow.processing_facts.run_times(FactsScope())

        assert sorted(times.durations) == [10 * MICROS, 600 * MICROS]  # microseconds
        assert sorted(times.work) == [MICROS, 32 * MICROS]
        assert {node: sorted(steps) for node, steps in times.steps.items()} == {
            Node.RECEIVE: [MICROS, 2 * MICROS],
            Node.SIGNAL_LLM: [30 * MICROS],
        }

    async def test_verdicts_count_by_field_and_kind_in_scope(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner, space = await owner_with_space(uow_factory)
        one, two = green(owner, space), yellow(owner, space)
        migrated = green(owner, space, Channel.MIGRATION)
        await store(uow_factory, one, two, migrated)
        async with uow_factory() as uow:
            await uow.processing_facts.add_verdicts(
                [
                    verdict(one, CONTACT, Verdict.TAKEN, at=DAY),
                    verdict(one, SPACE, Verdict.TAKEN, at=DAY),
                    verdict(two, CONTACT, Verdict.TAKEN, at=DAY),
                    verdict(two, SPACE, Verdict.CORRECTED, at=DAY),
                    verdict(two, TOPIC, Verdict.ADDED, at=timedelta(0)),
                    verdict(migrated, CONTACT, Verdict.CORRECTED, at=DAY),
                ]
            )
            await uow.commit()

        scope = FactsScope(channels=frozenset({Channel.WEB}), since=NOW + DAY)
        async with uow_factory() as uow:
            counts = await uow.processing_facts.verdict_counts(scope)
            every = await uow.processing_facts.verdict_counts(FactsScope())

        assert counts == {
            (CONTACT, Verdict.TAKEN): 2,
            (SPACE, Verdict.TAKEN): 1,
            (SPACE, Verdict.CORRECTED): 1,
        }
        assert every[CONTACT, Verdict.CORRECTED] == 1
        assert every[TOPIC, Verdict.ADDED] == 1

    async def test_signals_count_hits_and_misses_per_field(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        owner, space = await owner_with_space(uow_factory)
        one, two, three = (green(owner, space) for _ in range(3))
        await store(uow_factory, one, two, three)
        llm, classifier, facts = Node.SIGNAL_LLM, Node.SIGNAL_CLASSIFIER, Node.SIGNAL_FACTS
        async with uow_factory() as uow:
            await uow.processing_facts.add_verdicts(
                [
                    verdict(one, CONTACT, signals={llm: True, classifier: False}),
                    verdict(two, CONTACT, signals={llm: True, facts: True}),
                    verdict(three, CONTACT, Verdict.CORRECTED, signals={llm: False}),
                    verdict(one, SPACE, signals={classifier: True}),
                    verdict(two, SPACE),
                ]
            )
            await uow.commit()

        async with uow_factory() as uow:
            counts = await uow.processing_facts.signal_counts(FactsScope())

        assert counts == {
            (CONTACT, llm): SignalCount(hits=2, misses=1),
            (CONTACT, classifier): SignalCount(hits=0, misses=1),
            (CONTACT, facts): SignalCount(hits=1, misses=0),
            (SPACE, classifier): SignalCount(hits=1, misses=0),
        }


def _lane_key(count: LaneCount) -> tuple[str, str, bool, int]:
    return (
        count.first_lane.value,
        "" if count.lane is None else count.lane.value,
        count.decided,
        count.count,
    )
