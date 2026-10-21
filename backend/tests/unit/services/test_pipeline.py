import asyncio
import dataclasses
from datetime import timedelta
from uuid import UUID

import pytest

from lekto.adapters.outbound.memory import MemoryObjectStore
from lekto.core.domain.documents import Document, DocumentChanges, Sha256
from lekto.core.domain.errors import (
    DuplicateDocumentError,
    InvalidTransitionError,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableDocumentError,
    UnsupportedMediaTypeError,
)
from lekto.core.domain.events import (
    DocumentEvent,
    DocumentFiled,
    DocumentReceived,
    LaneChanged,
    NodeCompleted,
    NodeDeferred,
    NodeStarted,
)
from lekto.core.domain.ids import ContactId, TagId
from lekto.core.domain.jobs import JobStatus, RetryPolicy
from lekto.core.domain.master_data import Tag
from lekto.core.domain.pipeline import (
    CURRENT_SIGNALS,
    NODES,
    Lane,
    Node,
    NodeResult,
    NodeState,
    NodeStatus,
    Outcome,
    ProcessingStatus,
)
from lekto.core.domain.spaces import SpaceRole
from lekto.core.domain.users import Role, User
from lekto.core.services.objects import original_key
from lekto.core.services.pipeline import (
    CATCH_UP_JOB,
    NODE_JOB,
    REPARSE_JOB,
    MetadataResult,
    PipelineService,
)
from tests import builders
from tests.builders import FAILED, NOW, SAMPLES, UNCERTAIN, PlaceholderNode, Returns, incoming
from tests.unit.services.support import Raises, World

PDF = b"%PDF-1.7 invoice"


def postpone(world: World, node: Node, by: timedelta) -> None:
    """Let the job of `node` run later, so a test runs the other due jobs first: the jobs of
    `ocr` and `pages` are due at the same moment, in no fixed order."""
    for id, job in world.database.jobs.items():
        if job.payload.get("node") == node.value:
            world.database.jobs[id] = dataclasses.replace(job, run_at=job.run_at + by)


def in_graph_order(nodes: list[Node]) -> bool:
    """True if every node comes after the nodes it needs."""
    return all(
        needed in nodes[:position]
        for position, node in enumerate(nodes)
        for needed in node.requires
    )


async def receive(world: World, pipeline: PipelineService | None = None) -> tuple[User, Document]:
    owner = await world.user()
    document = await (pipeline or world.pipeline()).receive(
        owner.id, incoming(PDF), filename="invoice.pdf"
    )
    return owner, document


async def test_receive_stores_original_document_events_and_job(world: World) -> None:
    owner = await world.user()
    document = await world.pipeline().receive(owner.id, incoming(PDF), filename="invoice.pdf")
    assert document.sha256 == Sha256.of(PDF)
    assert await world.object_store.get(original_key(document.sha256)) == PDF
    assert document.space_id == (await world.personal_space(owner)).id
    assert document.processing.due() == (Node.OCR, Node.PAGES)
    assert document.lane is None

    assert world.event_types() == [DocumentReceived.type, NodeCompleted.type]
    async with world.uow() as uow:
        assert await uow.documents.get(document.id) == document
        (entry,) = await uow.processing_log.list_for(document.id)
        assert (entry.node, entry.run, entry.result.outcome) == (Node.RECEIVE, 1, Outcome.OK)
        assert entry.result.output == {
            "sha256": document.sha256.hex,
            "size": len(PDF),
            "media_type": "application/pdf",
        }
        assert entry.pipeline_version == "test"
        first = await uow.jobs.claim(now=NOW, lease=timedelta(minutes=1))
        second = await uow.jobs.claim(now=NOW, lease=timedelta(minutes=1))
    assert first is not None and second is not None
    assert {first.kind, second.kind} == {NODE_JOB}
    payloads = sorted([first.payload, second.payload], key=lambda payload: str(payload["node"]))
    assert payloads == [
        {"document_id": str(document.id), "node": Node.OCR.value, "run": 1},
        {"document_id": str(document.id), "node": Node.PAGES.value, "run": 1},
    ]


async def test_pipeline_runs_to_green(world: World) -> None:
    owner = await world.user()
    document = await world.pipeline().receive(owner.id, incoming(PDF), filename="invoice.pdf")
    assert await world.drain() == len(NODES) - 1
    stored = await world.documents.get(owner.id, document.id)
    assert stored.processing.status is ProcessingStatus.COMPLETED
    assert stored.lane is Lane.GREEN
    assert all(state.status is NodeStatus.DONE for state in stored.processing.nodes.values())

    events = world.events()
    assert isinstance(events[0], DocumentReceived)
    started = [event.node for event in events if isinstance(event, NodeStarted)]
    completed = [event.node for event in events if isinstance(event, NodeCompleted)]
    assert set(started) == set(NODES[1:]) and len(started) == len(NODES) - 1
    assert in_graph_order(completed)
    assert isinstance(events[-2], DocumentFiled)
    assert isinstance(events[-1], LaneChanged) and events[-1].new is Lane.GREEN
    log = await world.documents.processing_log(owner.id, document.id)
    assert in_graph_order([entry.node for entry in log])
    assert len(world.database.jobs) == len(NODES) - 1
    assert all(job.status is JobStatus.DONE for job in world.database.jobs.values())


async def test_a_running_node_is_visible_until_its_result_is_stored(world: World) -> None:
    owner, document = await receive(world)
    postpone(world, Node.PAGES, timedelta(hours=1))
    seen: list[tuple[Node, ...]] = []

    class Looks:
        async def run(self, document: Document) -> NodeResult:
            stored = await world.documents.get(owner.id, document.id)
            seen.append(stored.processing.running())
            assert stored.processing.nodes[Node.OCR].started_at == NOW
            return builders.OK

    pipeline = world.pipeline({Node.OCR: Looks()})
    assert await pipeline.run_next_job()
    assert seen == [(Node.OCR,)]
    assert world.event_types()[-2:] == [NodeStarted.type, NodeCompleted.type]
    stored = await world.documents.get(owner.id, document.id)
    assert stored.processing.nodes[Node.OCR] == NodeState(
        status=NodeStatus.DONE, outcome=Outcome.OK, started_at=NOW, finished_at=NOW
    )
    assert stored.processing.running() == ()
    assert stored.processing.due() == (Node.PAGES, Node.PARSE)


async def test_uncertain_step_ends_yellow(world: World) -> None:
    pipeline = world.pipeline({Node.JUDGE: Returns(UNCERTAIN)})
    owner, document = await receive(world, pipeline)
    await world.drain(pipeline)
    stored = await world.documents.get(owner.id, document.id)
    assert stored.lane is Lane.YELLOW
    log = await world.documents.processing_log(owner.id, stored.id)
    classify = next(entry for entry in log if entry.node is Node.JUDGE)
    assert classify.result.reason == "new contact"


async def test_failed_result_stops_red(world: World) -> None:
    pipeline = world.pipeline({Node.PARSE: Returns(FAILED)})
    owner, document = await receive(world, pipeline)
    # The nodes after receiving, up to the one that fails.
    ran = Node.RECEIVE.successors | Node.PARSE.ancestors | {Node.PARSE}
    assert await world.drain(pipeline) == len(ran - {Node.RECEIVE})
    stored = await world.documents.get(owner.id, document.id)
    assert stored.lane is Lane.RED
    assert stored.processing.status is ProcessingStatus.FAILED
    assert stored.processing.failed() == (Node.PARSE,)
    # `pages` runs beside the text: done if its job came first, else dropped (jobs due at the
    # same time run in no fixed order; the next test covers the dropped node).
    assert stored.processing.outcome(Node.PAGES) in (Outcome.OK, None)


async def test_a_node_still_queued_after_a_failure_is_dropped_and_retried_later(
    world: World,
) -> None:
    pages = Returns(builders.OK)
    pipeline = world.pipeline({Node.OCR: Returns(FAILED), Node.PAGES: pages})
    owner, document = await receive(world, pipeline)
    postpone(world, Node.PAGES, timedelta(seconds=1))
    assert await pipeline.run_next_job()  # ocr fails
    world.clock.advance(timedelta(seconds=1))
    assert await pipeline.run_next_job()  # the pages job is stale now: nothing new starts
    assert pages.calls == 0
    stored = await world.documents.get(owner.id, document.id)
    assert stored.processing.nodes[Node.PAGES] == NodeState()
    assert all(job.status is not JobStatus.QUEUED for job in world.database.jobs.values())

    working = world.pipeline({Node.PAGES: pages})
    retried = (await working.retry(owner.id, document.id)).document
    assert retried.processing.due() == (Node.OCR, Node.PAGES)
    await world.drain(working)
    assert pages.calls == 1
    assert (await world.documents.get(owner.id, document.id)).lane is Lane.GREEN


async def test_exceptions_are_retried_with_backoff(world: World) -> None:
    flaky = Raises(times=2)
    pipeline = world.pipeline({Node.OCR: flaky})
    owner, document = await receive(world, pipeline)
    # The pages, and the first attempt of the OCR, which fails.
    assert await world.drain(pipeline) == len(Node.RECEIVE.successors)
    assert not await pipeline.run_next_job()  # waits 30 s
    waiting = await world.documents.get(owner.id, document.id)
    assert waiting.processing.nodes[Node.OCR] == NodeState()  # not shown as running meanwhile
    assert NodeDeferred.type in world.event_types()
    world.clock.advance(timedelta(seconds=30))
    assert await pipeline.run_next_job()  # attempt 2 fails
    world.clock.advance(timedelta(seconds=59))
    assert not await pipeline.run_next_job()  # waits 60 s
    world.clock.advance(timedelta(seconds=1))
    await world.drain(pipeline)  # attempt 3 succeeds, the rest follows
    assert flaky.calls == 3
    stored = await world.documents.get(owner.id, document.id)
    assert stored.lane is Lane.GREEN
    ocr_job = next(
        job for job in world.database.jobs.values() if job.payload["node"] == Node.OCR.value
    )
    assert (ocr_job.attempts, ocr_job.status) == (3, JobStatus.DONE)
    assert ocr_job.last_error == "OSError: scanner glitch"


async def test_exhausted_retries_end_red_and_retry_recovers(world: World) -> None:
    broken = Raises(times=3)
    pipeline = world.pipeline({Node.OCR: broken})
    owner, document = await receive(world, pipeline)
    for _ in range(3):
        assert await world.drain(pipeline)
        world.clock.advance(timedelta(minutes=5))
    assert not await pipeline.run_next_job()
    stored = await world.documents.get(owner.id, document.id)
    assert stored.lane is Lane.RED
    log = await world.documents.processing_log(owner.id, stored.id)
    assert log[-1].result.outcome is Outcome.FAILED
    assert log[-1].result.reason == "OSError: scanner glitch"
    ocr_job = next(
        job for job in world.database.jobs.values() if job.payload["node"] == Node.OCR.value
    )
    assert ocr_job.status is JobStatus.FAILED

    retried = (await pipeline.retry(owner.id, stored.id)).document
    assert retried.processing.run == 2
    assert retried.lane is None
    await world.drain(pipeline)
    stored = await world.documents.get(owner.id, stored.id)
    assert stored.lane is Lane.GREEN
    assert broken.calls == 4


async def test_skipped_pages_are_caught_up_on_without_a_new_run(world: World) -> None:
    owner, document = await receive(world)
    await world.drain()
    red = await world.pipeline({Node.PARSE: Returns(FAILED)}).receive(
        owner.id, incoming(b"%PDF-1.7 red"), filename="red.pdf"
    )
    await world.drain(world.pipeline({Node.PARSE: Returns(FAILED)}))
    processing = await world.pipeline().receive(owner.id, incoming(b"%PDF-1.7 p"), filename="p.pdf")
    async with world.uow() as uow:  # as revision 0010 leaves documents from before the node
        for id in (document.id, red.id, processing.id):
            stored = await uow.documents.get(id)
            stored.processing.nodes[Node.PAGES] = NodeState(status=NodeStatus.SKIPPED)
            await uow.documents.update(stored)
        await uow.commit()
    world.database.outbox.clear()

    pages = Returns(builders.OK)
    pipeline = world.pipeline({Node.PAGES: pages})
    assert await pipeline.catch_up(Node.PAGES) == 3  # also the one being processed
    assert await pipeline.catch_up(Node.PAGES) == 0  # queued already
    # And the processing one: every node after receiving, its pages job stale.
    assert await world.drain(pipeline) == 3 + len(Node.RECEIVE.descendants)
    assert pages.calls == 3
    caught_up = await world.documents.get(owner.id, processing.id)
    assert caught_up.lane is Lane.GREEN
    assert caught_up.processing.nodes[Node.PAGES].status is NodeStatus.DONE
    for id, lane, status in ((document.id, Lane.GREEN, "completed"), (red.id, Lane.RED, "failed")):
        stored = await world.documents.get(owner.id, id)
        assert (stored.lane, stored.processing.status.value, stored.processing.run) == (
            lane,
            status,
            1,
        )
        assert stored.processing.nodes[Node.PAGES].status is NodeStatus.DONE
        log = await world.documents.processing_log(owner.id, id)
        assert log[-1].node is Node.PAGES and log[-1].run == 1
    kinds = [job.kind for job in world.database.jobs.values() if job.status is JobStatus.DONE]
    assert kinds.count(CATCH_UP_JOB) == 3
    assert LaneChanged.type not in [
        event.type
        for event in world.events()
        if isinstance(event, DocumentEvent) and event.document_id in (document.id, red.id)
    ]


async def test_a_failed_catch_up_keeps_the_node_skipped_and_blocks_nothing(world: World) -> None:
    owner, document = await receive(world)
    await world.drain()
    async with world.uow() as uow:
        stored = await uow.documents.get(document.id)
        stored.processing.nodes[Node.PAGES] = NodeState(status=NodeStatus.SKIPPED)
        await uow.documents.update(stored)
        await uow.commit()
    pipeline = world.pipeline({Node.PAGES: Returns(FAILED)})
    assert await pipeline.catch_up(Node.PAGES) == 1
    await world.drain(pipeline)
    stored = await world.documents.get(owner.id, document.id)
    assert stored.processing.nodes[Node.PAGES] == NodeState(status=NodeStatus.SKIPPED)
    assert (stored.lane, stored.processing.status) == (Lane.GREEN, ProcessingStatus.COMPLETED)
    log = await world.documents.processing_log(owner.id, document.id)
    assert (log[-1].node, log[-1].result.outcome) == (Node.PAGES, Outcome.FAILED)
    (job,) = [job for job in world.database.jobs.values() if job.kind == CATCH_UP_JOB]
    assert job.status is JobStatus.FAILED
    assert await pipeline.catch_up(Node.PAGES) == 1  # tried again next time
    await pipeline.reprocess_from(owner.id, document.id, Node.JUDGE)  # not blocked


async def test_a_catch_up_job_is_stale_once_the_document_runs_again(world: World) -> None:
    owner, document = await receive(world)
    await world.drain()
    async with world.uow() as uow:
        stored = await uow.documents.get(document.id)
        stored.processing.nodes[Node.PAGES] = NodeState(status=NodeStatus.SKIPPED)
        await uow.documents.update(stored)
        await uow.commit()
    pages = Returns(builders.OK)
    pipeline = world.pipeline({Node.PAGES: pages})
    assert await pipeline.catch_up(Node.PAGES) == 1
    await pipeline.reprocess_from(owner.id, document.id, Node.JUDGE)  # run 2
    await world.drain(pipeline)
    assert pages.calls == 0
    stored = await world.documents.get(owner.id, document.id)
    assert stored.processing.nodes[Node.PAGES].status is NodeStatus.SKIPPED
    assert all(job.status is JobStatus.DONE for job in world.database.jobs.values())


async def test_the_text_is_read_again_beside_processing(world: World) -> None:
    """`reparse`: the parse node runs again for documents whose text was read and that are
    not being processed; their nodes, lane and run stay, the log gets the reading."""
    owner, document = await receive(world)
    await world.drain()
    red = await world.pipeline({Node.OCR: Returns(FAILED)}).receive(
        owner.id, incoming(b"%PDF-1.7 red"), filename="red.pdf"
    )
    await world.drain(world.pipeline({Node.OCR: Returns(FAILED)}))
    busy = await world.pipeline().receive(owner.id, incoming(b"%PDF-1.7 busy"), filename="b.pdf")
    world.database.outbox.clear()

    parse = Returns(builders.OK)
    pipeline = world.pipeline({Node.PARSE: parse})
    assert await pipeline.reparse() == 1  # neither the red one (no text) nor the busy one
    assert await pipeline.reparse() == 0  # queued already
    await world.drain(pipeline)
    assert parse.calls == 2  # the reading, and the busy document's own run
    stored = await world.documents.get(owner.id, document.id)
    assert (stored.lane, stored.processing.run) == (Lane.GREEN, 1)
    log = await world.documents.processing_log(owner.id, document.id)
    assert (log[-1].node, log[-1].run, log[-1].result.input.get("reparse")) == (Node.PARSE, 1, True)
    kinds = [job.kind for job in world.database.jobs.values() if job.status is JobStatus.DONE]
    assert kinds.count(REPARSE_JOB) == 1
    types = [
        event.type
        for event in world.events()
        if isinstance(event, DocumentEvent) and event.document_id == document.id
    ]
    assert types == [NodeCompleted.type]
    assert (await world.documents.get(owner.id, busy.id)).lane is Lane.GREEN
    assert (await world.documents.get(owner.id, red.id)).lane is Lane.RED


async def test_a_reading_is_stale_once_the_document_runs_again(world: World) -> None:
    owner, document = await receive(world)
    await world.drain()
    parse = Returns(builders.OK)
    pipeline = world.pipeline({Node.PARSE: parse})
    assert await pipeline.reparse() == 1
    await pipeline.reprocess_from(owner.id, document.id, Node.JUDGE)  # run 2
    await world.drain(pipeline)
    assert parse.calls == 0
    log = await world.documents.processing_log(owner.id, document.id)
    assert not any(entry.result.input.get("reparse") for entry in log)


async def test_only_admins_have_every_text_read_again(world: World) -> None:
    owner, _ = await receive(world)
    await world.drain()
    with pytest.raises(PermissionDeniedError):
        await world.pipeline().request_reparse(owner.id)
    admin = await world.user(role=Role.ADMIN)
    assert await world.pipeline().request_reparse(admin.id) == 1


async def test_reprocess_from_a_step(world: World) -> None:
    owner, document = await receive(world)
    await world.drain()
    world.database.outbox.clear()
    pipeline = world.pipeline({Node.FIELDS: Returns(UNCERTAIN)})
    await pipeline.reprocess_from(owner.id, document.id, Node.JUDGE)
    # The signals without a model call, judge, fields, rules; it waits before filing.
    again = CURRENT_SIGNALS | {Node.JUDGE} | Node.JUDGE.descendants - {Node.FILE}
    assert await world.drain(pipeline) == len(again)
    stored = await world.documents.get(owner.id, document.id)
    assert stored.lane is Lane.YELLOW
    assert stored.processing.status is ProcessingStatus.REVIEW
    assert stored.processing.run == 2
    lanes = [(e.old, e.new) for e in world.events() if isinstance(e, LaneChanged)]
    assert lanes == [(Lane.GREEN, None), (None, Lane.YELLOW)]


async def test_retry_and_reprocess_are_for_the_editors(world: World) -> None:
    owner, reader, editor = await world.user(), await world.user(), await world.user()
    shared = await world.spaces.create(owner.id, "Shared")
    await world.spaces.set_member(owner.id, shared.id, reader.id, SpaceRole.READ)
    await world.spaces.set_member(owner.id, shared.id, editor.id, SpaceRole.EDIT)
    document = await world.pipeline().receive(
        owner.id, incoming(PDF), filename="a.pdf", space=shared.id
    )
    await world.drain()
    with pytest.raises(PermissionDeniedError):
        await world.pipeline().reprocess_from(reader.id, document.id, Node.OCR)
    await world.pipeline().reprocess_from(editor.id, document.id, Node.OCR)
    await world.drain()
    stranger = await world.user()
    with pytest.raises(NotFoundError):
        await world.pipeline().reprocess_from(stranger.id, document.id, Node.OCR)
    with pytest.raises(InvalidTransitionError):
        await world.pipeline().retry(owner.id, document.id)


async def test_duplicates_are_rejected_in_the_spaces_of_the_uploader(world: World) -> None:
    """A file in a space the uploader is a member of, or in the target space, is a duplicate;
    one only in spaces they cannot see is not (variant a, Tobi to confirm)."""
    owner, document = await receive(world)
    with pytest.raises(DuplicateDocumentError) as info:
        await world.pipeline().receive(owner.id, incoming(PDF), filename="again.pdf")
    assert info.value.existing == document.id
    other = await world.user()
    copy = await world.pipeline().receive(other.id, incoming(PDF), filename="mine.pdf")
    assert copy.sha256 == document.sha256
    assert copy.uploaded_by == other.id
    # Once the other may read the owner's personal space, the file is theirs to see there.
    personal = await world.personal_space(owner)
    await world.spaces.set_member(owner.id, personal.id, other.id, SpaceRole.READ)
    third = await world.user()
    household = await world.spaces.create(third.id, "Household")
    await world.spaces.set_member(third.id, household.id, other.id, SpaceRole.EDIT)
    with pytest.raises(DuplicateDocumentError):
        await world.pipeline().receive(
            other.id, incoming(PDF), filename="again.pdf", space=household.id
        )


async def test_only_duplicates_the_uploader_can_read_count(world: World) -> None:
    """A reader sees only green documents: a copy not green yet in a space they read neither
    blocks their upload nor tells them its id; a green one does."""
    owner, reader = await world.user(), await world.user()
    personal = await world.personal_space(owner)
    green = builders.processed(owner, personal)
    green.sha256 = Sha256.of(b"%PDF-1.7 green")
    waiting = builders.document(owner, personal)
    waiting.sha256 = Sha256.of(b"%PDF-1.7 waiting")
    async with world.uow() as uow:
        await uow.documents.add(green)
        await uow.documents.add(waiting)
        await uow.commit()
    await world.spaces.set_member(owner.id, personal.id, reader.id, SpaceRole.READ)
    copy = await world.pipeline().receive(
        reader.id, incoming(b"%PDF-1.7 waiting"), filename="waiting.pdf"
    )
    assert copy.space_id == (await world.personal_space(reader)).id
    with pytest.raises(DuplicateDocumentError) as info:
        await world.pipeline().receive(reader.id, incoming(b"%PDF-1.7 green"), filename="g.pdf")
    assert info.value.existing == green.id


async def test_a_duplicate_in_the_target_is_named_only_to_who_reads_it(world: World) -> None:
    """The target space holds a file once; the caller learns which document holds it only if
    they may read it."""
    owner, editor = await world.user(), await world.user()
    shared = await world.spaces.create(owner.id, "Shared")
    await world.spaces.set_member(owner.id, shared.id, editor.id, SpaceRole.EDIT)
    held = builders.document(owner, shared)
    held.sha256 = Sha256.of(PDF)
    async with world.uow() as uow:
        await uow.documents.add(held)
        await uow.commit()
    admin = await world.user(role=Role.ADMIN)
    with pytest.raises(DuplicateDocumentError) as info:
        await world.pipeline().receive(
            admin.id, incoming(PDF), filename="a.pdf", space=shared.id, uploaded_by=editor.id
        )
    assert info.value.existing == held.id
    await world.spaces.set_member(owner.id, shared.id, editor.id, SpaceRole.READ)
    with pytest.raises(DuplicateDocumentError) as info:
        await world.pipeline().receive(
            admin.id, incoming(PDF), filename="a.pdf", space=shared.id, uploaded_by=editor.id
        )
    assert info.value.existing == held.id  # the admin reads it


async def test_receive_into_a_space_needs_edit_rights(world: World) -> None:
    owner, writer, reader = await world.user(), await world.user(), await world.user()
    shared = await world.spaces.create(owner.id, "Shared")
    await world.spaces.set_member(owner.id, shared.id, writer.id, SpaceRole.EDIT)
    await world.spaces.set_member(owner.id, shared.id, reader.id, SpaceRole.READ)
    document = await world.pipeline().receive(
        writer.id, incoming(PDF), filename="a.pdf", space=shared.id
    )
    assert (document.uploaded_by, document.space_id) == (writer.id, shared.id)
    plain = await world.pipeline().receive(writer.id, incoming(b"%PDF-1.7 own"), filename="o.pdf")
    assert plain.space_id == (await world.personal_space(writer)).id
    with pytest.raises(PermissionDeniedError):
        await world.pipeline().receive(
            reader.id, incoming(b"%PDF-1.7 other"), filename="b.pdf", space=shared.id
        )
    with pytest.raises(NotFoundError):
        await world.pipeline().receive(
            reader.id,
            incoming(b"%PDF-1.7 other"),
            filename="b.pdf",
            space=(await world.personal_space(owner)).id,
        )


async def test_stale_jobs_are_skipped(world: World) -> None:
    owner, document = await receive(world)
    await world.documents.delete(owner.id, document.id)
    calls = Returns(FAILED)
    pipeline = world.pipeline({Node.OCR: calls})
    assert await world.drain(pipeline) == len(Node.RECEIVE.successors)  # both stale
    assert calls.calls == 0
    nodes = [job for job in world.database.jobs.values() if job.kind == NODE_JOB]
    assert all(job.status is JobStatus.DONE for job in nodes)


async def crash(world: World) -> None:
    """A worker claims the next job and dies; its lease runs out."""
    async with world.uow() as uow:
        assert await uow.jobs.claim(now=world.clock.now(), lease=timedelta(minutes=10))
        await uow.commit()
    world.clock.advance(timedelta(minutes=10))


async def test_a_step_that_keeps_killing_the_worker_ends_red(world: World) -> None:
    owner, document = await receive(world)
    postpone(world, Node.PAGES, timedelta(hours=1))
    for _ in range(3):
        await crash(world)
    ocr = Returns(FAILED)
    pipeline = world.pipeline({Node.OCR: ocr})
    assert await pipeline.run_next_job()
    assert ocr.calls == 0
    stored = await world.documents.get(owner.id, document.id)
    assert stored.lane is Lane.RED
    log = await world.documents.processing_log(owner.id, document.id)
    assert log[-1].result.reason is not None and "ran out of time" in log[-1].result.reason
    assert not await pipeline.run_next_job()


async def test_a_worker_that_lost_its_claim_stores_nothing(world: World) -> None:
    owner, document = await receive(world)

    class Slow:
        """Runs longer than the lease; meanwhile another worker takes the job over."""

        async def run(self, document: Document) -> NodeResult:
            world.clock.advance(timedelta(minutes=11))
            async with world.uow() as uow:
                assert await uow.jobs.claim(now=world.clock.now(), lease=timedelta(minutes=10))
                await uow.commit()
            return FAILED

    postpone(world, Node.PAGES, timedelta(hours=1))
    assert await world.pipeline({Node.OCR: Slow()}).run_next_job()
    stored = await world.documents.get(owner.id, document.id)
    assert stored.processing.nodes[Node.OCR].status is NodeStatus.RUNNING
    assert stored.processing.outcome(Node.OCR) is None
    assert stored.lane is None
    (job,) = [job for job in world.database.jobs.values() if job.payload["node"] == Node.OCR.value]
    assert (job.status, job.attempts) == (JobStatus.RUNNING, 2)


async def test_invalid_job_payload_fails_the_job(world: World) -> None:
    async with world.uow() as uow:
        await uow.jobs.enqueue(NODE_JOB, {"node": Node.OCR.value}, run_at=world.clock.now())
        await uow.commit()
    assert await world.pipeline().run_next_job()
    (job,) = world.database.jobs.values()
    assert job.status is JobStatus.FAILED
    assert job.last_error is not None and job.last_error.startswith("invalid payload")


async def test_every_step_needs_an_executor(world: World) -> None:
    with pytest.raises(ValueError, match="no executor"):
        builders.pipeline_service(
            world.uow, world.clock, world.object_store, {Node.OCR: PlaceholderNode()}
        )


def test_retry_policy() -> None:
    policy = RetryPolicy(max_attempts=3, delay=timedelta(seconds=10))
    assert policy.next_run(1, NOW) == NOW + timedelta(seconds=10)
    assert policy.next_run(2, NOW) == NOW + timedelta(seconds=20)
    assert policy.next_run(3, NOW) is None
    capped = RetryPolicy(
        max_attempts=10, delay=timedelta(seconds=10), max_delay=timedelta(seconds=30)
    )
    assert [capped.next_run(n, NOW) for n in (2, 3, 4)] == [
        NOW + timedelta(seconds=20),
        NOW + timedelta(seconds=30),
        NOW + timedelta(seconds=30),
    ]


class Blocks:
    """Node executor that waits until cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(self, document: Document) -> NodeResult:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("not reached")


class Unprocessable:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, document: Document) -> NodeResult:
        self.calls += 1
        raise UnprocessableDocumentError("the PDF is encrypted")


async def test_an_unprocessable_document_fails_at_once(world: World) -> None:
    ocr = Unprocessable()
    pipeline = world.pipeline({Node.OCR: ocr})
    owner, document = await receive(world, pipeline)
    await world.drain(pipeline)
    stored = await world.documents.get(owner.id, document.id)
    assert stored.lane is Lane.RED
    assert ocr.calls == 1  # no automatic retry
    log = await world.documents.processing_log(owner.id, document.id)
    assert (log[-1].node, log[-1].result.reason) == (Node.OCR, "the PDF is encrypted")
    (job,) = [job for job in world.database.jobs.values() if job.payload["node"] == Node.OCR.value]
    assert job.status is JobStatus.FAILED


async def test_a_cancelled_step_releases_its_job_at_once(world: World) -> None:
    """Interruptions (the worker stops) do not use up the attempts of the retry policy."""
    blocking = Blocks()
    pipeline = world.pipeline({Node.OCR: blocking})
    owner, document = await receive(world, pipeline)
    postpone(world, Node.PAGES, timedelta(hours=1))
    for _ in range(5):  # more than RetryPolicy.max_attempts
        blocking.started.clear()
        task = asyncio.create_task(pipeline.run_next_job())
        await blocking.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    (job,) = [job for job in world.database.jobs.values() if job.payload["node"] == Node.OCR.value]
    assert (job.status, job.tries, job.run_at, job.last_error) == (
        JobStatus.QUEUED,
        0,
        world.clock.now(),
        "interrupted: the worker stopped",
    )
    await world.drain()  # another worker takes it over without waiting for the lease
    world.clock.advance(timedelta(hours=1))
    await world.drain()  # the pages
    assert (await world.documents.get(owner.id, document.id)).lane is Lane.GREEN


@pytest.mark.parametrize(
    ("sample", "media_type"),
    [("scan.pdf", "application/pdf"), ("photo.jpg", "image/jpeg")],
)
async def test_the_media_type_comes_from_the_content(
    world: World, sample: str, media_type: str
) -> None:
    owner = await world.user()
    document = await world.pipeline().receive(
        owner.id, incoming((SAMPLES / sample).read_bytes()), filename="named-wrongly.txt"
    )
    assert document.media_type == media_type
    assert world.object_store.content_type(original_key(document.sha256)) == media_type


async def test_an_unsupported_file_is_rejected_and_not_stored(world: World) -> None:
    owner = await world.user()
    file = incoming((SAMPLES / "unsupported.docx").read_bytes())
    with pytest.raises(UnsupportedMediaTypeError, match="unsupported file type"):
        await world.pipeline().receive(owner.id, file, filename="letter.pdf")
    assert not await world.object_store.exists(original_key(file.sha256))
    assert world.events() == []


async def test_a_stored_original_is_not_uploaded_again(world: World) -> None:
    first, second = await world.user(), await world.user()
    document = await world.pipeline().receive(first.id, incoming(PDF), filename="a.pdf")
    key = original_key(document.sha256)
    await world.object_store.put(key, b"%PDF-1.7 marker", content_type="application/pdf")
    await world.pipeline().receive(second.id, incoming(PDF), filename="b.pdf")
    assert await world.object_store.get(key) == b"%PDF-1.7 marker"


class VanishingStore(MemoryObjectStore):
    """Says an original exists at the first look, then it is gone: as if the files of a deleted
    document were removed right between the two looks of an upload."""

    def __init__(self) -> None:
        super().__init__()
        self.looks = 0

    async def exists(self, key: str) -> bool:
        self.looks += 1
        return self.looks == 1 or await super().exists(key)


async def test_an_upload_stores_the_original_again_if_it_vanished(world: World) -> None:
    world.object_store = VanishingStore()
    owner = await world.user()
    document = await world.pipeline().receive(owner.id, incoming(b"%PDF-1.7 x"), filename="x.pdf")
    assert await world.object_store.get(original_key(document.sha256)) == b"%PDF-1.7 x"


class Changes:
    """Classifies with a metadata change."""

    def __init__(self, changes: DocumentChanges, add_tags: frozenset[TagId] = frozenset()) -> None:
        self.changes = changes
        self.add_tags = add_tags

    async def run(self, document: Document) -> MetadataResult:
        return MetadataResult(NodeResult(outcome=Outcome.OK), self.changes, self.add_tags)


async def test_a_step_changes_metadata_with_its_result(world: World) -> None:
    tag = Tag.create(name="Strom", now=NOW)
    async with world.uow() as uow:
        await uow.tags.add(tag)
        await uow.commit()
    changes = DocumentChanges(tag_ids=frozenset({tag.id}))
    pipeline = world.pipeline({Node.JUDGE: Changes(changes)})
    owner, document = await receive(world, pipeline)
    await world.drain(pipeline)
    stored = await world.documents.get(owner.id, document.id)
    assert stored.tag_ids == frozenset({tag.id})
    assert stored.lane is Lane.GREEN


async def test_classified_tags_are_added_to_the_documents_tags(world: World) -> None:
    mine, strom = Tag.create(name="Mine", now=NOW), Tag.create(name="Strom", now=NOW)
    async with world.uow() as uow:
        await uow.tags.add(mine)
        await uow.tags.add(strom)
        await uow.commit()
    pipeline = world.pipeline({Node.JUDGE: Changes(DocumentChanges(), frozenset({strom.id}))})
    owner, document = await receive(world, pipeline)
    await world.documents.update_metadata(
        owner.id, document.id, DocumentChanges(tag_ids=frozenset({mine.id}))
    )
    await world.drain(pipeline)
    stored = await world.documents.get(owner.id, document.id)
    assert stored.tag_ids == frozenset({mine.id, strom.id})
    assert stored.lane is Lane.GREEN


async def test_changes_that_no_longer_fit_make_the_step_uncertain(world: World) -> None:
    changes = DocumentChanges(
        contact_id=ContactId(UUID(int=1)), tag_ids=frozenset({TagId(UUID(int=2))})
    )
    pipeline = world.pipeline({Node.JUDGE: Changes(changes)})
    owner, document = await receive(world, pipeline)
    await world.drain(pipeline)
    stored = await world.documents.get(owner.id, document.id)
    assert stored.lane is Lane.YELLOW
    assert stored.contact_id is None
    log = await world.documents.processing_log(owner.id, document.id)
    classified = next(entry for entry in log if entry.node is Node.JUDGE)
    assert classified.result.outcome is Outcome.UNCERTAIN
    assert (classified.result.reason or "").startswith("the master data changed during the node")
