"""Counts of the document view's filters: what each contact, type, topic, tag and month of the
documents of a filter adds."""

from dataclasses import dataclass
from datetime import date

import pytest

from lekto.core.domain.documents import Document, DocumentChanges
from lekto.core.domain.errors import PermissionDeniedError
from lekto.core.domain.master_data import Contact, DocumentType, Tag, TagScope
from lekto.core.domain.periods import Period
from lekto.core.domain.users import Role, User
from lekto.core.ports.repository import DocumentFilter
from tests.unit.services.search_support import Setup
from tests.unit.services.support import World


@dataclass
class Scene:
    world: World
    admin: User
    owner: User
    nord: Contact
    sued: Contact
    invoice: DocumentType
    insurance: Tag
    health: Tag
    car: Tag
    topic: Tag
    documents: list[Document]


@pytest.fixture
async def scene(world: World) -> Scene:
    """Insurance with Health below it, and Car; the topic Vehicle. The owner's documents: Nord's
    invoice with Health on 30 September in Vehicle, Nord's letter with Car on 1 October, and
    Süd's invoice without a date or tags. A stranger's document lies outside their reach."""
    setup = Setup(world, embeddings=None)
    admin, owner, stranger = (
        await world.user(role=Role.ADMIN),
        await world.user(),
        await world.user(),
    )
    master = setup.master_data
    insurance = await master.create_tag(admin.id, "Insurance")
    health = await master.create_tag(admin.id, "Health", parent_id=insurance.id)
    car = await master.create_tag(admin.id, "Car")
    topic = await master.create_tag(admin.id, "Vehicle", scope=TagScope.TOPIC)
    nord = await master.create_contact(admin.id, "Nord", topic_ids=[topic.id])
    sued = await master.create_contact(admin.id, "Süd")
    invoice = await master.create_document_type(admin.id, "Invoice")
    documents = []
    for number, (user, changes) in enumerate(
        (
            (
                owner,
                DocumentChanges(
                    contact_id=nord.id,
                    document_type_id=invoice.id,
                    tag_ids=frozenset({health.id}),
                    document_date=date(2026, 9, 30),
                    topic_id=topic.id,
                ),
            ),
            (
                owner,
                DocumentChanges(
                    contact_id=nord.id, tag_ids=frozenset({car.id}), document_date=date(2026, 10, 1)
                ),
            ),
            (owner, DocumentChanges(contact_id=sued.id, document_type_id=invoice.id)),
            (stranger, DocumentChanges(contact_id=sued.id)),
        )
    ):
        document = await setup.document(user, f"Schreiben {number}")
        await world.documents.update_metadata(user.id, document.id, changes)
        documents.append(document)
    await setup.settle()
    return Scene(world, admin, owner, nord, sued, invoice, insurance, health, car, topic, documents)


async def test_counts_every_value_of_the_documents_within_reach(scene: Scene) -> None:
    facets = await scene.world.documents.facets(scene.owner.id, DocumentFilter())
    assert facets.total == 3
    assert facets.contacts == {scene.nord.id: 2, scene.sued.id: 1}
    assert facets.document_types == {scene.invoice.id: 2, None: 1}
    # A tag counts the documents with it or one below it.
    assert facets.tags == {scene.insurance.id: 1, scene.health.id: 1, scene.car.id: 1}
    assert facets.topics == {scene.topic.id: 1}
    assert facets.months == {"2026-09": 1, "2026-10": 1}
    assert facets.undated == 1


async def test_an_either_or_group_counts_without_its_own_choice(scene: Scene) -> None:
    only_nord = DocumentFilter(contacts=frozenset({scene.nord.id}))
    facets = await scene.world.documents.facets(scene.owner.id, only_nord)
    assert facets.total == 2
    # Süd still shows what it would add; the other groups follow the choice.
    assert facets.contacts == {scene.nord.id: 2, scene.sued.id: 1}
    assert facets.document_types == {scene.invoice.id: 1, None: 1}
    assert facets.months == {"2026-09": 1, "2026-10": 1}
    assert facets.undated == 0

    september = DocumentFilter(document_dates=Period.month(2026, 9))
    facets = await scene.world.documents.facets(scene.owner.id, september)
    assert facets.total == 1
    assert facets.months == {"2026-09": 1, "2026-10": 1}
    assert facets.undated == 1
    assert facets.contacts == {scene.nord.id: 1}


async def test_tags_count_with_the_whole_filter(scene: Scene) -> None:
    # Insurance, with Health below it: one more tag narrows, so tags count what remains.
    insured = DocumentFilter(tags=(frozenset({scene.insurance.id}),))
    facets = await scene.world.documents.facets(scene.owner.id, insured)
    assert facets.total == 1
    assert facets.tags == {scene.insurance.id: 1, scene.health.id: 1}
    assert facets.contacts == {scene.nord.id: 1}


async def test_every_document_only_for_admins(scene: Scene) -> None:
    with pytest.raises(PermissionDeniedError):
        await scene.world.documents.facets(scene.owner.id, DocumentFilter(), all_users=True)
    facets = await scene.world.documents.facets(scene.admin.id, DocumentFilter(), all_users=True)
    assert facets.total == 4
    assert facets.contacts == {scene.nord.id: 2, scene.sued.id: 2}
