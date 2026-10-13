"""Training the classifier from confirmed documents, its jobs, its status and its prediction."""

from datetime import timedelta

import pytest

from papiq.adapters.outbound.memory import FakeClassifier
from papiq.core.domain.classifier import KEPT_MODELS
from papiq.core.domain.documents import Document, DocumentChanges
from papiq.core.domain.errors import ConflictError, NotFoundError, PermissionDeniedError
from papiq.core.domain.identifiers import IdentifierKind, IdentifierSource
from papiq.core.domain.master_data import Contact
from papiq.core.domain.users import Role, User
from papiq.core.services.classifier import (
    CHECK_JOB,
    TRAIN_JOB,
    ClassifierPolicy,
    ClassifierService,
)
from papiq.core.services.objects import classifier_key, markdown_key
from tests import builders
from tests.unit.services.conftest import World

OWN_IBAN = "DE02 1203 0000 0000 2020 51"
THEIR_IBAN = "DE89 3704 0044 0532 0130 00"


def service(world: World, **policy: object) -> ClassifierService:
    values = {"min_examples": 4, "retrain_after": 2, **policy}
    return ClassifierService(
        world.uow,
        world.object_store,
        world.clock,
        FakeClassifier(),
        ClassifierPolicy(**values),  # type: ignore[arg-type]
    )


async def confirmed(world: World, owner: User, contact: Contact, text: str) -> Document:
    drawer = await world.default_drawer(owner)
    document = builders.processed(owner, drawer, content=text)
    document.apply_changes(DocumentChanges(contact_id=contact.id), {}, world.clock.now())
    document.mark_confirmed(world.clock.now())
    async with world.uow() as uow:
        await uow.documents.add(document)
        await uow.commit()
    await world.object_store.put(
        markdown_key(document.id), text.encode(), content_type="text/markdown"
    )
    return document


async def corpus(world: World) -> tuple[User, Contact, Contact]:
    owner = await world.user()
    utility = Contact.create(name="Stadtwerke", now=builders.NOW)
    bank = Contact.create(name="Beispielbank", now=builders.NOW)
    async with world.uow() as uow:
        await uow.contacts.add(utility)
        await uow.contacts.add(bank)
        await uow.commit()
    for number in range(2):
        await confirmed(
            world,
            owner,
            utility,
            f"Stadtwerke Stromrechnung Zählerstand {number} IBAN {THEIR_IBAN} von {OWN_IBAN}",
        )
        await confirmed(world, owner, bank, f"Beispielbank Kontoauszug Saldo {number} {OWN_IBAN}")
    return owner, utility, bank


async def test_training_learns_from_the_confirmed_documents(world: World) -> None:
    _, utility, bank = await corpus(world)
    classifier = service(world)
    model = await classifier.train()
    assert (model.number, model.examples) == (1, 4)
    assert model.examples_until == world.clock.now()
    assert model.summary["learned_identifiers"] == 1
    assert await world.object_store.get(classifier_key(1))
    async with world.uow() as uow:
        learned = (await uow.contacts.get(utility.id)).identifiers
        # The owner's own IBAN stands in both contacts' documents: never learned.
        assert [(item.kind, item.source) for item in learned] == [
            (IdentifierKind.IBAN, IdentifierSource.LEARNED)
        ]
        assert (await uow.contacts.get(bank.id)).identifiers == []
    predicted = await classifier.predict("Stadtwerke Zählerstand Stromrechnung")
    assert predicted is not None
    assert predicted[1].contacts[0][0] == utility.id


async def test_old_models_go(world: World) -> None:
    await corpus(world)
    classifier = service(world)
    for _ in range(KEPT_MODELS + 1):
        latest = await classifier.train()
    assert latest.number == KEPT_MODELS + 1
    async with world.uow() as uow:
        numbers = [model.number for model in await uow.classifier_models.list_all()]
    assert numbers == list(range(KEPT_MODELS + 1, 1, -1))
    with pytest.raises(NotFoundError):
        await world.object_store.get(classifier_key(1))


async def test_the_check_queues_a_training_when_enough_was_confirmed(world: World) -> None:
    owner, utility, _ = await corpus(world)
    classifier = service(world, min_examples=5)
    assert not await classifier.check()
    await confirmed(world, owner, utility, "Stadtwerke Abschlag")
    assert await classifier.check()
    await classifier.schedule()
    assert await classifier.run_next_job()  # the check, which queues the next one
    queued = [job.kind for job in world.database.jobs.values() if job.status.is_active]
    assert TRAIN_JOB in queued and CHECK_JOB in queued
    assert await classifier.run_next_job()  # the training
    async with world.uow() as uow:
        assert (await uow.classifier_models.latest()) is not None
    # One confirmation since: not enough for another.
    world.clock.advance(timedelta(minutes=1))
    await confirmed(world, owner, utility, "Stadtwerke Jahresabrechnung")
    assert not await classifier.check()


async def test_status_and_training_on_request_are_for_admins(world: World) -> None:
    admin, user = await world.user(role=Role.ADMIN), await world.user()
    classifier = service(world)
    with pytest.raises(PermissionDeniedError):
        await classifier.status(user.id)
    with pytest.raises(PermissionDeniedError):
        await classifier.request_training(user.id)
    with pytest.raises(ConflictError):  # too few confirmed documents
        await classifier.request_training(admin.id)
    await corpus(world)
    await classifier.request_training(admin.id)
    await classifier.request_training(admin.id)  # queued once
    status = await classifier.status(admin.id)
    assert (status.model, status.confirmed, status.since) == (None, 4, 4)
