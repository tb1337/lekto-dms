"""`/jobs`: the summary, the list and the durations for every user, a failed job queued again by
an admin."""

from datetime import timedelta

from lekto.adapters.inbound.rest import PREFIX
from lekto.core.domain.pipeline import Node
from lekto.core.services._jobs import NODE_JOB, NodeJob
from tests import builders
from tests.api import auth
from tests.unit.adapters.rest.support import Api

LEASE = timedelta(minutes=5)


async def failed_jobs(api: Api) -> tuple[str, str, str]:
    """A document of a new user, a failed step of it and a failed logo fetch; their ids."""
    owner = await api.user("owner")
    async with api.container.unit_of_work() as uow:
        space = await uow.spaces.get_personal(owner.id)
        document = builders.processed(owner, space, content="x")
        await uow.documents.add(document)
        step = await uow.jobs.enqueue(
            NODE_JOB,
            NodeJob(document.id, Node.OCR, 1).to_json(),
            run_at=builders.NOW - timedelta(days=1),
        )
        logo = await uow.jobs.enqueue("contacts.logo", {}, run_at=builders.NOW - timedelta(hours=1))
        for _ in range(2):
            job = await uow.jobs.claim(now=builders.NOW, lease=LEASE)
            assert job is not None
            await uow.jobs.fail(job, now=builders.NOW, error=f"broken {job.kind}")
        await uow.commit()
    assert step is not None and logo is not None
    return str(document.id), str(step), str(logo)


async def test_every_user_sees_the_jobs_admins_their_errors(api: Api) -> None:
    document, step, logo = await failed_jobs(api)
    admin, user = await api.admin(), await api.user()

    summary = await api.client.get(f"{PREFIX}/jobs/summary", headers=auth(user))
    assert summary.status_code == 200
    kinds = {item["kind"]: item for item in summary.json()["kinds"]}
    assert kinds["contacts.logo"] == {
        "kind": "contacts.logo",
        "running": 0,
        "due": 0,
        "planned": 0,
        "failed": 1,
        "done": 0,
    }
    assert summary.json()["last_started_at"] is not None

    failed = f"{PREFIX}/jobs?state=failed"
    by_user = (await api.client.get(failed, headers=auth(user))).json()
    by_admin = (await api.client.get(failed, headers=auth(admin))).json()
    assert by_user["total"] == by_admin["total"] == 2
    assert by_user["next_offset"] is None
    seen = {item["id"]: item for item in by_admin["items"]}
    assert seen[step]["document"] == {"id": document, "title": seen[step]["document"]["title"]}
    assert (seen[step]["node"], seen[step]["retry"], seen[step]["error"]) == (
        "ocr",
        "document",
        "broken pipeline.node",
    )
    assert (seen[logo]["retry"], seen[logo]["error"]) == ("job", "broken contacts.logo")
    for item in by_user["items"]:
        assert (item["error"], item["retry"]) == (None, None)
    hidden = next(item for item in by_user["items"] if item["id"] == step)
    assert (hidden["document"], hidden["document_hidden"]) == (None, True)

    open_jobs = (await api.client.get(f"{PREFIX}/jobs", headers=auth(user))).json()
    assert all(item["state"] in {"running", "due", "planned"} for item in open_jobs["items"])
    page = (await api.client.get(f"{failed}&limit=1", headers=auth(user))).json()
    assert (len(page["items"]), page["next_offset"]) == (1, 1)


async def test_an_admin_tries_a_failed_job_again(api: Api) -> None:
    _, step, logo = await failed_jobs(api)
    admin, user = await api.admin(), await api.user()

    assert (
        await api.client.post(f"{PREFIX}/jobs/{logo}/retry", headers=auth(user))
    ).status_code == 403
    in_document = await api.client.post(f"{PREFIX}/jobs/{step}/retry", headers=auth(admin))
    assert in_document.status_code == 409
    assert in_document.json()["reason"]["code"] == "job_retry_in_document"
    retried = await api.client.post(f"{PREFIX}/jobs/{logo}/retry", headers=auth(admin))
    assert retried.status_code == 200
    assert (retried.json()["state"], retried.json()["attempts"]) == ("due", 0)
    again = await api.client.post(f"{PREFIX}/jobs/{logo}/retry", headers=auth(admin))
    assert (again.status_code, again.json()["reason"]["code"]) == (409, "job_not_failed")


async def test_the_durations_of_the_done_jobs(api: Api) -> None:
    user = await api.user()
    async with api.container.unit_of_work() as uow:
        await uow.jobs.enqueue("search.index", {}, run_at=builders.NOW)
        job = await uow.jobs.claim(now=builders.NOW + timedelta(seconds=2), lease=LEASE)
        assert job is not None
        await uow.jobs.complete(job, now=builders.NOW + timedelta(seconds=3))
        await uow.commit()

    response = await api.client.get(f"{PREFIX}/jobs/durations", headers=auth(user))

    assert response.status_code == 200
    index = next(item for item in response.json()["kinds"] if item["kind"] == "search.index")
    assert index == {
        "kind": "search.index",
        "count": 1,
        "wait_median_ms": 2000.0,
        "wait_p90_ms": 2000.0,
        "run_median_ms": 1000.0,
        "run_p90_ms": 1000.0,
    }
