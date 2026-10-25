import asyncio
from datetime import timedelta

import pytest

from lekto.core.domain.errors import ConcurrencyError, ConflictError, NotFoundError
from lekto.core.domain.ids import JobId, new_id
from lekto.core.domain.jobs import FinishedJob, Job, JobCount, JobState, JobStatus
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from tests.builders import NOW

LEASE = timedelta(minutes=5)


async def enqueue(
    uow_factory: UnitOfWorkFactory,
    kind: str = "test",
    *,
    run_at: timedelta = timedelta(0),
    dedup_key: str | None = None,
    coalesce_key: str | None = None,
) -> JobId | None:
    async with uow_factory() as uow:
        job = await uow.jobs.enqueue(
            kind, {"n": 1}, run_at=NOW + run_at, dedup_key=dedup_key, coalesce_key=coalesce_key
        )
        await uow.commit()
    return job


async def claim(
    uow_factory: UnitOfWorkFactory,
    *,
    at: timedelta = timedelta(0),
    kinds: list[str] | None = None,
) -> Job | None:
    async with uow_factory() as uow:
        job = await uow.jobs.claim(now=NOW + at, lease=LEASE, kinds=kinds)
        await uow.commit()
    return job


async def get(uow_factory: UnitOfWorkFactory, job: JobId) -> Job:
    async with uow_factory() as uow:
        return await uow.jobs.get(job)


class JobQueueContract:
    async def test_enqueued_job_is_stored(self, uow_factory: UnitOfWorkFactory) -> None:
        async with uow_factory() as uow:
            id = await uow.jobs.enqueue(
                "pipeline.node",
                {"document_id": "x", "node": "ocr", "run": 1, "extra": [1.5, None, {"a": True}]},
                run_at=NOW,
                dedup_key="x:1:ocr",
            )
            assert id is not None
            await uow.commit()
        job = await get(uow_factory, id)
        assert job.kind == "pipeline.node"
        assert job.payload == {
            "document_id": "x",
            "node": "ocr",
            "run": 1,
            "extra": [1.5, None, {"a": True}],
        }
        assert job.dedup_key == "x:1:ocr"
        assert (job.status, job.attempts, job.run_at) == (JobStatus.QUEUED, 0, NOW)
        assert (job.locked_until, job.last_error) == (None, None)

    async def test_job_exists_only_after_commit(self, uow_factory: UnitOfWorkFactory) -> None:
        async with uow_factory() as uow:
            id = await uow.jobs.enqueue("test", {}, run_at=NOW)
            assert id is not None
        assert await claim(uow_factory) is None
        async with uow_factory() as uow:
            with pytest.raises(NotFoundError):
                await uow.jobs.get(id)

    async def test_missing_job(self, uow_factory: UnitOfWorkFactory) -> None:
        async with uow_factory() as uow:
            with pytest.raises(NotFoundError):
                await uow.jobs.get(JobId(new_id()))

    async def test_claim_takes_due_jobs_most_overdue_first(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        later = await enqueue(uow_factory, run_at=timedelta(minutes=2))
        earlier = await enqueue(uow_factory, run_at=timedelta(minutes=1))
        future = await enqueue(uow_factory, run_at=timedelta(hours=1))
        first = await claim(uow_factory, at=timedelta(minutes=3))
        second = await claim(uow_factory, at=timedelta(minutes=3))
        assert first is not None and first.id == earlier
        assert second is not None and second.id == later
        assert await claim(uow_factory, at=timedelta(minutes=3)) is None
        assert future is not None

    async def test_claim_locks_and_counts_attempts(self, uow_factory: UnitOfWorkFactory) -> None:
        id = await enqueue(uow_factory)
        job = await claim(uow_factory)
        assert job is not None and job.id == id
        assert job.status is JobStatus.RUNNING
        assert job.attempts == 1
        assert job.locked_until == NOW + LEASE
        assert await get(uow_factory, id) == job
        assert await claim(uow_factory, at=LEASE - timedelta(seconds=1)) is None

    async def test_expired_lease_releases_the_job(self, uow_factory: UnitOfWorkFactory) -> None:
        id = await enqueue(uow_factory)
        await claim(uow_factory)
        again = await claim(uow_factory, at=LEASE)
        assert again is not None and again.id == id
        assert again.attempts == 2
        assert again.locked_until == NOW + 2 * LEASE

    async def test_claim_filters_by_kind(self, uow_factory: UnitOfWorkFactory) -> None:
        await enqueue(uow_factory, "index")
        node = await enqueue(uow_factory, "pipeline.node", run_at=timedelta(seconds=1))
        job = await claim(uow_factory, at=timedelta(seconds=1), kinds=["pipeline.node"])
        assert job is not None and job.id == node
        assert await claim(uow_factory, at=timedelta(seconds=1), kinds=["pipeline.node"]) is None

    async def test_claim_without_commit_is_undone(self, uow_factory: UnitOfWorkFactory) -> None:
        id = await enqueue(uow_factory)
        async with uow_factory() as uow:
            assert await uow.jobs.claim(now=NOW, lease=LEASE) is not None
        job = await claim(uow_factory)
        assert job is not None and job.id == id and job.attempts == 1

    async def test_completed_job_does_not_run_again(self, uow_factory: UnitOfWorkFactory) -> None:
        id = await enqueue(uow_factory)
        assert id is not None
        claimed = await claim(uow_factory)
        assert claimed is not None
        async with uow_factory() as uow:
            await uow.jobs.complete(claimed, now=NOW)
            await uow.commit()
        job = await get(uow_factory, id)
        assert (job.status, job.locked_until) == (JobStatus.DONE, None)
        assert await claim(uow_factory, at=2 * LEASE) is None

    async def test_rescheduled_job_runs_again_later(self, uow_factory: UnitOfWorkFactory) -> None:
        id = await enqueue(uow_factory)
        assert id is not None
        claimed = await claim(uow_factory)
        assert claimed is not None
        async with uow_factory() as uow:
            await uow.jobs.reschedule(claimed, run_at=NOW + timedelta(minutes=1), error="timeout")
            await uow.commit()
        job = await get(uow_factory, id)
        assert (job.status, job.last_error, job.locked_until) == (
            JobStatus.QUEUED,
            "timeout",
            None,
        )
        assert await claim(uow_factory, at=timedelta(seconds=59)) is None
        again = await claim(uow_factory, at=timedelta(minutes=1))
        assert again is not None and again.id == id and again.attempts == 2

    async def test_released_job_runs_again_without_counting_the_attempt(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        id = await enqueue(uow_factory)
        assert id is not None
        claimed = await claim(uow_factory)
        assert claimed is not None and claimed.attempts == 1
        async with uow_factory() as uow:
            await uow.jobs.release(claimed, run_at=NOW, error="interrupted")
            await uow.commit()
        job = await get(uow_factory, id)
        assert (job.status, job.locked_until, job.last_error) == (
            JobStatus.QUEUED,
            None,
            "interrupted",
        )
        assert (job.attempts, job.releases, job.tries) == (1, 1, 0)
        again = await claim(uow_factory)
        assert again is not None and again.id == id
        assert (again.attempts, again.tries) == (2, 1)
        async with uow_factory() as uow:
            with pytest.raises(ConcurrencyError):
                await uow.jobs.release(claimed, run_at=NOW, error="stale claim")

    async def test_an_extended_claim_holds_the_job_longer(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        id = await enqueue(uow_factory)
        assert id is not None
        claimed = await claim(uow_factory)
        assert claimed is not None
        async with uow_factory() as uow:
            await uow.jobs.extend(claimed, until=NOW + timedelta(hours=1))
            await uow.commit()
        job = await get(uow_factory, id)
        assert (job.status, job.locked_until) == (JobStatus.RUNNING, NOW + timedelta(hours=1))
        assert await claim(uow_factory, at=LEASE) is None  # its lease alone would have run out
        again = await claim(uow_factory, at=timedelta(hours=1))
        assert again is not None and again.id == id
        async with uow_factory() as uow:
            with pytest.raises(ConcurrencyError):
                await uow.jobs.extend(claimed, until=NOW + timedelta(hours=2))

    async def test_failed_job_is_given_up(self, uow_factory: UnitOfWorkFactory) -> None:
        id = await enqueue(uow_factory)
        assert id is not None
        claimed = await claim(uow_factory)
        assert claimed is not None
        async with uow_factory() as uow:
            await uow.jobs.fail(claimed, now=NOW, error="broken file")
            await uow.commit()
        job = await get(uow_factory, id)
        assert (job.status, job.last_error, job.locked_until) == (
            JobStatus.FAILED,
            "broken file",
            None,
        )
        assert await claim(uow_factory, at=2 * LEASE) is None

    async def test_purge_removes_finished_jobs(self, uow_factory: UnitOfWorkFactory) -> None:
        ids = [await enqueue(uow_factory, run_at=timedelta(seconds=n)) for n in range(4)]
        assert all(ids)
        done, failed, running = [await claim(uow_factory, at=LEASE) for _ in range(3)]
        assert done and failed and running
        async with uow_factory() as uow:
            await uow.jobs.complete(done, now=NOW)
            await uow.jobs.fail(failed, now=NOW, error="broken")
            await uow.commit()

        async with uow_factory() as uow:  # not committed: nothing removed
            assert await uow.jobs.purge(before=NOW + LEASE) == 2
        assert (await get(uow_factory, done.id)).status is JobStatus.DONE

        async with uow_factory() as uow:
            assert await uow.jobs.purge(before=NOW + timedelta(seconds=1)) == 1  # due before
            assert await uow.jobs.purge(before=NOW + LEASE) == 1
            with pytest.raises(NotFoundError):
                await uow.jobs.get(failed.id)
            await uow.commit()
        for job in (done, failed):
            with pytest.raises(NotFoundError):
                await get(uow_factory, job.id)
        assert (await get(uow_factory, running.id)).status is JobStatus.RUNNING
        queued = ids[3]
        assert queued is not None and (await get(uow_factory, queued)).status is JobStatus.QUEUED

    async def test_a_purged_dedup_key_can_be_used_again(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        assert await enqueue(uow_factory, dedup_key="cleanup") is not None
        claimed = await claim(uow_factory)
        assert claimed is not None
        async with uow_factory() as uow:
            await uow.jobs.complete(claimed, now=NOW)
            await uow.jobs.purge(before=NOW + LEASE)
            assert await uow.jobs.enqueue("test", {}, run_at=NOW, dedup_key="cleanup")
            await uow.commit()

    async def test_dedup_key_while_active(self, uow_factory: UnitOfWorkFactory) -> None:
        first = await enqueue(uow_factory, dedup_key="doc:1:ocr")
        assert first is not None
        assert await enqueue(uow_factory, dedup_key="doc:1:ocr") is None
        assert (
            await enqueue(uow_factory, run_at=timedelta(hours=1), dedup_key="doc:1:parse")
            is not None
        )
        claimed = await claim(uow_factory, kinds=["test"])
        assert claimed is not None and claimed.dedup_key == "doc:1:ocr"
        assert await enqueue(uow_factory, dedup_key="doc:1:ocr") is None
        async with uow_factory() as uow:
            await uow.jobs.complete(claimed, now=NOW)
            await uow.commit()
        assert await enqueue(uow_factory, dedup_key="doc:1:ocr") is not None

    async def test_dedup_key_within_one_unit(self, uow_factory: UnitOfWorkFactory) -> None:
        async with uow_factory() as uow:
            assert await uow.jobs.enqueue("test", {}, run_at=NOW, dedup_key="k") is not None
            assert await uow.jobs.enqueue("test", {}, run_at=NOW, dedup_key="k") is None
            await uow.commit()

    async def test_coalesce_key_while_queued(self, uow_factory: UnitOfWorkFactory) -> None:
        first = await enqueue(uow_factory, coalesce_key="index:a")
        assert first is not None
        assert (await get(uow_factory, first)).coalesce_key == "index:a"
        assert await enqueue(uow_factory, coalesce_key="index:a") is None
        assert await enqueue(uow_factory, run_at=timedelta(hours=1), coalesce_key="index:b")
        claimed = await claim(uow_factory)
        assert claimed is not None and claimed.id == first
        assert claimed.coalesce_key is None  # claimed: its work has begun
        assert (await get(uow_factory, first)).coalesce_key is None
        second = await enqueue(uow_factory, coalesce_key="index:a")
        assert second is not None
        assert await enqueue(uow_factory, coalesce_key="index:a") is None

    async def test_coalesce_key_within_one_unit(self, uow_factory: UnitOfWorkFactory) -> None:
        async with uow_factory() as uow:
            assert await uow.jobs.enqueue("test", {}, run_at=NOW, coalesce_key="k") is not None
            assert await uow.jobs.enqueue("test", {}, run_at=NOW, coalesce_key="k") is None
            await uow.commit()

    async def test_a_job_has_one_key_at_most(self, uow_factory: UnitOfWorkFactory) -> None:
        async with uow_factory() as uow:
            with pytest.raises(ValueError, match="not both"):
                await uow.jobs.enqueue("test", {}, run_at=NOW, dedup_key="k", coalesce_key="k")

    async def test_a_coalesced_job_queued_again_holds_no_key(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        assert await enqueue(uow_factory, coalesce_key="index:a") is not None
        retried = await claim(uow_factory)
        assert retried is not None
        assert await enqueue(uow_factory, coalesce_key="index:a") is not None
        released = await claim(uow_factory)
        assert released is not None
        newest = await enqueue(uow_factory, coalesce_key="index:a")
        assert newest is not None
        async with uow_factory() as uow:
            await uow.jobs.reschedule(retried, run_at=NOW, error="timeout")
            await uow.jobs.release(released, run_at=NOW, error="interrupted")
            await uow.commit()
        assert (await get(uow_factory, retried.id)).coalesce_key is None
        assert (await get(uow_factory, released.id)).coalesce_key is None
        assert (await get(uow_factory, newest)).coalesce_key == "index:a"
        assert await enqueue(uow_factory, coalesce_key="index:a") is None

    async def test_a_job_is_never_claimed_twice(self, uow_factory: UnitOfWorkFactory) -> None:
        id = await enqueue(uow_factory)

        async def claim_and_commit() -> Job | None:
            async with uow_factory() as uow:
                job = await uow.jobs.claim(now=NOW, lease=LEASE)
                await asyncio.sleep(0)
                await uow.commit()
                return job

        results = await asyncio.gather(
            claim_and_commit(), claim_and_commit(), return_exceptions=True
        )
        claimed = [r for r in results if isinstance(r, Job)]
        assert [job.id for job in claimed] == [id]
        assert all(r is None or isinstance(r, (Job, ConcurrencyError)) for r in results)

    async def test_only_the_current_claim_finishes_a_job(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        id = await enqueue(uow_factory)
        lost = await claim(uow_factory)
        current = await claim(uow_factory, at=LEASE)
        assert lost is not None and current is not None and current.id == lost.id == id
        for finish in ("complete", "reschedule", "fail"):
            with pytest.raises(ConcurrencyError):
                async with uow_factory() as uow:
                    if finish == "complete":
                        await uow.jobs.complete(lost, now=NOW)
                    elif finish == "reschedule":
                        await uow.jobs.reschedule(lost, run_at=NOW, error="late")
                    else:
                        await uow.jobs.fail(lost, now=NOW, error="late")
                    await uow.commit()
        async with uow_factory() as uow:
            await uow.jobs.complete(current, now=NOW)
            await uow.commit()
        with pytest.raises(ConcurrencyError):
            async with uow_factory() as uow:
                await uow.jobs.complete(current, now=NOW)
                await uow.commit()
        assert (await get(uow_factory, id)).status is JobStatus.DONE

    async def test_reads_are_copies(self, uow_factory: UnitOfWorkFactory) -> None:
        id = await enqueue(uow_factory)
        assert id is not None
        job = await get(uow_factory, id)
        job.payload["n"] = 2
        assert (await get(uow_factory, id)).payload == {"n": 1}

    async def test_a_job_keeps_when_it_started_and_finished(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        done = await enqueue(uow_factory)
        failed = await enqueue(uow_factory, run_at=timedelta(seconds=1))
        assert done is not None and failed is not None
        first = await claim(uow_factory, at=timedelta(seconds=2))
        second = await claim(uow_factory, at=timedelta(seconds=3))
        assert first is not None and second is not None
        assert (first.started_at, second.started_at) == (
            NOW + timedelta(seconds=2),
            NOW + timedelta(seconds=3),
        )
        async with uow_factory() as uow:
            await uow.jobs.complete(
                first, now=NOW + timedelta(seconds=5), result={"sections": 3, "model": "m"}
            )
            await uow.jobs.fail(second, now=NOW + timedelta(seconds=6), error="broken")
            await uow.commit()
        job = await get(uow_factory, done)
        assert (job.started_at, job.finished_at, job.result) == (
            NOW + timedelta(seconds=2),
            NOW + timedelta(seconds=5),
            {"sections": 3, "model": "m"},
        )
        job = await get(uow_factory, failed)
        assert (job.finished_at, job.result, job.last_error) == (
            NOW + timedelta(seconds=6),
            None,
            "broken",
        )
        fresh = await get(uow_factory, await enqueue(uow_factory) or JobId(new_id()))
        assert (fresh.started_at, fresh.finished_at, fresh.result) == (None, None, None)

    async def test_retry_queues_a_failed_job_as_new(self, uow_factory: UnitOfWorkFactory) -> None:
        id = await enqueue(uow_factory, dedup_key="logo:1")
        assert id is not None
        claimed = await claim(uow_factory)
        assert claimed is not None
        async with uow_factory() as uow:
            await uow.jobs.fail(claimed, now=NOW + timedelta(seconds=1), error="timeout")
            await uow.commit()
        async with uow_factory() as uow:  # not committed: still failed
            await uow.jobs.retry(id, now=NOW + timedelta(minutes=1))
        assert (await get(uow_factory, id)).status is JobStatus.FAILED
        async with uow_factory() as uow:
            retried = await uow.jobs.retry(id, now=NOW + timedelta(minutes=1))
            await uow.commit()
        job = await get(uow_factory, id)
        assert job == retried
        assert (job.status, job.run_at, job.attempts, job.releases) == (
            JobStatus.QUEUED,
            NOW + timedelta(minutes=1),
            0,
            0,
        )
        assert (job.started_at, job.finished_at, job.locked_until) == (None, None, None)
        assert (job.last_error, job.dedup_key) == ("timeout", "logo:1")
        assert await enqueue(uow_factory, dedup_key="logo:1") is None  # active again
        again = await claim(uow_factory, at=timedelta(minutes=1))
        assert again is not None and again.id == id and again.attempts == 1

    async def test_only_a_failed_job_is_retried(self, uow_factory: UnitOfWorkFactory) -> None:
        queued = await enqueue(uow_factory)
        assert queued is not None
        async with uow_factory() as uow:
            with pytest.raises(ConflictError) as raised:
                await uow.jobs.retry(queued, now=NOW)
            assert raised.value.reason is not None
            assert raised.value.reason.code == "job_not_failed"
            with pytest.raises(NotFoundError):
                await uow.jobs.retry(JobId(new_id()), now=NOW)
        claimed = await claim(uow_factory)
        assert claimed is not None
        async with uow_factory() as uow:
            await uow.jobs.complete(claimed, now=NOW)
            await uow.commit()
        async with uow_factory() as uow:
            with pytest.raises(ConflictError):
                await uow.jobs.retry(queued, now=NOW)

    async def test_retry_waits_for_the_same_work_queued_again(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        failed = await enqueue(uow_factory, dedup_key="train")
        assert failed is not None
        claimed = await claim(uow_factory)
        assert claimed is not None
        async with uow_factory() as uow:
            await uow.jobs.fail(claimed, now=NOW, error="broken")
            await uow.commit()
        assert await enqueue(uow_factory, dedup_key="train") is not None
        async with uow_factory() as uow:
            with pytest.raises(ConflictError) as raised:
                await uow.jobs.retry(failed, now=NOW)
        assert raised.value.reason is not None
        assert raised.value.reason.code == "job_already_queued"
        assert (await get(uow_factory, failed)).status is JobStatus.FAILED

    async def test_overview_counts_the_jobs_by_kind_and_state(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        async with uow_factory() as uow:
            empty = await uow.jobs.overview(now=NOW)
        assert (empty.counts, empty.last_started) == ((), None)
        for kind, at in [("a", 0), ("a", 1), ("a", 2), ("a", 3), ("b", 4)]:
            await enqueue(uow_factory, kind, run_at=timedelta(seconds=at))
        await enqueue(uow_factory, "a", run_at=timedelta(hours=1))  # planned
        await enqueue(uow_factory, "b", run_at=timedelta(seconds=30))  # due at 30 s
        done = await claim(uow_factory, at=timedelta(seconds=10))
        failed = await claim(uow_factory, at=timedelta(seconds=11))
        await claim(uow_factory, at=timedelta(seconds=12))  # running
        assert done is not None and failed is not None
        async with uow_factory() as uow:
            await uow.jobs.complete(done, now=NOW + timedelta(seconds=13))
            await uow.jobs.fail(failed, now=NOW + timedelta(seconds=13), error="x")
            await uow.commit()
        async with uow_factory() as uow:
            overview = await uow.jobs.overview(now=NOW + timedelta(seconds=30))
        assert set(overview.counts) == {
            JobCount("a", JobState.DONE, 1),
            JobCount("a", JobState.FAILED, 1),
            JobCount("a", JobState.RUNNING, 1),
            JobCount("a", JobState.DUE, 1),
            JobCount("a", JobState.PLANNED, 1),
            JobCount("b", JobState.DUE, 2),
        }
        assert overview.last_started == NOW + timedelta(seconds=12)
        async with uow_factory() as uow:
            earlier = await uow.jobs.overview(now=NOW + timedelta(seconds=29))
        assert JobCount("b", JobState.PLANNED, 1) in earlier.counts

    async def test_find_orders_by_state_and_time(self, uow_factory: UnitOfWorkFactory) -> None:
        ids = {}
        for name, kind, at in [
            ("done_early", "a", 0),
            ("done_late", "a", 1),
            ("failed", "b", 2),
            ("running_long", "a", 3),
            ("running_short", "b", 4),
            ("due_late", "a", 20),
            ("due_early", "b", 10),
            ("planned", "a", 3600),
        ]:
            ids[name] = await enqueue(uow_factory, kind, run_at=timedelta(seconds=at))
        claimed = [await claim(uow_factory, at=timedelta(seconds=5 + n)) for n in range(5)]
        assert all(claimed)
        done_early, done_late, failed, _, _ = claimed
        assert done_early and done_late and failed
        async with uow_factory() as uow:
            await uow.jobs.complete(done_late, now=NOW + timedelta(seconds=40))
            await uow.jobs.complete(done_early, now=NOW + timedelta(seconds=30))
            await uow.jobs.fail(failed, now=NOW + timedelta(seconds=35), error="x")
            await uow.commit()
        moment = NOW + timedelta(seconds=60)

        async def find(states: set[JobState], **options: object) -> list[JobId | None]:
            async with uow_factory() as uow:
                jobs = await uow.jobs.find(now=moment, states=states, limit=50, **options)  # type: ignore[arg-type]
            return [job.id for job in jobs]

        everything = set(JobState)
        assert await find(everything) == [
            ids[name]
            for name in (
                "running_long",
                "running_short",
                "due_early",
                "due_late",
                "planned",
                "failed",
                "done_late",
                "done_early",
            )
        ]
        assert await find({JobState.DUE, JobState.PLANNED}, kind="a") == [
            ids["due_late"],
            ids["planned"],
        ]
        assert await find(everything, offset=2) == (await find(everything))[2:]
        async with uow_factory() as uow:
            page = await uow.jobs.find(now=moment, states=everything, offset=1, limit=2)
        assert [job.id for job in page] == [ids["running_short"], ids["due_early"]]
        async with uow_factory() as uow:
            assert await uow.jobs.find(now=moment, states=set(), limit=10) == []

    async def test_finished_names_the_times_of_done_jobs(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        for kind, at in [("a", 0), ("b", 1), ("a", 2), ("a", 3)]:
            await enqueue(uow_factory, kind, run_at=timedelta(seconds=at))
        old, other, recent, failed = [
            await claim(uow_factory, at=timedelta(seconds=10 + n)) for n in range(4)
        ]
        assert old and other and recent and failed
        async with uow_factory() as uow:
            await uow.jobs.complete(old, now=NOW + timedelta(seconds=20))
            await uow.jobs.complete(other, now=NOW + timedelta(seconds=40), result={"x": 1})
            await uow.jobs.complete(recent, now=NOW + timedelta(seconds=30), result={"n": 2})
            await uow.jobs.fail(failed, now=NOW + timedelta(seconds=30), error="x")
            await uow.commit()
        async with uow_factory() as uow:
            found = await uow.jobs.finished(since=NOW + timedelta(seconds=30))
            only_a = await uow.jobs.finished(since=NOW, kinds=["a"])
        assert found == [
            FinishedJob(
                kind="a",
                run_at=NOW + timedelta(seconds=2),
                started_at=NOW + timedelta(seconds=12),
                finished_at=NOW + timedelta(seconds=30),
                result={"n": 2},
            ),
            FinishedJob(
                kind="b",
                run_at=NOW + timedelta(seconds=1),
                started_at=NOW + timedelta(seconds=11),
                finished_at=NOW + timedelta(seconds=40),
                result={"x": 1},
            ),
        ]
        assert [job.finished_at for job in only_a] == [
            NOW + timedelta(seconds=20),
            NOW + timedelta(seconds=30),
        ]
        async with uow_factory() as uow:  # the latest ones, still earliest first
            latest = await uow.jobs.finished(since=NOW, limit=2)
            none = await uow.jobs.finished(since=NOW, limit=0)
        assert [job.finished_at for job in latest] == [
            NOW + timedelta(seconds=30),
            NOW + timedelta(seconds=40),
        ]
        assert none == []
