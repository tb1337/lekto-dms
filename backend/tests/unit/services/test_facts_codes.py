"""The codes on a document's pages in the facts: read once from the archive and kept, their
identifiers and payee as evidence, the identifiers a document shows kept for it, and reading the
facts of documents from before (`read-codes`)."""

from pathlib import Path

from lekto.adapters.outbound.memory import FAKE_GIRO_CODE, FakeCodeReader, FakeOcr
from lekto.adapters.outbound.memory.processing import FAKE_PDF
from lekto.core.domain.codes import Code
from lekto.core.domain.document_facts import FactOrigin, FactRole
from lekto.core.domain.documents import Document
from lekto.core.domain.identifiers import Identifier, IdentifierKind
from lekto.core.domain.ids import ContactId
from lekto.core.domain.master_data import Contact
from lekto.core.domain.pipeline import Node
from lekto.core.domain.users import Role
from lekto.core.ports.codes import CodeReading
from lekto.core.services.classification.signals import FactsResult, FactsSignal
from lekto.core.services.nodes import OcrNode
from lekto.core.services.objects import archive_key, codes_key, original_key
from tests import builders
from tests.unit.services.support import World
from tests.unit.services.test_signals import contacts, stored

GIRO_IBAN = "DE89370400440532013000"
OWN_IBAN = "DE02120300000000202051"
TEXT = f"Lekto Test GmbH\nRechnung 4711\nLastschrift von {OWN_IBAN}\n"


async def with_archive(world: World, document: Document) -> Document:
    await world.object_store.put(archive_key(document.id), FAKE_PDF, content_type="application/pdf")
    return document


async def facts(world: World, document: Document, reader: FakeCodeReader) -> FactsResult:
    result = await FactsSignal(world.uow, world.object_store, reader).run(document)
    assert isinstance(result, FactsResult)
    return result


async def test_the_identifiers_and_the_payee_of_a_code_count(world: World) -> None:
    iban = Identifier.parse(IdentifierKind.IBAN, GIRO_IBAN)
    payee = Contact.create(name="Lekto Test GmbH", now=builders.NOW, identifiers=[iban])
    await contacts(world, payee)
    text = "Rechnung 4711\nBetrag 123,45 EUR\n"  # neither the payee nor its IBAN in the text
    document = await with_archive(world, await stored(world, await world.user(), text))
    result = await facts(world, document, FakeCodeReader([FAKE_GIRO_CODE]))
    assert result.output["named"] == [
        {"contact_id": str(payee.id), "name": "Lekto Test GmbH", "alias": False, "in_code": True}
    ]
    assert result.output["identifiers"] == [
        {"contact_id": str(payee.id), "kind": "iban", "value": GIRO_IBAN, "in_code": True}
    ]
    assert result.output["codes"] == 1
    assert {fact.key for fact in result.facts} == {(IdentifierKind.IBAN, GIRO_IBAN)}


async def test_the_codes_are_read_once_and_again_with_a_new_archive(world: World) -> None:
    reader = FakeCodeReader([FAKE_GIRO_CODE])
    document = await with_archive(world, await stored(world, await world.user(), TEXT))
    await facts(world, document, reader)
    await facts(world, document, reader)
    assert len(reader.calls) == 1
    assert await world.object_store.exists(codes_key(document.id))
    # The OCR writes a new archive: its codes are read again.
    await world.object_store.put(
        original_key(document.sha256), FAKE_PDF, content_type="application/pdf"
    )
    await OcrNode(world.object_store, FakeOcr()).run(document)
    assert not await world.object_store.exists(codes_key(document.id))
    await facts(world, document, reader)
    assert len(reader.calls) == 2


class Broken(FakeCodeReader):
    async def read_codes(self, source: Path) -> CodeReading:
        raise RuntimeError("the reader broke")


async def test_codes_that_cannot_be_read_leave_the_facts_of_the_text(world: World) -> None:
    document = await with_archive(world, await stored(world, await world.user(), TEXT))
    result = await facts(world, document, Broken())
    assert "codes" not in result.output
    assert {fact.key for fact in result.facts} == {(IdentifierKind.IBAN, OWN_IBAN)}
    assert not await world.object_store.exists(codes_key(document.id))
    # Without an archive (or a reader) there are no codes either.
    other = await stored(world, await world.user(), TEXT)
    assert "codes" not in (await facts(world, other, FakeCodeReader([FAKE_GIRO_CODE]))).output


async def confirmed(world: World, contact: Contact, codes: list[Code]) -> Document:
    """A document of `contact` whose facts ran in its processing, then confirmed."""
    owner = await world.user()
    document = await with_archive(world, await stored(world, owner, TEXT, contact))
    result = await facts(world, document, FakeCodeReader(codes))
    async with world.uow() as uow:
        current = await uow.documents.get(document.id)
        await result.apply(uow, current, builders.NOW)
        current.mark_confirmed(builders.NOW)
        await uow.documents.update(current)
        await uow.commit()
    return document


async def contacts_of(world: World, iban: str) -> frozenset[ContactId]:
    key = (IdentifierKind.IBAN, iban)
    async with world.uow() as uow:
        return (await uow.document_facts.contacts_of([key])).get(key, frozenset())


async def test_the_identifiers_a_document_shows_are_kept(world: World) -> None:
    utility, bank = (Contact.create(name=name, now=builders.NOW) for name in ("Werke", "Bank"))
    await contacts(world, utility, bank)
    await confirmed(world, utility, [FAKE_GIRO_CODE])
    await confirmed(world, bank, [])
    # The owner's own IBAN stands on both; the GiroCode's only on the utility's.
    assert await contacts_of(world, OWN_IBAN) == {utility.id, bank.id}
    assert await contacts_of(world, GIRO_IBAN) == {utility.id}


async def test_the_facts_keep_where_they_come_from_and_their_role(world: World) -> None:
    """The text's IBAN by its pattern, where it stands and as written; the GiroCode's by the
    code; both with the role of their kind; the report names both."""
    utility = Contact.create(name="Werke", now=builders.NOW)
    await contacts(world, utility)
    document = await confirmed(world, utility, [FAKE_GIRO_CODE])
    async with world.uow() as uow:
        kept = {fact.value: fact for fact in await uow.document_facts.of_document(document.id)}
    own, giro = kept[OWN_IBAN], kept[GIRO_IBAN]
    assert (own.origins, own.role) == (frozenset({FactOrigin.PATTERN}), FactRole.CONTACT)
    assert own.position is not None and own.written is not None
    assert TEXT[own.position :].startswith(own.written)
    assert (giro.origins, giro.position) == (frozenset({FactOrigin.CODE}), None)
    report = await world.documents.facts((await world.user(role=Role.ADMIN)).id, document.id)
    assert report.stored[(IdentifierKind.IBAN, GIRO_IBAN)].origins == {FactOrigin.CODE}


async def test_admins_learn_which_other_contacts_show_an_identifier(world: World) -> None:
    utility, bank = (Contact.create(name=name, now=builders.NOW) for name in ("Werke", "Bank"))
    await contacts(world, utility, bank)
    await confirmed(world, utility, [FAKE_GIRO_CODE])
    await confirmed(world, bank, [])
    document = await with_archive(world, await stored(world, await world.user(), TEXT, utility))
    admin = await world.user(role=Role.ADMIN)
    report = await world.documents.facts(admin.id, document.id)
    assert report.other_contacts is not None
    # The owner's own IBAN stands on the bank's documents too, never counting the utility.
    assert report.other_contacts[(IdentifierKind.IBAN, OWN_IBAN)] == {bank.id}
    assert document.uploaded_by is not None
    assert (await world.documents.facts(document.uploaded_by, document.id)).other_contacts is None


async def test_read_codes_reads_the_facts_of_documents_from_before(world: World) -> None:
    utility = Contact.create(name="Werke", now=builders.NOW)
    await contacts(world, utility)
    owner = await world.user()
    document = await with_archive(world, await stored(world, owner, TEXT, utility))
    async with world.uow() as uow:
        current = await uow.documents.get(document.id)
        current.mark_confirmed(builders.NOW)
        await uow.documents.update(current)
        await uow.commit()
    reader = FakeCodeReader([FAKE_GIRO_CODE])
    pipeline = world.pipeline(facts=FactsSignal(world.uow, world.object_store, reader))
    assert await pipeline.request_facts() == 1
    assert await pipeline.request_facts() == 0  # queued already
    await world.drain(pipeline)
    assert len(reader.calls) == 1
    assert await contacts_of(world, GIRO_IBAN) == {utility.id}
    # Processing and log stay as they were.
    async with world.uow() as uow:
        log = await uow.processing_log.list_for(document.id)
    assert all(entry.node is not Node.SIGNAL_FACTS for entry in log)


async def test_the_report_lists_the_document_s_numbers(world: World) -> None:
    """Its own invoice number and the one of the invoice a reminder refers to, as the text
    reads, with where they stand; a customer number stays among the identifiers."""
    owner = await world.user()
    text = (
        "Mahnung\nRechnungsnummer: M-77\nIhre Rechnung Nr. 4711 ist offen.\nKundennummer 20047718\n"
    )
    document = await stored(world, owner, text)
    result = await facts(world, document, FakeCodeReader([]))
    async with world.uow() as uow:
        await result.apply(uow, await uow.documents.get(document.id), builders.NOW)
        await uow.commit()
    report = await world.documents.facts(owner.id, document.id)
    numbers = [(item.fact.kind, item.fact.value, item.fact.role) for item in report.numbers]
    assert numbers == [
        (IdentifierKind.INVOICE_NUMBER, "M77", FactRole.OWN),
        (IdentifierKind.INVOICE_NUMBER, "4711", FactRole.REFERS),
    ]
    assert text[report.numbers[1].spans[0].start : report.numbers[1].spans[0].end] == "4711"
    assert [item.kind for item in report.facts.identifiers] == [IdentifierKind.CUSTOMER_NUMBER]
