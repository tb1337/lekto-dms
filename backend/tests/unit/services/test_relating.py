"""Recognising relations (#145 PR 11, `services.relating`): the sources, how sure each is, both
directions, and what a person decided stays."""

from datetime import date

from lekto.core.domain.document_facts import DocumentFact, FactOrigin, FactRole
from lekto.core.domain.documents import Document, DocumentChanges
from lekto.core.domain.fields import FieldDefinition, FieldType
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import ContactId, DocumentTypeId
from lekto.core.domain.master_data import Contact, DocumentType
from lekto.core.domain.periods import Period
from lekto.core.domain.pipeline import Node
from lekto.core.domain.relations import Relation, RelationOrigin, RelationState
from lekto.core.domain.rules import AddTags, Condition, ConditionField, Operator
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import User
from lekto.core.services.classification.signals import FactsSignal
from lekto.core.services.relating import RELATE, RELATIONS_LOCK, relate
from lekto.core.services.relations import RelationService
from tests import builders
from tests.unit.services.rules_support import Classifies, definition, rule_world
from tests.unit.services.support import World

K = IdentifierKind
NOW = builders.NOW


class Scene:
    """A user's documents with contacts, types, dates, fields and facts, stored directly."""

    def __init__(self, world: World, owner: User, space: Space) -> None:
        self.world, self.owner, self.space = world, owner, space

    @classmethod
    async def of(cls, world: World) -> "Scene":
        owner = await world.user()
        return cls(world, owner, await world.personal_space(owner))

    async def contact(self, name: str) -> ContactId:
        contact = Contact.create(name=name, now=NOW)
        async with self.world.uow() as uow:
            await uow.contacts.add(contact)
            await uow.commit()
        return contact.id

    async def document_type(self, name: str, *, target: bool = False) -> DocumentTypeId:
        kind = DocumentType.create(name=name, now=NOW, relation_target=target)
        async with self.world.uow() as uow:
            await uow.document_types.add(kind)
            await uow.commit()
        return kind.id

    async def document(
        self,
        *,
        contact: ContactId | None = None,
        kind: DocumentTypeId | None = None,
        dated: date | None = None,
        facts: tuple[tuple[K, str, FactRole], ...] = (),
        fields: tuple[tuple[FieldDefinition, object], ...] = (),
    ) -> Document:
        document = builders.processed(self.owner, self.space)
        definitions = {item.id: item for item, _ in fields}
        document.apply_changes(
            DocumentChanges(
                contact_id=contact,
                document_type_id=kind,
                document_date=dated,
                fields={item.id: value for item, value in fields},
            ),
            definitions,
            NOW,
        )
        async with self.world.uow() as uow:
            await uow.documents.add(document)
            await uow.document_facts.replace_found(
                document.id,
                [
                    DocumentFact(
                        kind=kind_,
                        value=value,
                        role=role,
                        origins=frozenset({FactOrigin.PATTERN}),
                        written=value,
                        position=0,
                    )
                    for kind_, value, role in facts
                ],
            )
            await uow.commit()
        return document

    async def relate(self, document: Document) -> list[Relation]:
        async with self.world.uow() as uow:
            await uow.lock(RELATIONS_LOCK)
            made = await relate(uow, document, NOW)
            await uow.commit()
        return made

    async def relations(self, document: Document) -> list[Relation]:
        async with self.world.uow() as uow:
            return await uow.document_relations.of_document(document.id)


def pairs(relations: list[Relation]) -> set[tuple[object, object, RelationState]]:
    return {(item.newer, item.older, item.state) for item in relations}


async def test_a_reminder_refers_to_the_invoice_whose_number_it_names(world: World) -> None:
    s = await Scene.of(world)
    shop = await s.contact("Versandhaus")
    invoice = await s.document(
        contact=shop, dated=date(2026, 5, 12), facts=((K.INVOICE_NUMBER, "VB889911", FactRole.OWN),)
    )
    reminder = await s.document(
        contact=shop,
        dated=date(2026, 6, 10),
        facts=((K.INVOICE_NUMBER, "VB889911", FactRole.REFERS),),
    )
    made = await s.relate(reminder)
    assert pairs(made) == {(reminder.id, invoice.id, RelationState.SET)}
    assert made[0].origin is RelationOrigin.LEKTO
    assert made[0].evidence == {
        "kind": "fact",
        "fact_kind": "invoice_number",
        "value": "VB889911",
    }
    # Once more: nothing new.
    assert await s.relate(reminder) == []


async def test_the_invoice_coming_later_finds_the_reminder(world: World) -> None:
    s = await Scene.of(world)
    shop = await s.contact("Versandhaus")
    reminder = await s.document(
        contact=shop,
        dated=date(2026, 6, 10),
        facts=((K.INVOICE_NUMBER, "VB889911", FactRole.REFERS),),
    )
    invoice = await s.document(
        contact=shop, dated=date(2026, 5, 12), facts=((K.INVOICE_NUMBER, "VB889911", FactRole.OWN),)
    )
    assert pairs(await s.relate(invoice)) == {(reminder.id, invoice.id, RelationState.SET)}


async def test_another_contact_is_no_relation_and_two_owners_only_suggestions(
    world: World,
) -> None:
    s = await Scene.of(world)
    shop, other = await s.contact("Versandhaus"), await s.contact("Stadtwerke")
    await s.document(
        contact=other, dated=date(2026, 5, 1), facts=((K.INVOICE_NUMBER, "4711", FactRole.OWN),)
    )
    first = await s.document(
        contact=shop, dated=date(2026, 5, 2), facts=((K.INVOICE_NUMBER, "4711", FactRole.OWN),)
    )
    second = await s.document(
        contact=shop, dated=date(2026, 5, 3), facts=((K.INVOICE_NUMBER, "4711", FactRole.OWN),)
    )
    reminder = await s.document(
        contact=shop, dated=date(2026, 6, 1), facts=((K.INVOICE_NUMBER, "4711", FactRole.REFERS),)
    )
    assert pairs(await s.relate(reminder)) == {
        (reminder.id, first.id, RelationState.SUGGESTED),
        (reminder.id, second.id, RelationState.SUGGESTED),
    }


async def test_a_contract_number_connects_only_with_a_relation_target(world: World) -> None:
    s = await Scene.of(world)
    insurer = await s.contact("Nord Versicherung")
    policy = await s.document_type("Police", target=True)
    bill = await s.document_type("Beitragsrechnung")
    number = ((K.POLICY_NUMBER, "KV123456", FactRole.TARGET),)
    first = await s.document(contact=insurer, kind=bill, dated=date(2026, 1, 5), facts=number)
    second = await s.document(contact=insurer, kind=bill, dated=date(2026, 2, 5), facts=number)
    # Two bills with the policy number: no relation between them.
    assert await s.relate(second) == []
    contract = await s.document(contact=insurer, kind=policy, dated=date(2025, 12, 1), facts=number)
    made = await s.relate(contract)
    assert pairs(made) == {
        (first.id, contract.id, RelationState.SET),
        (second.id, contract.id, RelationState.SET),
    }
    assert made[0].evidence["kind"] == "target"


async def test_a_correction_refers_to_the_original_of_the_same_period(world: World) -> None:
    s = await Scene.of(world)
    employer = await s.contact("Arbeitgeber")
    payslip = await s.document_type("Lohnabrechnung")
    period = FieldDefinition.create(name="Bezugszeitraum", data_type=FieldType.PERIOD, now=NOW)
    async with world.uow() as uow:
        await uow.fields.add(period)
        await uow.commit()
    september = Period(date(2026, 9, 1), date(2026, 9, 30))
    original = await s.document(
        contact=employer, kind=payslip, dated=date(2026, 9, 30), fields=((period, september),)
    )
    await s.document(
        contact=employer,
        kind=payslip,
        dated=date(2026, 10, 31),
        fields=((period, Period(date(2026, 10, 1), date(2026, 10, 31))),),
    )
    correction = await s.document(
        contact=employer, kind=payslip, dated=date(2026, 11, 15), fields=((period, september),)
    )
    made = await s.relate(correction)
    assert pairs(made) == {(correction.id, original.id, RelationState.SET)}
    assert made[0].evidence == {"kind": "period", "field_id": str(period.id), "period": "2026-09"}
    # Another person's payslip of the month (another personnel number) is none.
    mine = ((K.PERSONNEL_NUMBER, "4711", FactRole.CONTACT),)
    theirs = ((K.PERSONNEL_NUMBER, "4712", FactRole.CONTACT),)
    october = Period(date(2026, 10, 1), date(2026, 10, 31))
    await s.document(
        contact=employer,
        kind=payslip,
        dated=date(2026, 10, 30),
        fields=((period, october),),
        facts=mine,
    )
    partner = await s.document(
        contact=employer,
        kind=payslip,
        dated=date(2026, 10, 31),
        fields=((period, october),),
        facts=theirs,
    )
    assert await s.relate(partner) == []


async def test_a_letter_answering_a_letter_of_a_day(world: World) -> None:
    s = await Scene.of(world)
    insurer = await s.contact("Nord Versicherung")
    letter = await s.document(contact=insurer, dated=date(2026, 5, 18))
    answer = await s.document(
        contact=insurer,
        dated=date(2026, 6, 10),
        facts=((K.LETTER_DATE, "2026-05-18", FactRole.REFERS),),
    )
    assert pairs(await s.relate(answer)) == {(answer.id, letter.id, RelationState.SET)}


async def test_what_a_person_decided_stays(world: World) -> None:
    """A rejected suggestion is not made again; a suggestion becomes set when a source is sure."""
    s = await Scene.of(world)
    shop = await s.contact("Versandhaus")
    invoice = await s.document(
        contact=shop, dated=date(2026, 5, 12), facts=((K.INVOICE_NUMBER, "VB1", FactRole.OWN),)
    )
    reminder = await s.document(
        contact=shop, dated=date(2026, 6, 10), facts=((K.INVOICE_NUMBER, "VB1", FactRole.REFERS),)
    )
    await s.relate(reminder)
    await RelationService(world.uow, world.clock).unrelate(s.owner.id, reminder.id, invoice.id)
    assert await s.relate(reminder) == []
    (kept,) = await s.relations(invoice)
    assert kept.state is RelationState.REJECTED


async def test_the_node_relates_a_reminder_on_arrival(world: World) -> None:
    """In processing, after the fields and before the rules; again by `lekto relate`."""
    r = await rule_world(world)
    owner = await world.user()
    facts = FactsSignal(world.uow, world.object_store)
    invoice = await r.arrive(owner, text="Rechnungsnummer: VB-889911", facts=facts)
    reminder = await r.arrive(owner, text="Ihre Rechnung Nr. VB-889911 ist offen.", facts=facts)
    async with world.uow() as uow:
        (relation,) = await uow.document_relations.of_document(invoice.id)
    # Neither has a contact: only a suggestion.
    assert (relation.newer, relation.older) == (reminder.id, invoice.id)
    assert relation.state is RelationState.SUGGESTED
    (entry,) = [item for item in await r.log(reminder) if item.node is Node.RELATE]
    assert entry.result.model_version == RELATE
    assert entry.result.output["relations"] == [
        {
            "document_id": str(invoice.id),
            "direction": "refers_to",
            "state": "suggested",
            "evidence": {"kind": "fact", "fact_kind": "invoice_number", "value": "VB-889911"},
        }
    ]
    pipeline = r.pipeline(facts=facts)
    assert await pipeline.request_relations() == 2
    assert await world.drain(pipeline) == 2


async def test_the_rules_of_the_run_see_the_relation(world: World) -> None:
    """`relate` runs before the rules: a rule on a relation to an invoice tags the reminder."""
    r = await rule_world(world)
    owner = await world.user()
    shop = await r.contact("Versandhaus")
    invoice_type = await world.master_data.create_document_type(r.admin.id, "Rechnung")
    reminder_tag = await r.tag("Mahnung")
    refers = Condition(field=ConditionField.RELATION, op=Operator.IS, value=str(invoice_type.id))
    await r.personal_rule(
        owner, definition("Mahnungen", refers, AddTags(frozenset({reminder_tag.id})))
    )
    facts = FactsSignal(world.uow, world.object_store)
    await r.arrive(
        owner,
        text="Rechnungsnummer: VB-889911",
        facts=facts,
        classify=Classifies(contact=shop.id, document_type=invoice_type.id),
    )
    reminder = await r.arrive(
        owner,
        text="Ihre Rechnung Nr. VB-889911 ist offen.",
        facts=facts,
        classify=Classifies(contact=shop.id),
    )
    assert reminder_tag.id in reminder.tag_ids
