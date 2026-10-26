"""Keeping the facts of processing as they happen: the first run when it stops, and a person's
verdicts at their first decision on each field (`services._first_runs`)."""

from dataclasses import dataclass
from datetime import date, timedelta

from lekto.core.domain.classification import (
    CONTACT,
    DOCUMENT_DATE,
    SPACE,
    TAGS,
    Candidate,
    CandidateSource,
    FieldCheck,
    checks_to_json,
)
from lekto.core.domain.document_facts import DocumentFact, FactOrigin, FactRole
from lekto.core.domain.documents import Document, DocumentChanges
from lekto.core.domain.first_runs import FACTS, Decision, FieldVerdict, Verdict
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import SpaceId
from lekto.core.domain.master_data import Assignment, Contact, Tag
from lekto.core.domain.pipeline import Lane, Node, NodeResult, Outcome
from lekto.core.domain.reasons import written
from lekto.core.domain.users import User
from lekto.core.services.pipeline import MetadataResult, PipelineService
from tests.builders import NOW, Returns, incoming
from tests.unit.services.support import World

PDF = b"%PDF-1.7\n%%EOF\n"
DATE = date(2026, 10, 1)


@dataclass
class Scene:
    owner: User
    named: Contact  # what the language model named, and the judge set
    other: Contact  # what the classifier named
    pipeline: PipelineService


def judged(
    named: Contact, other: Contact, *, sure_date: bool, space_suggestion: SpaceId | None = None
) -> MetadataResult:
    """The judge sets `named` as the contact (the language model named it, the classifier
    `other`); the date is sure, or uncertain without a suggestion; with `space_suggestion`, the
    space is uncertain with that suggestion."""
    candidates = (
        Candidate(
            value=str(named.id),
            label=named.name,
            sources=(CandidateSource(signal=Node.SIGNAL_LLM.value, names=True),),
        ),
        Candidate(
            value=str(other.id),
            label=other.name,
            sources=(CandidateSource(signal=Node.SIGNAL_CLASSIFIER.value, names=True),),
        ),
    )
    checks = [
        FieldCheck(
            field=CONTACT,
            outcome=Outcome.OK,
            confidence=0.9,
            value=str(named.id),
            candidates=candidates,
        ),
        FieldCheck(field=TAGS, outcome=Outcome.OK, confidence=1, value=[]),
        FieldCheck(field=DOCUMENT_DATE, outcome=Outcome.OK, confidence=1, value=DATE.isoformat())
        if sure_date
        else FieldCheck(
            field=DOCUMENT_DATE,
            outcome=Outcome.UNCERTAIN,
            confidence=0,
            reasons=(written("no date"),),
        ),
    ]
    if space_suggestion is not None:
        checks.append(
            FieldCheck(
                field=SPACE,
                outcome=Outcome.UNCERTAIN,
                confidence=0.5,
                reasons=(written("space"),),
                suggestion=str(space_suggestion),
            )
        )
    uncertain = [check.field for check in checks if not check.ok]
    result = NodeResult(
        outcome=Outcome.UNCERTAIN if uncertain else Outcome.OK,
        reasons=tuple(written(name) for name in uncertain),
        model_version="fake-llm 1",
        output={"fields": checks_to_json(checks)},
    )
    changes = DocumentChanges(contact_id=named.id, document_date=DATE if sure_date else None)
    return MetadataResult(result, changes)


async def scene(world: World, *, sure_date: bool, space_suggestion: SpaceId | None = None) -> Scene:
    owner = await world.user()
    named = Contact.create(name="Stadtwerke", now=NOW)
    other = Contact.create(name="Gemeindewerke", now=NOW)
    async with world.uow() as uow:
        await uow.contacts.add(named)
        await uow.contacts.add(other)
        await uow.commit()
    verdict = judged(named, other, sure_date=sure_date, space_suggestion=space_suggestion)
    pipeline = world.pipeline({Node.JUDGE: Returns(verdict)})
    return Scene(owner, named, other, pipeline)


async def received(s: Scene, space: SpaceId | None = None) -> Document:
    return await s.pipeline.receive(s.owner.id, incoming(PDF), filename="a.pdf", space=space)


async def verdicts(world: World, document: Document) -> dict[str, FieldVerdict]:
    async with world.uow() as uow:
        return {item.field: item for item in await uow.processing_facts.verdicts(document.id)}


async def test_the_first_run_is_kept_when_it_stops(world: World) -> None:
    s = await scene(world, sure_date=True)
    document = await received(s)
    world.clock.advance(timedelta(minutes=2))
    await world.drain(s.pipeline)

    async with world.uow() as uow:
        run = await uow.processing_facts.first_run(document.id)
        stored = await uow.documents.get(document.id)
    assert stored.first_lane is Lane.GREEN
    assert run is not None
    assert (run.started_at, run.stopped_at) == (NOW, NOW + timedelta(minutes=2))
    assert {Node.RECEIVE, Node.OCR, Node.JUDGE, Node.FILE} <= set(run.steps)


async def test_a_later_run_leaves_the_first_run(world: World) -> None:
    s = await scene(world, sure_date=False)
    document = await received(s)
    await world.drain(s.pipeline)
    async with world.uow() as uow:
        first = await uow.processing_facts.first_run(document.id)
    assert first is not None

    world.clock.advance(timedelta(hours=1))
    await s.pipeline.confirm(s.owner.id, document.id, DocumentChanges(document_date=DATE))
    await world.drain(s.pipeline)

    async with world.uow() as uow:
        assert await uow.processing_facts.first_run(document.id) == first
        assert (await uow.documents.get(document.id)).lane is Lane.GREEN


async def test_confirming_in_the_inbox_judges_every_field(world: World) -> None:
    s = await scene(world, sure_date=False)
    document = await received(s)
    await world.drain(s.pipeline)
    world.clock.advance(timedelta(hours=1))

    await s.pipeline.confirm(s.owner.id, document.id, DocumentChanges(document_date=DATE))

    found = await verdicts(world, document)
    assert {name: item.verdict for name, item in found.items()} == {
        CONTACT: Verdict.TAKEN,
        DOCUMENT_DATE: Verdict.ADDED,
        SPACE: Verdict.TAKEN,  # where it landed, and no check doubted it
    }
    contact = found[CONTACT]
    assert (contact.decision, contact.decided_at) == (Decision.INBOX, world.clock.now())
    assert contact.signals == {Node.SIGNAL_LLM: True, Node.SIGNAL_CLASSIFIER: False}


async def test_confirming_a_document_with_facts_takes_them(world: World) -> None:
    """Confirmed in the inbox, the facts the sources found count as taken."""
    s = await scene(world, sure_date=False)
    document = await received(s)
    await world.drain(s.pipeline)
    fact = DocumentFact(
        kind=IdentifierKind.INVOICE_NUMBER,
        value="4711",
        role=FactRole.OWN,
        origins=frozenset({FactOrigin.PATTERN}),
    )
    async with world.uow() as uow:
        await uow.document_facts.replace_found(document.id, [fact])
        await uow.commit()

    await s.pipeline.confirm(s.owner.id, document.id, DocumentChanges(document_date=DATE))

    assert (await verdicts(world, document))[FACTS].verdict is Verdict.TAKEN


async def test_a_change_judges_what_it_sets_and_what_the_automation_set(world: World) -> None:
    s = await scene(world, sure_date=True)
    document = await received(s)
    await world.drain(s.pipeline)

    await world.documents.change_metadata(
        s.owner.id, document.id, DocumentChanges(contact_id=s.other.id)
    )
    world.clock.advance(timedelta(hours=1))
    await world.documents.change_metadata(
        s.owner.id, document.id, DocumentChanges(contact_id=s.named.id, title="Strom")
    )

    found = await verdicts(world, document)
    assert {name: item.verdict for name, item in found.items()} == {
        CONTACT: Verdict.CORRECTED,  # the first decision stays
        DOCUMENT_DATE: Verdict.TAKEN,
    }
    assert found[CONTACT].decision is Decision.CHANGE
    assert found[CONTACT].signals == {Node.SIGNAL_LLM: False, Node.SIGNAL_CLASSIFIER: True}


async def test_a_change_before_the_first_run_stopped_leaves_nothing_to_judge(
    world: World,
) -> None:
    s = await scene(world, sure_date=True)
    document = await received(s)

    await world.documents.change_metadata(
        s.owner.id, document.id, DocumentChanges(document_date=date(2026, 9, 1))
    )
    await world.drain(s.pipeline)
    await world.documents.change_metadata(
        s.owner.id, document.id, DocumentChanges(document_date=date(2026, 9, 2))
    )

    found = await verdicts(world, document)
    assert found[DOCUMENT_DATE].verdict is Verdict.EARLY
    assert found[CONTACT].verdict is Verdict.TAKEN  # judged at the second change


async def test_tags_set_by_hand_alone_decide_nothing(world: World) -> None:
    s = await scene(world, sure_date=True)
    document = await received(s)
    await world.drain(s.pipeline)
    status = Tag.create(name="to pay", now=NOW, assignment=Assignment.MANUAL)
    async with world.uow() as uow:
        await uow.tags.add(status)
        await uow.commit()

    await world.documents.change_metadata(
        s.owner.id, document.id, DocumentChanges(tag_ids=frozenset({status.id}))
    )

    assert await verdicts(world, document) == {}


async def test_a_move_judges_the_space(world: World) -> None:
    s = await scene(world, sure_date=True)
    document = await received(s)
    await world.drain(s.pipeline)
    archive = await world.spaces.create(s.owner.id, "Archive")

    await world.documents.move(s.owner.id, document.id, archive.id)

    found = await verdicts(world, document)
    assert {name: item.verdict for name, item in found.items()} == {SPACE: Verdict.CORRECTED}
    assert found[SPACE].decision is Decision.MOVE


async def test_a_space_chosen_on_upload_is_not_judged(world: World) -> None:
    s = await scene(world, sure_date=False)
    archive = await world.spaces.create(s.owner.id, "Archive")
    document = await received(s, archive.id)
    await world.drain(s.pipeline)

    await s.pipeline.confirm(s.owner.id, document.id, DocumentChanges(document_date=DATE))
    home = await world.personal_space(s.owner)
    await world.documents.move(s.owner.id, document.id, home.id)

    assert SPACE not in await verdicts(world, document)


async def test_the_space_the_automation_asked_about_since_the_upload_is_judged(
    world: World,
) -> None:
    owner = await world.user()
    archive = await world.spaces.create(owner.id, "Archive")
    home = await world.personal_space(owner)
    s = await scene(world, sure_date=True, space_suggestion=home.id)
    s.owner = owner
    document = await received(s, archive.id)  # chosen on upload
    await world.drain(s.pipeline)

    await s.pipeline.confirm(s.owner.id, document.id, DocumentChanges(), accept_suggestions=True)

    found = await verdicts(world, document)
    assert (found[SPACE].verdict, found[SPACE].decision) == (Verdict.ACCEPTED, Decision.INBOX)
    async with world.uow() as uow:
        assert (await uow.documents.get(document.id)).space_id == home.id
