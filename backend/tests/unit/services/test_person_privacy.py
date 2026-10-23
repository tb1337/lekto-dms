"""What is private about a person found them only for admins and that person: in the
processing log and the review, another user shows only as far as the text names them by their
display name."""

from datetime import timedelta
from typing import Any

from lekto.core.domain.classification import FieldCheck, checks_to_json
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
            reason="space" if node is Node.JUDGE else None,
            output=output,  # type: ignore[arg-type]
        ),
        pipeline_version="1",
        started_at=NOW,
        duration=timedelta(seconds=1),
    )


async def _scene(world: World) -> tuple[User, User, User, Document]:
    """Tobi's document in a space he shares with Anna and Bob, editors both. The facts found
    Anna by her tax ID and display name, Bob by his birth date, Carla (no member) by an alias;
    the judge also had Bob as the recipient, by his display name."""
    tobi, anna, bob, carla = [await world.user() for _ in range(4)]
    shared = await world.spaces.create(tobi.id, "Shared")
    for member in (anna, bob):
        await world.spaces.set_member(tobi.id, shared.id, member.id, SpaceRole.EDIT)
    document = builders.processed(tobi, shared, content="letter")
    facts: dict[str, object] = {
        "persons": [
            {"user_id": str(anna.id), "strength": "hard", "evidence": ["tax_id", "name"]},
            {"user_id": str(bob.id), "strength": "medium", "evidence": ["birth_date"]},
            {"user_id": str(carla.id), "strength": "weak", "evidence": ["alias"]},
        ]
    }
    check = FieldCheck(
        field="space",
        outcome=Outcome.UNCERTAIN,
        confidence=0.5,
        reasons=(written("names someone who would not see it there"),),
        unseen_by=(str(anna.id), str(bob.id), str(carla.id)),
    )
    judge: dict[str, object] = {
        "fields": checks_to_json([check]),
        "persons": [
            {"user_id": str(anna.id), "strength": "hard", "public": "weak"},
            {"user_id": str(bob.id), "strength": "medium", "public": "medium"},
            {"user_id": str(carla.id), "strength": "weak"},
        ],
    }
    async with world.uow() as uow:
        await uow.documents.add(document)
        await uow.processing_log.append(_run(document, Node.SIGNAL_FACTS, facts))
        await uow.processing_log.append(_run(document, Node.JUDGE, judge))
        await uow.commit()
    return anna, bob, carla, document


def _persons(log: list[NodeRun], node: Node) -> Any:
    (entry,) = [run for run in log if run.node is node]
    return entry.result.output["persons"]


def _unseen(log: list[NodeRun]) -> Any:
    (entry,) = [run for run in log if run.node is Node.JUDGE]
    checks: Any = entry.result.output["fields"]
    return checks[0].get("unseen_by")


async def test_another_editor_sees_a_person_only_by_their_display_name(world: World) -> None:
    anna, bob, carla, document = await _scene(world)
    log = await world.documents.processing_log(bob.id, document.id)
    assert _persons(log, Node.SIGNAL_FACTS) == [
        {"user_id": str(anna.id), "strength": "weak", "evidence": ["name"]},
        {"user_id": str(bob.id), "strength": "medium", "evidence": ["birth_date"]},
    ]
    assert _persons(log, Node.JUDGE) == [
        {"user_id": str(anna.id), "strength": "weak"},
        {"user_id": str(bob.id), "strength": "medium", "public": "medium"},
    ]
    # Anna is named weakly in public: that she is unseen would tell her tax ID stands there.
    assert _unseen(log) == [str(bob.id)]
    review = await world.documents.review(bob.id, document.id)
    (judge,) = [node for node in review.nodes if node.node is Node.JUDGE]
    assert judge.fields[0].unseen_by == (str(bob.id),)
    log = await world.documents.processing_log(anna.id, document.id)
    assert _unseen(log) == [str(anna.id), str(bob.id)]
    assert {item["user_id"] for item in _persons(log, Node.SIGNAL_FACTS)} == {str(anna.id)}
    assert str(carla.id) not in str(log)


async def test_admins_see_every_person_found(world: World) -> None:
    anna, bob, carla, document = await _scene(world)
    admin = await world.user(role=Role.ADMIN)
    log = await world.documents.processing_log(admin.id, document.id)
    assert len(_persons(log, Node.SIGNAL_FACTS)) == 3
    assert _unseen(log) == [str(anna.id), str(bob.id), str(carla.id)]
