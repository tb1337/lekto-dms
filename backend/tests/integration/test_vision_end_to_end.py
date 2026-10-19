"""A poor scan and a photo that Tesseract cannot read, read with the vision language model:
real OCRmyPDF with the vision plugin against a stand-in for the model, the layout text, then
the signals, the judge and the fields with a stand-in language model. Without a person asking,
nothing goes to the vision model; the document is red then, and the advice says why."""

import json
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from lekto.adapters.outbound.filesystem import FilesystemObjectStore
from lekto.adapters.outbound.memory import FakeLanguageModel
from lekto.adapters.outbound.ocrmypdf import OcrmypdfEngine
from lekto.adapters.outbound.ocrmypdf.vision import VisionSettings
from lekto.adapters.outbound.pdfium import LayoutParser, PdfiumPageRenderer, PdfiumTextLocator
from lekto.composition.container import (
    VISION_REQUEST_TIMEOUT,
    build_memory_container,
    build_services,
)
from lekto.core.domain.fields import FieldDefinition, FieldType, Money
from lekto.core.domain.master_data import Contact, DocumentType
from lekto.core.domain.pipeline import Lane, Node
from lekto.core.domain.reading import VisionAdvice
from lekto.core.ports.llm import StructuredRequest
from lekto.core.services.objects import text_key
from tests import builders, probes
from tests.builders import DEFAULT_SETTINGS, NOW, SAMPLES, incoming
from tests.vision_stub import Lines, VisionStub, serve

pytestmark = probes.requires_ocr


@dataclass(frozen=True)
class Case:
    sample: str
    lines: Lines  # what the vision model reads on the page
    contact: str
    kind: str
    field: str
    proposal: dict[str, object]
    value: Money
    document_date: date


INVOICE = Case(
    sample="poor-scan.pdf",
    lines=(
        ("Stadtwerke Musterstadt GmbH", (0.09, 0.1, 0.48, 0.13)),
        ("Rechnung Nr. R-2026-0815", (0.09, 0.14, 0.44, 0.17)),
        ("Musterstadt, 31.03.2026", (0.09, 0.18, 0.4, 0.21)),
        ("Arbeitspreis 70,76 EUR", (0.09, 0.22, 0.38, 0.25)),
        ("Gesamtbetrag 84,20 EUR", (0.09, 0.26, 0.41, 0.29)),
        ("Zahlbar bis 15.04.2026.", (0.09, 0.3, 0.39, 0.33)),
    ),
    contact="Stadtwerke Musterstadt GmbH",
    kind="Rechnung",
    field="Rechnungsbetrag",
    proposal={
        "sender": {"value": "Stadtwerke Musterstadt GmbH", "evidence": None},
        "document_date": {"value": "2026-03-31", "evidence": "Musterstadt, 31.03.2026"},
        "title": "Stromrechnung März 2026",
        "fields": [{"key": "a1", "value": "84,20 EUR", "evidence": "Gesamtbetrag 84,20 EUR"}],
    },
    value=Money(Decimal("84.20"), "EUR"),
    document_date=date(2026, 3, 31),
)
RECEIPT = Case(
    sample="receipt-photo.jpg",
    lines=(
        ("BAUMARKT HAMMER", (0.38, 0.17, 0.57, 0.2)),
        ("Kasse 3 Bon 0815", (0.37, 0.23, 0.54, 0.26)),
        ("26.09.2026 14:37", (0.36, 0.28, 0.53, 0.31)),
        ("Farbrolle 4,29", (0.36, 0.34, 0.5, 0.37)),
        ("Schrauben 7,99", (0.35, 0.39, 0.51, 0.42)),
        ("SUMME EUR 12,28", (0.35, 0.45, 0.53, 0.48)),
    ),
    contact="Baumarkt Hammer",
    kind="Kassenbon",
    field="Summe",
    proposal={
        "sender": {"value": "BAUMARKT HAMMER", "evidence": None},
        "document_date": {"value": "2026-09-26", "evidence": "26.09.2026 14:37"},
        "title": "Kassenbon Baumarkt",
        "fields": [{"key": "a1", "value": "12,28 EUR", "evidence": "SUMME EUR 12,28"}],
    },
    value=Money(Decimal("12.28"), "EUR"),
    document_date=date(2026, 9, 26),
)


@pytest.fixture
def stub() -> Iterator[VisionStub]:
    with serve(VisionStub()) as served:
        yield served


def answers(case: Case) -> FakeLanguageModel:
    proposal = {
        "recipient": None,
        "document_type": case.kind,
        "new_document_type": None,
        "topic": None,
        "tags": [],
        "new_tags": [],
        "language": "de",
        **case.proposal,
    }

    def respond(request: StructuredRequest) -> str:
        assert request.schema_name == "proposal", request.schema_name
        return json.dumps(proposal)

    return FakeLanguageModel(respond)


@pytest.mark.parametrize("case", [INVOICE, RECEIPT], ids=["poor scan", "photo"])
async def test_the_vision_model_reads_what_tesseract_cannot(
    tmp_path: Path, stub: VisionStub, case: Case
) -> None:
    stub.pages = [case.lines]
    settings = VisionSettings(
        base_url=stub.url, model=stub.model, api_key="stub-key", timeout=VISION_REQUEST_TIMEOUT
    )
    container = replace(
        build_memory_container(),
        object_store=FilesystemObjectStore(tmp_path / "objects"),
        ocr=OcrmypdfEngine(
            languages=["deu", "eng"],
            timeout=timedelta(minutes=5),
            vision=settings,
            vision_timeout=DEFAULT_SETTINGS.vlm_timeout,
        ),
        parser=LayoutParser(),
        pages=PdfiumPageRenderer(),
        locator=PdfiumTextLocator(),
        language_model=answers(case),
    )
    services = build_services(container)
    owner = await builders.seed_user(container.unit_of_work)
    contact = Contact.create(name=case.contact, now=NOW)
    kind = DocumentType.create(name=case.kind, now=NOW)
    field = FieldDefinition.create(
        name=case.field,
        data_type=FieldType.AMOUNT,
        document_type_ids=[kind.id],
        required_types=[kind.id],
        now=NOW,
    )
    async with container.unit_of_work() as uow:
        await uow.contacts.add(contact)
        await uow.document_types.add(kind)
        await uow.fields.add(field)
        await uow.commit()

    async def drain() -> None:
        await builders.drain(services.pipeline)

    data = (SAMPLES / case.sample).read_bytes()
    received = await services.pipeline.receive(owner.id, incoming(data), filename=case.sample)
    await drain()
    # Tesseract finds no text; nothing went to the vision model.
    read = await services.documents.get(owner.id, received.id)
    assert read.lane is Lane.RED
    assert stub.requests == []
    reading = await services.pipeline.reading(owner.id, received.id)
    assert (reading.vision, reading.advice) == (False, VisionAdvice.NO_TEXT)

    await services.pipeline.read_with_vision(owner.id, received.id)
    await drain()
    document = await services.documents.get(owner.id, received.id)
    log = await services.documents.processing_log(owner.id, received.id)
    assert document.lane is Lane.GREEN, [(entry.node, entry.result.reason) for entry in log]
    assert len(stub.requests) == 1
    assert (document.contact_id, document.document_type_id) == (contact.id, kind.id)
    assert document.document_date == case.document_date
    assert document.fields == {field.id: case.value}
    text = (await container.object_store.get(text_key(document.id))).decode()
    assert all(line in " ".join(text.split()) for line, _ in case.lines)
    ocr = [entry for entry in log if entry.node is Node.OCR][-1]
    vision = ocr.result.output["vision"]
    assert isinstance(vision, dict) and vision["model"] == "stub-vlm"
    after = await services.pipeline.reading(owner.id, received.id)
    assert (after.vision, after.advice) == (True, None)
