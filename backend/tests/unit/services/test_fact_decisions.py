"""A person's decisions about the facts of a document (#145 PR 6): adding, correcting,
rejecting and withdrawing, who may, what outlasts a new run of the facts signal, the verdict on
the facts, and an admin's correction at the contact too."""

import pytest

from lekto.adapters.outbound.memory import FakeCodeReader
from lekto.core.domain.document_facts import FactOrigin, FactRole, FactState
from lekto.core.domain.documents import Document
from lekto.core.domain.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from lekto.core.domain.first_runs import FACTS, Verdict
from lekto.core.domain.identifiers import Identifier, IdentifierKind, IdentifierSource
from lekto.core.domain.identifiers.visibility import seen_by
from lekto.core.domain.master_data import Contact
from lekto.core.domain.spaces import SpaceRole
from lekto.core.domain.users import Role, User
from lekto.core.services.classification.signals import FactsSignal
from lekto.core.services.fact_decisions import FactAction, FactDecision
from lekto.core.services.master_data import replace_learned_identifiers
from lekto.core.services.objects import text_key
from tests import builders
from tests.unit.services.support import World
from tests.unit.services.test_signals import contacts, stored

K = IdentifierKind
TEXT = "Mahnung\nRechnungsnummer: M-77\nIhre Rechnung Nr. 4711 ist offen.\nKundennummer 20047718\n"


async def run_facts(world: World, document: Document) -> None:
    result = await FactsSignal(world.uow, world.object_store, FakeCodeReader([])).run(document)
    async with world.uow() as uow:
        await result.apply(uow, await uow.documents.get(document.id), builders.NOW)  # type: ignore[union-attr]
        await uow.commit()


async def with_facts(world: World, owner: User, contact: Contact | None = None) -> Document:
    document = await stored(world, owner, TEXT, contact)
    await run_facts(world, document)
    return document


async def kept(world: World, document: Document) -> dict[tuple[K, str], object]:
    async with world.uow() as uow:
        return {
            fact.key: (fact.role, fact.state, fact.origins)
            for fact in await uow.document_facts.of_document(document.id)
        }


def decide(action: FactAction, kind: K, value: str, **given: object) -> FactDecision:
    return FactDecision(action=action, kind=kind, value=value, **given)  # type: ignore[arg-type]


async def test_a_person_adds_corrects_rejects_and_withdraws(world: World) -> None:
    owner = await world.user()
    document = await with_facts(world, owner)
    service = world.documents
    pattern = frozenset({FactOrigin.PATTERN})
    person = frozenset({FactOrigin.PERSON})

    # The reminder's own number stands nowhere the patterns read it: added, where it stands.
    await service.decide_fact(
        owner.id,
        document.id,
        decide(FactAction.ADD, K.ORDER_NUMBER, "A 77881", role=FactRole.OWN),
    )
    # The invoice it refers to: the role corrected; its own number: the value.
    await service.decide_fact(
        owner.id,
        document.id,
        decide(FactAction.CORRECT, K.INVOICE_NUMBER, "M77", new_value="M-78"),
    )
    await service.decide_fact(
        owner.id,
        document.id,
        decide(FactAction.CORRECT, K.INVOICE_NUMBER, "4711", role=FactRole.THREAD),
    )
    await service.decide_fact(
        owner.id, document.id, decide(FactAction.REJECT, K.CUSTOMER_NUMBER, "20047718")
    )
    assert await kept(world, document) == {
        (K.INVOICE_NUMBER, "M77"): (FactRole.OWN, FactState.REJECTED, pattern | person),
        (K.INVOICE_NUMBER, "M78"): (FactRole.OWN, FactState.CORRECTED, person),
        (K.INVOICE_NUMBER, "4711"): (FactRole.THREAD, FactState.CORRECTED, pattern | person),
        (K.CUSTOMER_NUMBER, "20047718"): (
            FactRole.CONTACT,
            FactState.REJECTED,
            pattern | person,
        ),
        (K.ORDER_NUMBER, "A77881"): (FactRole.OWN, FactState.ADDED, person),
    }

    # A new run of the facts signal leaves the person's decisions as they are.
    before = await kept(world, document)
    await run_facts(world, document)
    assert await kept(world, document) == before

    # Withdrawn: a fact is as the sources find it now (its role too), one only a person gave
    # goes.
    for key in (
        (K.CUSTOMER_NUMBER, "20047718"),
        (K.ORDER_NUMBER, "A77881"),
        (K.INVOICE_NUMBER, "4711"),
    ):
        await service.decide_fact(owner.id, document.id, decide(FactAction.WITHDRAW, *key))
    after = await kept(world, document)
    assert after[(K.CUSTOMER_NUMBER, "20047718")] == (FactRole.CONTACT, FactState.FOUND, pattern)
    assert after[(K.INVOICE_NUMBER, "4711")] == (FactRole.REFERS, FactState.FOUND, pattern)
    assert (K.ORDER_NUMBER, "A77881") not in after

    # The report shows the rejected number and that the owner decides.
    report = await service.facts(owner.id, document.id)
    assert report.editable
    states = {item.fact.value: item.fact.state for item in report.numbers}
    assert states["M77"] is FactState.REJECTED and states["M78"] is FactState.CORRECTED


async def test_what_a_decision_needs(world: World) -> None:
    owner = await world.user()
    document = await with_facts(world, owner)
    service = world.documents
    cases: list[tuple[FactDecision, type[Exception]]] = [
        (decide(FactAction.ADD, K.INVOICE_NUMBER, "M-77", role=FactRole.OWN), ConflictError),
        (decide(FactAction.ADD, K.INVOICE_NUMBER, "M-99"), ValidationError),  # no role
        (decide(FactAction.ADD, K.CREDITOR_ID, "DE00ZZZ1", role=FactRole.CONTACT), ValidationError),
        (decide(FactAction.REJECT, K.INVOICE_NUMBER, "9999"), NotFoundError),
        (
            decide(FactAction.CORRECT, K.INVOICE_NUMBER, "M77", at_contact=True),
            PermissionDeniedError,
        ),
        (
            decide(FactAction.ADD, K.TAX_ID, "86095742001", role=FactRole.PERSON),
            PermissionDeniedError,
        ),
    ]
    for decision, error in cases:
        with pytest.raises(error):
            await service.decide_fact(owner.id, document.id, decision)


async def test_only_editors_and_admins_decide(world: World) -> None:
    owner, reader, admin = await world.user(), await world.user(), await world.user(role=Role.ADMIN)
    shared = await world.spaces.create(owner.id, "Shared")
    await world.spaces.set_member(owner.id, shared.id, reader.id, SpaceRole.READ)
    document = builders.processed(owner, shared, content="shared reminder")
    async with world.uow() as uow:
        await uow.documents.add(document)
        await uow.commit()
    await world.object_store.put(text_key(document.id), TEXT.encode(), content_type="text/md")
    await run_facts(world, document)
    reject = decide(FactAction.REJECT, K.INVOICE_NUMBER, "M77")
    with pytest.raises(PermissionDeniedError):
        await world.documents.decide_fact(reader.id, document.id, reject)
    assert not (await world.documents.facts(reader.id, document.id)).editable
    await world.documents.decide_fact(admin.id, document.id, reject)


async def test_the_first_decision_about_the_facts_is_a_verdict(world: World) -> None:
    owner = await world.user()
    document = await with_facts(world, owner)
    await world.documents.decide_fact(
        owner.id, document.id, decide(FactAction.REJECT, K.INVOICE_NUMBER, "M77")
    )
    await world.documents.decide_fact(
        owner.id, document.id, decide(FactAction.ADD, K.ORDER_NUMBER, "A 100", role=FactRole.OWN)
    )
    async with world.uow() as uow:
        verdicts = await uow.processing_facts.verdicts(document.id)
    assert [(item.field, item.verdict) for item in verdicts] == [(FACTS, Verdict.CORRECTED)]


async def test_a_rejected_fact_is_no_evidence_of_a_contact(world: World) -> None:
    number = Identifier.parse(K.CUSTOMER_NUMBER, "20047718")
    bank = Contact.create(name="Bank", now=builders.NOW, identifiers=[number])
    await contacts(world, bank)
    owner = await world.user()
    document = await with_facts(world, owner)
    await world.documents.decide_fact(
        owner.id, document.id, decide(FactAction.REJECT, K.CUSTOMER_NUMBER, "20047718")
    )
    result = await FactsSignal(world.uow, world.object_store, FakeCodeReader([])).run(document)
    assert result.output["identifiers"] == []


async def test_an_admin_corrects_a_number_at_the_contact_too(world: World) -> None:
    """The old value is rejected there; one entered by hand gives way to one entered by hand."""
    entered = Identifier(K.CUSTOMER_NUMBER, "20047718")
    bank = Contact.create(name="Bank", now=builders.NOW, identifiers=[entered])
    await contacts(world, bank)
    admin = await world.user(role=Role.ADMIN)
    document = await with_facts(world, await world.user(), bank)
    await world.documents.decide_fact(
        admin.id,
        document.id,
        decide(
            FactAction.CORRECT,
            K.CUSTOMER_NUMBER,
            "20047718",
            new_value="20047719",
            at_contact=True,
        ),
    )
    async with world.uow() as uow:
        identifiers = (await uow.contacts.get(bank.id)).identifiers
    assert sorted((item.value, item.source) for item in identifiers) == [
        ("20047718", IdentifierSource.REJECTED),
        ("20047719", IdentifierSource.MANUAL),
    ]
    # Only on a document with a contact and for a contact's kind.
    with pytest.raises(ValidationError):
        await world.documents.decide_fact(
            admin.id,
            document.id,
            decide(FactAction.CORRECT, K.INVOICE_NUMBER, "M77", new_value="M-1", at_contact=True),
        )


async def test_a_learned_number_corrected_at_the_contact_stays_learned_where_it_was(
    world: World,
) -> None:
    """Who saw the old value sees the new one (#82): learned in the owner's space only, the
    corrected one too; the wrong one is rejected, so training does not learn it again."""
    bank = Contact.create(name="Bank", now=builders.NOW)
    await contacts(world, bank)
    admin, owner, other = (
        await world.user(role=Role.ADMIN),
        await world.user(),
        await world.user(),
    )
    space = await world.personal_space(owner)
    learned = Identifier(
        K.CUSTOMER_NUMBER,
        "20047718",
        IdentifierSource.LEARNED,
        learned_in=frozenset({space.id}),
    )
    async with world.uow() as uow:
        await replace_learned_identifiers(uow, {bank.id: [learned]})
        await uow.commit()
    document = await with_facts(world, owner, bank)
    await world.documents.decide_fact(
        admin.id,
        document.id,
        decide(
            FactAction.CORRECT,
            K.CUSTOMER_NUMBER,
            "20047718",
            new_value="20047719",
            at_contact=True,
        ),
    )
    async with world.uow() as uow:
        identifiers = {item.value: item for item in (await uow.contacts.get(bank.id)).identifiers}
    assert identifiers["20047718"].source is IdentifierSource.REJECTED
    corrected = identifiers["20047719"]
    assert (corrected.source, corrected.learned_in) == (
        IdentifierSource.LEARNED,
        frozenset({space.id}),
    )
    assert seen_by(corrected, owner.id, {space.id})
    assert not seen_by(corrected, other.id, set())


async def test_a_decision_before_the_first_run_stopped_is_early(world: World) -> None:
    owner = await world.user()
    document = await stored(world, owner, TEXT)
    await run_facts(world, document)
    async with world.uow() as uow:
        current = await uow.documents.get(document.id)
        # Still in its first run: the first stop is not recorded yet.
        current.processing.run = 1
        current.first_lane = None
        await uow.documents.update(current)
        await uow.commit()
    await world.documents.decide_fact(
        owner.id, document.id, decide(FactAction.REJECT, K.INVOICE_NUMBER, "M77")
    )
    async with world.uow() as uow:
        verdicts = await uow.processing_facts.verdicts(document.id)
    assert [(item.field, item.verdict) for item in verdicts] == [(FACTS, Verdict.EARLY)]


async def test_admins_see_and_decide_the_found_facts_of_a_person(world: World) -> None:
    """A tax ID the patterns found is in no list of identifiers: admins see it among the
    further facts and decide it; others never see a person's."""
    owner, admin = await world.user(), await world.user(role=Role.ADMIN)
    document = await stored(world, owner, "Steuer-ID 86 095 742 001\nRechnungsnummer: M-77")
    await run_facts(world, document)
    tax = (K.TAX_ID, "86095742001")
    seen = await world.documents.facts(admin.id, document.id)
    assert tax in {item.fact.key for item in seen.decided}
    assert tax not in {
        item.fact.key for item in (await world.documents.facts(owner.id, document.id)).decided
    }
    await world.documents.decide_fact(admin.id, document.id, decide(FactAction.REJECT, *tax))
