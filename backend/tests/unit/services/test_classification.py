"""Classification and field extraction with a fake language model: every check, the
answer handling, and the way through the pipeline."""

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from papiq.adapters.outbound.memory import FakeLanguageModel, FakeTextLocator
from papiq.adapters.outbound.memory.processing import FAKE_PDF
from papiq.core.domain.classification import FieldCheck, checks_from_json, field_key
from papiq.core.domain.documents import UNSET, Document, DocumentChanges
from papiq.core.domain.errors import LanguageModelError
from papiq.core.domain.exchanges import RunExchange, exchanges_from_json
from papiq.core.domain.fields import FieldDefinition, FieldType, Money
from papiq.core.domain.json_value import JsonObject
from papiq.core.domain.master_data import Contact, DocumentType, Tag
from papiq.core.domain.pipeline import Lane, Node, NodeResult, Outcome, ProcessingStatus
from papiq.core.ports import StructuredRequest
from papiq.core.services.classification.nodes import (
    NO_MODEL,
    ClassificationPolicy,
    ClassifyNode,
    ExtractFieldsNode,
)
from papiq.core.services.classification.prompts import CLASSIFY_SYSTEM, EXTRACT_SYSTEM
from papiq.core.services.objects import archive_key, exchanges_key, markdown_key
from papiq.core.services.pipeline import MetadataResult, NodeExecutor
from tests import builders
from tests.builders import NOW, incoming
from tests.unit.services.conftest import World

INVOICE = """\
# Stadtwerke Musterstadt GmbH
Postfach 12 34, 12345 Musterstadt

Herrn Max Nord, Musterweg 1, 12345 Musterstadt

Musterstadt, 31.03.2026

## Rechnung Nr. R-2026-0815

Stromverbrauch vom 01.01.2026 bis 31.03.2026

| Position | Betrag |
| --- | --- |
| Arbeitspreis | 70,76 € |
| Gesamtbetrag | 84,20 € |

Zahlbar bis 15.04.2026.
"""


@dataclass
class Seeded:
    contacts: dict[str, Contact]
    types: dict[str, DocumentType]
    tags: dict[str, Tag]
    fields: dict[str, FieldDefinition]


async def seed(world: World, contacts: tuple[str, ...] = ()) -> Seeded:
    names = contacts or ("Stadtwerke Musterstadt GmbH", "Stadtwerke Beispielstadt", "AOK Bayern")
    seeded = Seeded(
        contacts={name: Contact.create(name=name, now=NOW) for name in names},
        types={name: DocumentType.create(name=name, now=NOW) for name in ("Rechnung", "Vertrag")},
        tags={name: Tag.create(name=name, now=NOW) for name in ("Strom", "Versicherung")},
        fields={},
    )
    invoice = seeded.types["Rechnung"].id
    for name, data_type, scope in [
        ("Rechnungsbetrag", FieldType.AMOUNT, [invoice]),
        ("Rechnungsnummer", FieldType.TEXT, [invoice]),
        ("Fällig am", FieldType.DATE, [invoice]),
        ("Bezahlt", FieldType.BOOLEAN, None),
    ]:
        # Bound to the invoice, the fields are required for it; the global one is optional.
        seeded.fields[name] = FieldDefinition.create(
            name=name,
            data_type=data_type,
            document_type_ids=scope,
            required_types=scope or (),
            now=NOW,
        )
    async with world.uow() as uow:
        for contact in seeded.contacts.values():
            await uow.contacts.add(contact)
        for kind in seeded.types.values():
            await uow.document_types.add(kind)
        for tag in seeded.tags.values():
            await uow.tags.add(tag)
        for field in seeded.fields.values():
            await uow.fields.add(field)
        await uow.commit()
    return seeded


def classification(**changes: Any) -> JsonObject:
    answer: JsonObject = {
        "contact": {"value": "Stadtwerke Musterstadt GmbH", "evidence": None},
        "document_type": "Rechnung",
        "new_document_type": None,
        "tags": ["Strom"],
        "new_tags": [],
        "document_date": {"value": "2026-03-31", "evidence": "Musterstadt, 31.03.2026"},
    }
    return answer | changes


def extraction(**values: Any) -> JsonObject:
    """Answer for the fields in key order: Bezahlt, Fällig am, Rechnungsbetrag,
    Rechnungsnummer (sorted by name)."""
    defaults: dict[str, Any] = {
        "a1": {"value": None, "evidence": None},
        "a2": {"value": "2026-04-15", "evidence": "Zahlbar bis 15.04.2026."},
        "a3": {
            "value": {"amount": "84.20", "currency": "EUR"},
            "evidence": "Gesamtbetrag | 84,20 €",
        },
        "a4": {"value": "R-2026-0815", "evidence": None},
    }
    return {"fields": defaults | values}


def model(*answers: JsonObject | str) -> FakeLanguageModel:
    """Answers in turn; the last one again and again."""
    remaining = list(answers)

    def respond(request: StructuredRequest) -> JsonObject | str:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return FakeLanguageModel(respond)


async def document_with(
    world: World, text: str = INVOICE, type: DocumentType | None = None
) -> Document:
    owner = await world.user()
    document = builders.document(owner, await world.default_drawer(owner))
    document.document_type_id = None if type is None else type.id
    await world.object_store.put(
        markdown_key(document.id), text.encode(), content_type="text/markdown; charset=utf-8"
    )
    return document


def classify_step(world: World, fake: FakeLanguageModel | None, **policy: Any) -> ClassifyNode:
    return ClassifyNode(
        world.uow, world.object_store, fake, world.clock, ClassificationPolicy(**policy)
    )


def extract_step(world: World, fake: FakeLanguageModel | None) -> ExtractFieldsNode:
    return ExtractFieldsNode(world.uow, world.object_store, fake, world.clock)


def checks(result: NodeResult) -> dict[str, FieldCheck]:
    return {check.field: check for check in checks_from_json(result.output["fields"])}


async def classify(world: World, answer: JsonObject, text: str = INVOICE) -> MetadataResult:
    document = await document_with(world, text)
    result = await classify_step(world, model(answer)).run(document)
    assert isinstance(result, MetadataResult)
    return result


# --- classification ---------------------------------------------------------------------------


async def test_a_verified_classification_is_applied(world: World) -> None:
    seeded = await seed(world)
    fake = model(classification())
    document = await document_with(world)

    outcome = await classify_step(world, fake).run(document)

    assert isinstance(outcome, MetadataResult)
    result, changes = outcome.result, outcome.changes
    assert result.outcome is Outcome.OK
    assert result.confidence == 1
    assert result.model_version == "fake-llm 1"
    assert changes == DocumentChanges(
        contact_id=seeded.contacts["Stadtwerke Musterstadt GmbH"].id,
        document_type_id=seeded.types["Rechnung"].id,
        document_date=date(2026, 3, 31),
    )
    assert outcome.add_tags == frozenset({seeded.tags["Strom"].id})
    assert result.input["truncated"] is False
    assert result.input["model"] == "fake-llm 1"
    assert result.input["endpoint"] == "memory"
    assert result.input["contacts"] == 3
    assert result.output["attempts"] == 1
    # Per attempt; the fake model reports no usage.
    assert result.output["tokens"] == [{"prompt": None, "completion": None, "usage": {}}]
    assert result.output["answer"] == classification()
    assert set(checks(result)) == {"contact", "document_type", "tags", "document_date"}

    (request,) = fake.requests
    assert "- Rechnung\n- Vertrag" in request.user
    assert "- Strom\n- Versicherung" in request.user
    # Contacts the text names (half of "Stadtwerke Beispielstadt"), not "AOK Bayern".
    assert "Contacts:\n- Stadtwerke Musterstadt GmbH\n- Stadtwerke Beispielstadt\n" in request.user
    assert "Postfach 12 34" in request.user
    assert request.schema_name == "classification"


@pytest.mark.parametrize(
    "name",
    ["Stadtwerke Musterstadt", "STADTWERKE MUSTERSTADT GMBH", "Stadtwerke Musterstdt GmbH"],
)
async def test_the_contact_is_matched_and_shown_in_the_text(world: World, name: str) -> None:
    seeded = await seed(world)
    result = await classify(world, classification(contact={"value": name, "evidence": None}))
    contact = checks(result.result)["contact"]
    assert contact.ok
    assert contact.confidence >= 0.9
    assert result.changes.contact_id == seeded.contacts["Stadtwerke Musterstadt GmbH"].id


async def test_an_unknown_contact_is_proposed_as_new(world: World) -> None:
    await seed(world)
    text = INVOICE.replace("Stadtwerke Musterstadt GmbH", "Elektro Huber")
    result = await classify(
        world, classification(contact={"value": "Elektro Huber", "evidence": None}), text
    )
    contact = checks(result.result)["contact"]
    assert contact.outcome is Outcome.UNCERTAIN
    assert contact.new_name == "Elektro Huber"
    assert contact.suggestion is None
    assert "a new contact is proposed" in (contact.reason or "")
    assert result.changes.contact_id is UNSET
    assert result.result.outcome is Outcome.UNCERTAIN
    assert (result.result.reason or "").startswith("contact: no contact matches 'Elektro Huber'")


async def test_a_contact_absent_from_the_text_is_only_suggested(world: World) -> None:
    seeded = await seed(world)
    result = await classify(
        world, classification(contact={"value": "AOK Bayern", "evidence": None})
    )
    contact = checks(result.result)["contact"]
    assert contact.outcome is Outcome.UNCERTAIN
    assert contact.reason == "the contact 'AOK Bayern' does not appear in the text"
    assert contact.suggestion == str(seeded.contacts["AOK Bayern"].id)
    assert contact.confidence == 0.5


async def test_a_similar_contact_is_suggested(world: World) -> None:
    seeded = await seed(world)
    result = await classify(
        world, classification(contact={"value": "Stadtwerk Musterstadt Netz", "evidence": None})
    )
    contact = checks(result.result)["contact"]
    assert contact.outcome is Outcome.UNCERTAIN
    assert contact.suggestion == str(seeded.contacts["Stadtwerke Musterstadt GmbH"].id)
    assert "is similar to the contact 'Stadtwerke Musterstadt GmbH'" in (contact.reason or "")
    assert 0.75 <= contact.confidence < 0.9


async def test_the_contact_itself_must_be_named(world: World) -> None:
    """A typo in the text matches the contact closely, but the contact is not named."""
    seeded = await seed(world)
    text = INVOICE.replace("Stadtwerke Musterstadt GmbH", "Stadtwerke Musterstad GmbH")
    result = await classify(
        world,
        classification(contact={"value": "Stadtwerke Musterstad GmbH", "evidence": None}),
        text,
    )
    contact = checks(result.result)["contact"]
    assert contact.outcome is Outcome.UNCERTAIN
    assert contact.suggestion == str(seeded.contacts["Stadtwerke Musterstadt GmbH"].id)
    assert contact.confidence == 0.5


async def test_ambiguous_contacts_are_uncertain(world: World) -> None:
    await seed(world, contacts=("Muster GmbH", "Muster AG"))
    text = INVOICE.replace("Stadtwerke Musterstadt GmbH", "Muster")
    result = await classify(
        world, classification(contact={"value": "Muster", "evidence": None}), text
    )
    contact = checks(result.result)["contact"]
    assert contact.outcome is Outcome.UNCERTAIN
    assert "several contacts" in (contact.reason or "")


async def test_no_contact(world: World) -> None:
    await seed(world)
    result = await classify(world, classification(contact={"value": None, "evidence": None}))
    assert checks(result.result)["contact"].reason == "no contact recognised"


@pytest.mark.parametrize(
    ("answer", "reason", "new_name"),
    [
        ({"document_type": "Mahnung"}, "'Mahnung' is not a document type", "Mahnung"),
        (
            {"document_type": None, "new_document_type": "Werbung"},
            "no document type fits; a new type 'Werbung' is proposed",
            "Werbung",
        ),
        ({"document_type": None}, "no document type recognised", None),
    ],
)
async def test_uncertain_document_types(
    world: World, answer: dict[str, Any], reason: str, new_name: str | None
) -> None:
    await seed(world)
    result = await classify(world, classification(**answer))
    kind = checks(result.result)["document_type"]
    assert kind.outcome is Outcome.UNCERTAIN
    assert (kind.reason or "").startswith(reason)
    assert kind.new_name == new_name
    assert result.changes.document_type_id is UNSET


async def test_document_types_are_matched_regardless_of_case(world: World) -> None:
    seeded = await seed(world)
    result = await classify(world, classification(document_type="rechnung"))
    assert result.changes.document_type_id == seeded.types["Rechnung"].id


async def test_new_tags_are_only_proposed(world: World) -> None:
    seeded = await seed(world)
    result = await classify(
        world, classification(tags=["Strom", "Energie", "Strom"], new_tags=["Abschlag"])
    )
    tags = checks(result.result)["tags"]
    assert tags.ok
    assert tags.value == [str(seeded.tags["Strom"].id)]
    assert tags.suggestion == ["Abschlag", "Energie"]
    assert result.result.outcome is Outcome.OK
    assert result.add_tags == frozenset({seeded.tags["Strom"].id})


@pytest.mark.parametrize(
    ("value", "evidence", "reason", "suggestion"),
    [
        ("2026-03-30", None, "the date does not appear in the text", "2026-03-30"),
        (
            "2026-03-31",
            "31.03.2025",
            "the quoted passage does not appear in the text",
            "2026-03-31",
        ),
        ("31.13.2026", None, "'31.13.2026' is not a date", None),
        ("2026-02-30", None, "'2026-02-30' is not a date", None),
        ("1850-03-31", None, "1850-03-31 is not plausible", None),
        ("2030-03-31", None, "2030-03-31 is not plausible", None),
        (None, None, "no date recognised", None),
    ],
)
async def test_uncertain_dates(
    world: World, value: str | None, evidence: str | None, reason: str, suggestion: str | None
) -> None:
    await seed(world)
    text = INVOICE + "\nGültig bis 31.03.2030, gegründet 31.03.1850\n"
    result = await classify(
        world, classification(document_date={"value": value, "evidence": evidence}), text
    )
    check = checks(result.result)["document_date"]
    assert check.outcome is Outcome.UNCERTAIN
    assert check.reason == reason
    assert check.suggestion == suggestion
    assert result.changes.document_date is UNSET


async def test_nothing_recognised_fails(world: World) -> None:
    await seed(world)
    document = await document_with(world)
    result = await classify_step(world, FakeLanguageModel()).run(document)
    assert isinstance(result, NodeResult)
    assert result.outcome is Outcome.FAILED
    assert result.reason == "nothing recognised: no contact, document type or date"


async def test_an_unfit_answer_is_asked_again(world: World) -> None:
    await seed(world)
    fake = model("Sure! Here is the JSON.", classification())
    outcome = await classify_step(world, fake).run(await document_with(world))
    assert isinstance(outcome, MetadataResult)
    assert outcome.result.outcome is Outcome.OK
    assert outcome.result.output["attempts"] == 2
    first, second = fake.requests
    assert second.user.startswith(first.user)
    assert "Your previous answer was not valid: the answer is not JSON" in second.user


async def exchanges(world: World, document: Document, node: Node) -> list[RunExchange]:
    return exchanges_from_json(
        json.loads(await world.object_store.get(exchanges_key(document.id, node)))
    )


async def test_what_was_sent_is_kept_per_run(world: World) -> None:
    await seed(world)
    fake = model("Sure! Here is the JSON.", classification())
    document = await document_with(world)
    await classify_step(world, fake).run(document)

    (kept,) = await exchanges(world, document, Node.JUDGE)
    assert kept.run == document.processing.run
    first, second = kept.calls
    assert (first.system, first.user) == (CLASSIFY_SYSTEM, fake.requests[0].user)
    assert first.answer == "Sure! Here is the JSON."
    assert second.user == fake.requests[1].user
    assert json.loads(second.answer) == classification()
    assert (second.model, second.usage) == ("fake-llm 1", {})

    # The same run again replaces its calls; a later run is added.
    await classify_step(world, model(classification())).run(document)
    (again,) = await exchanges(world, document, Node.JUDGE)
    assert len(again.calls) == 1
    later = replace(document, processing=replace(document.processing, run=2))
    await classify_step(world, model(classification())).run(later)
    assert [run.run for run in await exchanges(world, document, Node.JUDGE)] == [1, 2]


async def test_the_exchanges_of_a_failed_step_are_kept(world: World) -> None:
    await seed(world)
    document = await document_with(world)
    await classify_step(world, model("not json")).run(document)
    (kept,) = await exchanges(world, document, Node.JUDGE)
    assert [call.answer for call in kept.calls] == ["not json", "not json"]


async def test_the_field_extraction_keeps_its_own_exchanges(world: World) -> None:
    seeded = await seed(world)
    document = await document_with(world, type=seeded.types["Rechnung"])
    await extract_step(world, model(extraction())).run(document)
    (kept,) = await exchanges(world, document, Node.FIELDS)
    assert kept.calls[0].system == EXTRACT_SYSTEM
    assert not await world.object_store.exists(exchanges_key(document.id, Node.JUDGE))


async def test_two_unfit_answers_fail_the_step(world: World) -> None:
    await seed(world)
    injected = classification() | {"drawer": "Shared", "owner": "mallory"}
    outcome = await classify_step(world, model(injected)).run(await document_with(world))
    assert isinstance(outcome, NodeResult)
    assert outcome.outcome is Outcome.FAILED
    assert outcome.reason == (
        "the model's answer does not fit the schema: the answer: unexpected drawer, owner"
    )
    assert outcome.output["attempts"] == 2
    assert len(outcome.output["answers"]) == 2  # type: ignore[arg-type]


async def test_without_a_model_a_person_classifies(world: World) -> None:
    result = await classify_step(world, None).run(await document_with(world))
    assert result == NodeResult(outcome=Outcome.UNCERTAIN, reason=NO_MODEL)


async def test_an_unreachable_model_raises_for_a_retry(world: World) -> None:
    def fail(request: StructuredRequest) -> str:
        raise LanguageModelError("cannot reach ollama:11434")

    with pytest.raises(LanguageModelError):
        await classify_step(world, FakeLanguageModel(fail)).run(await document_with(world))


async def test_long_texts_are_shortened_but_checked_in_full(world: World) -> None:
    await seed(world)
    text = (
        INVOICE.replace("Musterstadt, 31.03.2026\n", "")
        + "\n".join(f"Zeile {number}" for number in range(3000))
        + "\nMusterstadt, 31.03.2026\n"
    )
    fake = model(classification())
    outcome = await classify_step(world, fake, input_budget=2000).run(
        await document_with(world, text)
    )
    assert isinstance(outcome, MetadataResult)
    assert outcome.result.input["truncated"] is True
    sent = outcome.result.input["sent"]
    assert isinstance(sent, int)
    assert sent < 2200
    assert "characters left out" in fake.requests[0].user
    assert checks(outcome.result)["document_date"].ok


async def test_many_tags_list_those_named_in_the_text_first(world: World) -> None:
    await seed(world)
    async with world.uow() as uow:
        for number in range(10):
            await uow.tags.add(Tag.create(name=f"Aaa {number}", now=NOW))
        await uow.commit()
    fake = model(classification())
    text = INVOICE + "\nTarif: Strom Basis\n"
    await classify_step(world, fake, max_tags=3).run(await document_with(world, text))
    request = fake.requests[0]
    assert "- Strom" in request.user
    assert request.user.count("- Aaa") == 2


async def add_contact(world: World, name: str, *aliases: str) -> Contact:
    contact = Contact.create(name=name, now=NOW, aliases=aliases)
    async with world.uow() as uow:
        await uow.contacts.add(contact)
        await uow.commit()
    return contact


EXAMPLE_LETTER = INVOICE.replace("Stadtwerke Musterstadt GmbH", "Nord Krankenversicherung AG")


@pytest.mark.parametrize("name", ["Nord Versicherungsgruppe", "Nord Krankenversicherung AG"])
async def test_a_contact_named_by_an_alias_is_applied(world: World, name: str) -> None:
    """The model gives the listed name or the one in the text; the text shows an alias."""
    await seed(world)
    example = await add_contact(world, "Nord Versicherungsgruppe", "Nord Krankenversicherung AG")
    result = await classify(
        world, classification(contact={"value": name, "evidence": None}), EXAMPLE_LETTER
    )
    contact = checks(result.result)["contact"]
    assert contact.ok
    assert result.changes.contact_id == example.id


async def test_without_the_alias_the_contact_is_new(world: World) -> None:
    await seed(world)
    await add_contact(world, "Nord Versicherungsgruppe")
    result = await classify(
        world,
        classification(contact={"value": "Nord Krankenversicherung AG", "evidence": None}),
        EXAMPLE_LETTER,
    )
    contact = checks(result.result)["contact"]
    assert contact.new_name == "Nord Krankenversicherung AG"


async def test_an_alias_of_another_contact_does_not_count_as_named(world: World) -> None:
    """The other insurer's alias in the text does not name the example."""
    await seed(world)
    example = await add_contact(world, "Nord Versicherungsgruppe")
    await add_contact(world, "Muster", "Nord Krankenversicherung AG Muster")
    result = await classify(
        world,
        classification(contact={"value": "Nord Versicherungsgruppe", "evidence": None}),
        EXAMPLE_LETTER,
    )
    contact = checks(result.result)["contact"]
    assert not contact.ok
    assert contact.suggestion == str(example.id)


async def test_contacts_the_text_names_most_are_listed(world: World) -> None:
    await seed(world)
    await add_contact(world, "Nord Versicherungsgruppe", "Nord Krankenversicherung AG")
    await add_contact(world, "Südstädter Versicherung")
    await add_contact(world, "Nord Sport")
    fake = model(classification())
    text = EXAMPLE_LETTER + "\nINTER, Südstadt\n"
    node = classify_step(world, fake, max_contacts=3)
    result = await node.run(await document_with(world, text))
    contacts = fake.requests[0].user.split("\n\nDocument types:")[0]
    assert contacts == (
        "Contacts:\n"
        "- Nord Versicherungsgruppe (also written as: Nord Krankenversicherung AG)\n"
        "- Nord Sport\n"  # half of the words, like the next; then by name
        "- Stadtwerke Musterstadt GmbH"
    )  # not the contacts whose words the text does not show
    assert isinstance(result, MetadataResult)
    assert result.result.input["contacts_listed"] == 3


async def test_type_descriptions_are_listed(world: World) -> None:
    await seed(world)
    async with world.uow() as uow:
        await uow.document_types.add(
            DocumentType.create(name="Lohnabrechnung", now=NOW, description="Entgeltbescheinigung")
        )
        await uow.commit()
    fake = model(classification())
    await classify_step(world, fake).run(await document_with(world))
    assert "- Lohnabrechnung: Entgeltbescheinigung\n- Rechnung\n" in fake.requests[0].user


# --- fields -------------------------------------------------------------------------------


async def extract(
    world: World, answer: JsonObject, text: str = INVOICE
) -> tuple[Seeded, MetadataResult]:
    seeded = await seed(world)
    document = await document_with(world, text, seeded.types["Rechnung"])
    result = await extract_step(world, model(answer)).run(document)
    assert isinstance(result, MetadataResult)
    return seeded, result


def field_check(seeded: Seeded, result: MetadataResult, name: str) -> FieldCheck:
    return checks(result.result)[field_key(seeded.fields[name].id)]


async def test_verified_fields_are_applied(world: World) -> None:
    seeded, result = await extract(world, extraction())
    assert result.result.outcome is Outcome.OK
    fields = seeded.fields
    assert result.changes.fields == {
        fields["Rechnungsbetrag"].id: Money(Decimal("84.20"), "EUR"),
        fields["Rechnungsnummer"].id: "R-2026-0815",
        fields["Fällig am"].id: date(2026, 4, 15),
    }
    paid = field_check(seeded, result, "Bezahlt")
    assert paid.ok and paid.value is None  # a global field may be missing
    assert result.result.input["fields"] == {
        "a1": str(fields["Bezahlt"].id),
        "a2": str(fields["Fällig am"].id),
        "a3": str(fields["Rechnungsbetrag"].id),
        "a4": str(fields["Rechnungsnummer"].id),
    }


@pytest.mark.parametrize(
    ("answer", "name", "reason", "suggestion"),
    [
        (
            {"a3": {"value": {"amount": "99.99", "currency": "EUR"}, "evidence": None}},
            "Rechnungsbetrag",
            "'Rechnungsbetrag': the amount does not appear in the text",
            {"amount": "99.99", "currency": "EUR"},
        ),
        (
            {"a3": {"value": {"amount": "84.20", "currency": "USD"}, "evidence": None}},
            "Rechnungsbetrag",
            "'Rechnungsbetrag': the currency USD does not appear in the text",
            {"amount": "84.20", "currency": "USD"},
        ),
        (
            {"a3": {"value": "zwölf Euro", "evidence": None}},
            "Rechnungsbetrag",
            "'zwölf Euro' is not a valid value of 'Rechnungsbetrag' (amount)",
            None,
        ),
        (
            {"a4": {"value": None, "evidence": None}},
            "Rechnungsnummer",
            "'Rechnungsnummer' was not found",
            None,
        ),
        (
            {"a4": {"value": "R-2026-0816", "evidence": None}},
            "Rechnungsnummer",
            "'Rechnungsnummer': the text does not appear in the text",
            "R-2026-0816",
        ),
        (
            {"a4": {"value": "R-2026-0815", "evidence": "Rechnung Nr. R-2026-0815 vom"}},
            "Rechnungsnummer",
            "'Rechnungsnummer': the quoted passage does not appear in the text",
            "R-2026-0815",
        ),
        (
            {"a2": {"value": "2026-04-16", "evidence": None}},
            "Fällig am",
            "'Fällig am': the date does not appear in the text",
            "2026-04-16",
        ),
        (
            {"a1": {"value": True, "evidence": None}},
            "Bezahlt",
            "'Bezahlt': the quoted passage does not appear in the text",
            True,
        ),
        (
            {"a1": {"value": True, "evidence": "31"}},
            "Bezahlt",
            "'Bezahlt': the quoted passage does not appear in the text",
            True,
        ),
        (
            {"a4": {"value": "R-2026", "evidence": None}},
            "Rechnungsnummer",
            "'Rechnungsnummer': the text does not appear in the text",
            "R-2026",
        ),
        (
            {"a3": {"value": {"amount": "84.20", "currency": "BIS"}, "evidence": None}},
            "Rechnungsbetrag",
            "'Rechnungsbetrag': the currency BIS does not appear in the text",
            {"amount": "84.20", "currency": "BIS"},
        ),
    ],
)
async def test_uncertain_fields(
    world: World, answer: dict[str, Any], name: str, reason: str, suggestion: object
) -> None:
    seeded, result = await extract(world, extraction(**answer))
    check = field_check(seeded, result, name)
    assert check.outcome is Outcome.UNCERTAIN
    assert check.reason == reason
    assert check.suggestion == suggestion
    assert seeded.fields[name].id not in result.changes.fields
    assert result.result.outcome is Outcome.UNCERTAIN


async def test_a_date_equal_to_the_document_date_is_only_suggested(world: World) -> None:
    """Models put the document date into a due date the text does not give."""
    seeded = await seed(world)
    document = await document_with(world, type=seeded.types["Rechnung"])
    document.document_date = date(2026, 3, 31)
    answer = extraction(a2={"value": "2026-03-31", "evidence": "Musterstadt, 31.03.2026"})
    result = await extract_step(world, model(answer)).run(document)
    assert isinstance(result, MetadataResult)
    check = field_check(seeded, result, "Fällig am")
    assert check.outcome is Outcome.UNCERTAIN
    assert check.reason == "'Fällig am': the same date as the document date"
    assert check.suggestion == "2026-03-31"
    assert seeded.fields["Fällig am"].id not in result.changes.fields


async def test_values_are_read_leniently(world: World) -> None:
    seeded, result = await extract(
        world,
        extraction(
            a1={"value": True, "evidence": "Zahlbar bis 15.04.2026."},
            a3={"value": {"amount": "84,2", "currency": "eur"}, "evidence": None},
        ),
    )
    fields = seeded.fields
    assert result.changes.fields[fields["Rechnungsbetrag"].id] == Money(Decimal("84.2"), "EUR")
    assert result.changes.fields[fields["Bezahlt"].id] is True


async def test_an_optional_field_may_stay_empty_but_a_value_must_be_shown(world: World) -> None:
    seeded = await seed(world)
    number = seeded.fields["Rechnungsnummer"]
    number.require(types=[])
    async with world.uow() as uow:
        await uow.fields.update(number)
        await uow.commit()
    document = await document_with(world, INVOICE, seeded.types["Rechnung"])
    for answer, outcome in (
        (extraction(), Outcome.OK),
        (extraction(a4={"value": "R-2026", "evidence": None}), Outcome.UNCERTAIN),
    ):
        result = await extract_step(world, model(answer)).run(document)
        assert isinstance(result, MetadataResult)
        assert field_check(seeded, result, "Rechnungsnummer").outcome is outcome


async def test_values_are_read_as_written_in_german(world: World) -> None:
    seeded, result = await extract(
        world,
        extraction(
            a2={"value": "15.04.2026", "evidence": "Zahlbar bis 15.04.2026."},
            a3={"value": "84,20 €", "evidence": "Gesamtbetrag | 84,20 €"},
        ),
    )
    fields = seeded.fields
    assert result.changes.fields[fields["Rechnungsbetrag"].id] == Money(Decimal("84.20"), "EUR")
    assert result.changes.fields[fields["Fällig am"].id] == date(2026, 4, 15)


async def test_no_fields_no_question(world: World) -> None:
    await seed(world)
    document = await document_with(world)  # no type: only the global field applies
    async with world.uow() as uow:
        for field in await uow.fields.list_all():
            if field.is_global:
                await uow.fields.remove(field.id)
        await uow.commit()
    fake = model(extraction())
    result = await extract_step(world, fake).run(document)
    assert result == NodeResult(outcome=Outcome.OK, output={"fields": []})
    assert fake.requests == []
    assert await extract_step(world, None).run(document) == result


async def test_fields_without_a_model(world: World) -> None:
    seeded = await seed(world)
    document = await document_with(world, type=seeded.types["Rechnung"])
    result = await extract_step(world, None).run(document)
    assert result == NodeResult(outcome=Outcome.UNCERTAIN, reason=NO_MODEL)


async def test_extraction_prompt_names_type_and_fields(world: World) -> None:
    seeded = await seed(world)
    fake = model(extraction())
    await extract_step(world, fake).run(await document_with(world, type=seeded.types["Rechnung"]))
    (request,) = fake.requests
    assert 'The document is of type "Rechnung".' in request.user
    assert '- a3: "Rechnungsbetrag" (object with amount' in request.user
    assert request.schema_name == "fields"


# --- through the pipeline ---------------------------------------------------------------------


def responder(
    classify: JsonObject, extract: JsonObject
) -> Callable[[StructuredRequest], JsonObject]:
    return lambda request: classify if request.schema_name == "classification" else extract


async def run(world: World, fake: FakeLanguageModel) -> tuple[Any, Document]:
    owner = await world.user()
    executors: dict[Node, NodeExecutor] = {
        Node.JUDGE: classify_step(world, fake),
        Node.FIELDS: extract_step(world, fake),
    }
    pipeline = world.pipeline(executors)
    document = await pipeline.receive(owner.id, incoming(b"%PDF-1.7\n%%EOF\n"), filename="a.pdf")
    await world.object_store.put(
        markdown_key(document.id), INVOICE.encode(), content_type="text/markdown; charset=utf-8"
    )
    await world.drain(pipeline)
    return owner, await world.documents.get(owner.id, document.id)


async def test_a_verified_document_is_filed_green(world: World) -> None:
    seeded = await seed(world)
    owner, document = await run(world, FakeLanguageModel(responder(classification(), extraction())))
    assert document.lane is Lane.GREEN
    assert document.contact_id == seeded.contacts["Stadtwerke Musterstadt GmbH"].id
    assert document.document_type_id == seeded.types["Rechnung"].id
    assert document.tag_ids == {seeded.tags["Strom"].id}
    assert document.document_date == date(2026, 3, 31)
    assert document.fields[seeded.fields["Rechnungsbetrag"].id] == Money(Decimal("84.20"), "EUR")
    assert "document.filed" in world.event_types()
    log = await world.documents.processing_log(owner.id, document.id)
    classified = next(entry for entry in log if entry.node is Node.JUDGE)
    assert classified.result.output["answer"] == classification()
    assert len(checks(classified.result)) == 4


async def test_an_uncertain_document_waits_in_the_inbox(world: World) -> None:
    seeded = await seed(world)
    answer = classification(contact={"value": "AOK Bayern", "evidence": None})
    _, document = await run(world, FakeLanguageModel(responder(answer, extraction())))
    assert document.lane is Lane.YELLOW
    assert document.processing.status is ProcessingStatus.REVIEW
    assert document.contact_id is None  # only proposed
    assert document.document_type_id == seeded.types["Rechnung"].id  # verified, so applied
    assert "document.filed" not in world.event_types()


# --- quotes on the page ---------------------------------------------------------------------


async def test_quotes_are_located_in_the_archive(world: World) -> None:
    await seed(world)
    document = await document_with(world)
    await world.object_store.put(archive_key(document.id), FAKE_PDF, content_type="application/pdf")
    locator = FakeTextLocator([INVOICE])
    step = ClassifyNode(
        world.uow, world.object_store, model(classification()), world.clock, locator=locator
    )
    outcome = await step.run(document)
    assert isinstance(outcome, MetadataResult)
    found = checks(outcome.result)
    dated = found["document_date"]
    assert dated.quote_shows_value is True
    (place,) = dated.locations
    assert place.page == 1 and place.boxes
    assert found["contact"].locations == ()  # no quote
    assert found["contact"].quote_shows_value is None
    assert locator.calls == [["Musterstadt, 31.03.2026"]]


async def test_without_an_archive_the_quotes_stay_unlocated(world: World) -> None:
    await seed(world)
    document = await document_with(world)
    step = ClassifyNode(
        world.uow,
        world.object_store,
        model(classification()),
        world.clock,
        locator=FakeTextLocator([INVOICE]),
    )
    outcome = await step.run(document)
    assert isinstance(outcome, MetadataResult)
    assert outcome.result.outcome is Outcome.OK
    assert checks(outcome.result)["document_date"].locations == ()


@pytest.mark.parametrize(
    ("evidence", "shows"),
    [("Stadtwerke Musterstadt GmbH", True), ("Postfach 12 34, 12345 Musterstadt", False)],
)
async def test_a_quote_may_lead_to_the_contact_without_naming_it(
    world: World, evidence: str, shows: bool
) -> None:
    await seed(world)
    contact = {"value": "Stadtwerke Musterstadt GmbH", "evidence": evidence}
    result = await classify(world, classification(contact=contact))
    assert checks(result.result)["contact"].quote_shows_value is shows


async def test_field_quotes_show_amounts_and_dates_but_never_yes_or_no(world: World) -> None:
    paid = {"value": True, "evidence": "Zahlbar bis 15.04.2026."}
    seeded, result = await extract(world, extraction(a1=paid))
    assert field_check(seeded, result, "Rechnungsbetrag").quote_shows_value is True
    assert field_check(seeded, result, "Fällig am").quote_shows_value is True
    assert field_check(seeded, result, "Bezahlt").quote_shows_value is False
    assert field_check(seeded, result, "Rechnungsnummer").quote_shows_value is None


async def test_a_failure_to_keep_the_exchanges_does_not_fail_the_node(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed(world)
    document = await document_with(world)
    put = world.object_store.put

    async def failing(key: str, data: bytes, *, content_type: str) -> None:
        if "/exchanges/" in key:
            raise OSError("the object store is full")
        await put(key, data, content_type=content_type)

    monkeypatch.setattr(world.object_store, "put", failing)
    outcome = await classify_step(world, model(classification())).run(document)
    assert isinstance(outcome, MetadataResult)
    assert outcome.result.outcome is Outcome.OK
    assert not await world.object_store.exists(exchanges_key(document.id, Node.JUDGE))
