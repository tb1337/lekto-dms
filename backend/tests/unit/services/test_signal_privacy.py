"""The similar documents a signal found are searched from the uploader's reach: an editor of
the document's space, or who received it, sees only those they may read themselves."""

from datetime import timedelta
from typing import Any

from lekto.core.domain.classification import Candidate, CandidateSource, FieldCheck, checks_to_json
from lekto.core.domain.documents import Document
from lekto.core.domain.pipeline import Node, NodeResult, NodeRun, Outcome
from lekto.core.domain.reasons import written
from lekto.core.domain.spaces import SpaceRole
from lekto.core.domain.users import Role, User
from tests import builders
from tests.builders import NOW
from tests.unit.services.support import World


def _run(document: Document, node: Node, output: dict[str, object]) -> NodeRun:
    return NodeRun(
        document_id=document.id,
        node=node,
        run=1,
        result=NodeResult(
            outcome=Outcome.UNCERTAIN if node is Node.JUDGE else Outcome.OK,
            reasons=(written("contact"),) if node is Node.JUDGE else (),
            output=output,  # type: ignore[arg-type]
        ),
        pipeline_version="1",
        started_at=NOW,
        duration=timedelta(seconds=1),
    )


async def _scene(world: World) -> tuple[User, User, Document, Document, Document]:
    """Tobi's private document, one in a space he shares with Anna, and the new one there,
    whose signals found both."""
    tobi, anna = await world.user(), await world.user()
    shared = await world.spaces.create(tobi.id, "Shared")
    await world.spaces.set_member(tobi.id, shared.id, anna.id, SpaceRole.EDIT)
    home = await world.personal_space(tobi)
    private = builders.processed(tobi, home, content="private")
    common = builders.processed(tobi, shared, content="common")
    new = builders.processed(tobi, shared, content="new")
    found: list[dict[str, object]] = [
        {"document_id": str(item.id), "score": 0.9, "contact_id": None, "tag_ids": []}
        for item in (private, common)
    ]
    sources = CandidateSource(
        signal=Node.SIGNAL_NEIGHBOURS.value,
        names=True,
        votes=2,
        of=2,
        documents=(str(private.id), str(common.id)),
    )
    check = FieldCheck(
        field="contact",
        outcome=Outcome.UNCERTAIN,
        confidence=0.5,
        reasons=(written("unsure"),),
        candidates=(Candidate(value=None, label="Dr. Private", sources=(sources,)),),
    )
    async with world.uow() as uow:
        for document in (private, common, new):
            await uow.documents.add(document)
        await uow.processing_log.append(
            _run(new, Node.SIGNAL_NEIGHBOURS, {"neighbours": found, "known": {"contacts": []}})
        )
        await uow.processing_log.append(_run(new, Node.JUDGE, {"fields": checks_to_json([check])}))
        await uow.commit()
    return tobi, anna, private, common, new


def _neighbours(log: list[NodeRun]) -> tuple[list[object], bool]:
    (entry,) = [run for run in log if run.node is Node.SIGNAL_NEIGHBOURS]
    output = entry.result.output
    found = output["neighbours"]
    assert isinstance(found, list)
    return [item["document_id"] for item in found if isinstance(item, dict)], "known" in output


def _sources(log: list[NodeRun]) -> Any:
    (entry,) = [run for run in log if run.node is Node.JUDGE]
    checks: Any = entry.result.output["fields"]
    (check,) = checks
    return check["candidates"][0]["sources"][0]["documents"]


async def test_a_co_editor_sees_only_the_similar_documents_they_may_read(world: World) -> None:
    tobi, anna, private, common, new = await _scene(world)
    log = await world.documents.processing_log(anna.id, new.id)
    assert _neighbours(log) == ([str(common.id)], False)
    assert _sources(log) == [str(common.id)]
    review = await world.documents.review(anna.id, new.id)
    (judge,) = [node for node in review.nodes if node.node is Node.JUDGE]
    assert judge.fields[0].candidates[0].sources[0].documents == (str(common.id),)
    # The uploader reads both; what his documents carry stays with admins.
    assert _neighbours(await world.documents.processing_log(tobi.id, new.id)) == (
        [str(private.id), str(common.id)],
        False,
    )
    admin = await world.user(role=Role.ADMIN)
    assert _neighbours(await world.documents.processing_log(admin.id, new.id))[1]


async def test_who_received_a_document_sees_none_of_the_givers_similar_documents(
    world: World,
) -> None:
    tobi, _, _, _, new = await _scene(world)
    bob = await world.user()
    await world.documents.move(tobi.id, new.id, (await world.personal_space(bob)).id)
    log = await world.documents.processing_log(bob.id, new.id)
    assert _neighbours(log) == ([], False)
    assert _sources(log) == []
