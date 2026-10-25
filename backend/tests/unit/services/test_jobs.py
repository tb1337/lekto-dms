"""The jobs on the page "System": counts by kind and state, the jobs as their viewer may see
them, the durations of the jobs done lately, and a failed job queued again by an admin."""

from datetime import timedelta

import pytest

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import ConflictError, PermissionDeniedError
from lekto.core.domain.ids import JobId
from lekto.core.domain.jobs import OPEN_STATES, JobState
from lekto.core.domain.master_data import Contact
from lekto.core.domain.pipeline import Node
from lekto.core.domain.users import Role
from lekto.core.services.jobs import JobsService, KindSummary, RetryWay
from lekto.core.services.pipeline import NODE_JOB, NodeJob
from tests.builders import NOW, incoming
from tests.unit.services.support import World

RETENTION = timedelta(days=7)
LEASE = timedelta(minutes=5)


def jobs(world: World) -> JobsService:
    return JobsService(world.uow, world.clock, retention=RETENTION)


async def finish(
    world: World, *, error: str | None = None, kinds: list[str] | None = None
) -> JobId:
    """Claim the most overdue job (of `kinds`) now and complete it, or fail it with `error`."""
    async with world.uow() as uow:
        job = await uow.jobs.claim(now=world.clock.now(), lease=LEASE, kinds=kinds)
        assert job is not None
        if error is None:
            await uow.jobs.complete(job, now=world.clock.now())
        else:
            await uow.jobs.fail(job, now=world.clock.now(), error=error)
        await uow.commit()
    return job.id


async def queue(world: World, kind: str, payload: dict[str, object], at: timedelta) -> None:
    async with world.uow() as uow:
        await uow.jobs.enqueue(kind, payload, run_at=NOW + at)  # type: ignore[arg-type]
        await uow.commit()


async def document_of(world: World) -> tuple[Document, JobId]:
    """A document of a new user received, and a failed job of one of its steps."""
    owner = await world.user("owner")
    document = await world.pipeline().receive(owner.id, incoming(b"%PDF-1"), filename="a.pdf")
    async with world.uow() as uow:
        failed = await uow.jobs.enqueue(
            NODE_JOB, NodeJob(document.id, Node.OCR, 99).to_json(), run_at=NOW - timedelta(1)
        )
        await uow.commit()
    assert failed is not None
    await finish(world, error="OCRmyPDF: page 3 unreadable", kinds=[NODE_JOB])
    return document, failed


async def test_the_summary_counts_the_jobs_by_kind_and_state(world: World) -> None:
    viewer = await world.user()
    await queue(world, "search.index", {}, timedelta(0))
    await queue(world, "search.index", {}, timedelta(seconds=1))
    await queue(world, "search.index", {}, timedelta(hours=1))
    await queue(world, "contacts.logo", {}, timedelta(0))
    world.clock.advance(timedelta(seconds=10))
    await finish(world, kinds=["search.index"])
    await finish(world, error="timeout", kinds=["contacts.logo"])

    summary = await jobs(world).summary(viewer.id)

    assert summary.kinds == (
        KindSummary("contacts.logo", failed=1),
        KindSummary("search.index", due=1, planned=1, done=1),
    )
    assert summary.last_started == NOW + timedelta(seconds=10)
    assert summary.now == NOW + timedelta(seconds=10)
    assert summary.kept_since == summary.now - RETENTION
    assert summary.kinds[1].count(OPEN_STATES) == 2


async def test_a_job_names_a_document_only_to_those_who_may_read_it(world: World) -> None:
    document, failed = await document_of(world)
    owner = document.uploaded_by
    assert owner is not None
    stranger = await world.user("stranger")

    mine = await jobs(world).list(owner, states=[JobState.FAILED])
    theirs = await jobs(world).list(stranger.id, states=[JobState.FAILED])

    [view] = mine.jobs
    assert (view.job.id, view.state, view.node) == (failed, JobState.FAILED, Node.OCR)
    assert view.document is not None and view.document.title == document.title
    assert not view.document_hidden
    [hidden] = theirs.jobs
    assert (hidden.document, hidden.document_hidden, hidden.node) == (None, True, Node.OCR)
    assert (mine.total, theirs.total) == (1, 1)


async def test_errors_and_retries_are_for_admins(world: World) -> None:
    document, failed = await document_of(world)
    async with world.uow() as uow:
        contact = Contact.create(name="Stadtwerke", now=NOW)
        await uow.contacts.add(contact)
        await uow.jobs.enqueue("contacts.logo", {"contact_id": str(contact.id)}, run_at=NOW)
        await uow.commit()
    logo = await finish(world, error="timeout after 10 s", kinds=["contacts.logo"])
    admin = await world.user("admin", role=Role.ADMIN)
    assert document.uploaded_by is not None

    seen = await jobs(world).list(admin.id, states=[JobState.FAILED])
    by_user = await jobs(world).list(document.uploaded_by, states=[JobState.FAILED])

    views = {view.job.id: view for view in seen.jobs}
    assert (views[failed].error, views[failed].retry) == (
        "OCRmyPDF: page 3 unreadable",
        RetryWay.DOCUMENT,
    )
    assert (views[logo].error, views[logo].retry, views[logo].contact) == (
        "timeout after 10 s",
        RetryWay.JOB,
        "Stadtwerke",
    )
    assert {(view.error, view.retry) for view in by_user.jobs} == {(None, None)}


async def test_an_admin_queues_a_failed_job_again(world: World) -> None:
    document, failed = await document_of(world)
    await queue(world, "contacts.logo", {}, timedelta(0))
    logo = await finish(world, error="timeout", kinds=["contacts.logo"])
    admin = await world.user("admin", role=Role.ADMIN)
    assert document.uploaded_by is not None
    world.clock.advance(timedelta(minutes=1))

    with pytest.raises(PermissionDeniedError):
        await jobs(world).retry(document.uploaded_by, logo)
    with pytest.raises(ConflictError) as raised:
        await jobs(world).retry(admin.id, failed)
    assert raised.value.reason is not None
    assert raised.value.reason.code == "job_retry_in_document"
    retried = await jobs(world).retry(admin.id, logo)

    assert (retried.job.id, retried.state, retried.retry) == (logo, JobState.DUE, None)
    assert retried.job.run_at == NOW + timedelta(minutes=1)
    with pytest.raises(ConflictError):
        await jobs(world).retry(admin.id, logo)


async def test_the_list_pages_through_the_open_jobs_of_a_kind(world: World) -> None:
    viewer = await world.user()
    for n in range(5):
        await queue(world, "search.index", {}, timedelta(seconds=n))
    await queue(world, "contacts.logo", {}, timedelta(0))
    world.clock.advance(timedelta(seconds=10))

    first = await jobs(world).list(
        viewer.id, states=OPEN_STATES, kind="search.index", offset=0, limit=2
    )
    rest = await jobs(world).list(
        viewer.id, states=OPEN_STATES, kind="search.index", offset=2, limit=10
    )

    assert (len(first.jobs), len(rest.jobs), first.total, rest.total) == (2, 3, 5, 5)
    assert [view.job.run_at for view in first.jobs + rest.jobs] == [
        NOW + timedelta(seconds=n) for n in range(5)
    ]


async def test_durations_of_the_jobs_done_within_the_retention(world: World) -> None:
    viewer = await world.user()
    # Done eight days ago: outside the retention.
    await queue(world, "search.index", {}, timedelta(0))
    await finish(world, kinds=["search.index"])
    world.clock.advance(timedelta(days=8))
    for waited, ran in [(1, 2), (3, 4), (5, 30)]:
        now = world.clock.now() - NOW
        await queue(world, "search.index", {}, now)
        world.clock.advance(timedelta(seconds=waited))
        async with world.uow() as uow:
            job = await uow.jobs.claim(now=world.clock.now(), lease=LEASE)
            assert job is not None
            world.clock.advance(timedelta(seconds=ran))
            await uow.jobs.complete(job, now=world.clock.now(), result={"sections": 1})
            await uow.commit()

    durations = await jobs(world).durations(viewer.id)

    [index] = durations.kinds
    assert (index.kind, index.count) == ("search.index", 3)
    assert (index.wait_median, index.wait_p90) == (timedelta(seconds=3), timedelta(seconds=5))
    assert (index.run_median, index.run_p90) == (timedelta(seconds=4), timedelta(seconds=30))
    assert durations.since == world.clock.now() - RETENTION


async def test_durations_come_from_the_latest_jobs_of_a_kind_and_are_kept_a_minute(
    world: World,
) -> None:
    viewer = await world.user()
    service = JobsService(world.uow, world.clock, retention=RETENTION, sample=2)
    for ran in [100, 2, 4]:  # the earliest one falls out of the sample
        await queue(world, "search.index", {}, world.clock.now() - NOW)
        async with world.uow() as uow:
            job = await uow.jobs.claim(now=world.clock.now(), lease=LEASE)
            assert job is not None
            world.clock.advance(timedelta(seconds=ran))
            await uow.jobs.complete(job, now=world.clock.now())
            await uow.commit()
    await queue(world, "contacts.logo", {}, world.clock.now() - NOW)
    await finish(world, kinds=["contacts.logo"])

    first = await service.durations(viewer.id)
    [logo, index] = first.kinds
    assert (index.count, index.run_median, index.run_p90) == (
        2,
        timedelta(seconds=2),
        timedelta(seconds=4),
    )
    assert (logo.kind, logo.count) == ("contacts.logo", 1)

    await queue(world, "search.index", {}, world.clock.now() - NOW)
    await finish(world, kinds=["search.index"])
    world.clock.advance(timedelta(seconds=59))
    assert await service.durations(viewer.id) == first  # kept
    world.clock.advance(timedelta(seconds=2))
    [_, counted] = (await service.durations(viewer.id)).kinds
    assert (counted.count, counted.run_median) == (2, timedelta(seconds=0))
