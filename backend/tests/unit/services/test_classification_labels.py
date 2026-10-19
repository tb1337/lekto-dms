"""The label beside a field's value (issue #55, step 1): checked against the words of the
parsed text and recorded with the field's check, without changing any outcome."""

import json
from dataclasses import replace
from typing import Any

import pytest

from lekto.core.domain.classification import FieldCheck, checks_from_json, field_key
from lekto.core.domain.documents import Document
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.labels import LabelCheck, LabelOutcome, grid_layout
from lekto.core.domain.pipeline import Node, Outcome
from lekto.core.services.classification import nodes
from lekto.core.services.objects import structure_key
from lekto.core.services.pipeline import MetadataResult
from tests.unit.services.support import World
from tests.unit.services.test_classification import (
    FIELDS,
    INVOICE,
    Seeded,
    document_with,
    extraction,
    fields_step,
    judge,
    model,
    proposal,
    record,
    seed,
)

# Keys by name: a1 Bezahlt, a2 Fällig am, a3 Rechnungsbetrag, a4 Rechnungsnummer.
LABELS = {"a1": "Bezahlt", "a2": "Zahlbar bis", "a3": "Gesamtbetrag", "a4": "Rechnung Nr."}


def labelled(**labels: str | None) -> JsonObject:
    """The fields node's answer with a label for each field (`LABELS`, changed by `labels`),
    Bezahlt given as yes."""
    answer: Any = extraction(a1={"value": True, "evidence": "Zahlbar bis 15.04.2026."})
    for key, entry in answer["fields"].items():
        entry["label"] = labels.get(key, LABELS[key])
    result: JsonObject = answer
    return result


async def invoice(
    world: World, structure: object = None, seeded: Seeded | None = None
) -> tuple[Seeded, Document]:
    """The invoice with its structure on the grid (or `structure`, None: on the grid), of the
    master data `seeded` (None: seeded now)."""
    seeded = seeded or await seed(world)
    document = await document_with(world, INVOICE, seeded.types["Rechnung"])
    data = grid_layout(INVOICE) if structure is None else structure
    await world.object_store.put(
        structure_key(document.id), json.dumps(data).encode(), content_type="application/json"
    )
    return seeded, document


async def read(
    world: World, answer: JsonObject, structure: object = None, seeded: Seeded | None = None
) -> tuple[Seeded, MetadataResult]:
    seeded, document = await invoice(world, structure, seeded)
    result = await fields_step(world, model(answer)).run(document)
    assert isinstance(result, MetadataResult)
    return seeded, result


def label(seeded: Seeded, result: MetadataResult, name: str) -> LabelCheck | None:
    checks = {check.field: check for check in checks_from_json(result.result.output["fields"])}
    return checks[field_key(seeded.fields[name].id)].label


def without_labels(result: MetadataResult) -> list[FieldCheck]:
    return [
        replace(check, label=None) for check in checks_from_json(result.result.output["fields"])
    ]


async def test_each_value_s_label_is_checked_by_its_type(world: World) -> None:
    seeded, result = await read(world, labelled())
    assert label(seeded, result, "Rechnungsbetrag") == LabelCheck(
        "Gesamtbetrag", LabelOutcome.BESIDE
    )
    assert label(seeded, result, "Fällig am") == LabelCheck("Zahlbar bis", LabelOutcome.BESIDE)
    # Text and yes/no are not checked; the label is kept.
    assert label(seeded, result, "Rechnungsnummer") == LabelCheck(
        "Rechnung Nr.", LabelOutcome.UNKNOWN
    )
    assert label(seeded, result, "Bezahlt") == LabelCheck("Bezahlt", LabelOutcome.UNKNOWN)
    assert result.result.outcome is Outcome.OK


async def test_the_label_check_changes_no_outcome(world: World) -> None:
    paid = {"value": True, "evidence": "Zahlbar bis 15.04.2026."}
    seeded, plain = await read(world, extraction(a1=paid))
    for given, expected in [
        ("Arbeitspreis", LabelOutcome.APART),  # the line above, another column
        ("Endbetrag", LabelOutcome.LABEL_MISSING),
        (None, LabelOutcome.NO_LABEL),
    ]:
        _, result = await read(world, labelled(a3=given), seeded=seeded)
        assert label(seeded, result, "Rechnungsbetrag") == LabelCheck(given, expected)
        assert result.result.outcome is plain.result.outcome is Outcome.OK
        assert (result.result.reason, result.changes) == (plain.result.reason, plain.changes)
        assert without_labels(result) == without_labels(plain)


async def test_a_suggested_value_has_its_label_checked_too(world: World) -> None:
    wrong = {
        "value": {"amount": "84.20", "currency": "EUR"},
        "evidence": "Summe 84,20 €",
        "label": "Gesamtbetrag",
    }
    answer: Any = labelled()
    answer["fields"]["a3"] = wrong
    seeded, result = await read(world, answer)
    assert result.result.outcome is Outcome.UNCERTAIN
    assert label(seeded, result, "Rechnungsbetrag") == LabelCheck(
        "Gesamtbetrag", LabelOutcome.BESIDE
    )


async def test_without_the_words_of_the_parsed_text_nothing_is_found(world: World) -> None:
    seeded, result = await read(world, labelled(), structure={"text": INVOICE})  # Docling's
    assert label(seeded, result, "Rechnungsbetrag") == LabelCheck(
        "Gesamtbetrag", LabelOutcome.UNKNOWN
    )
    _, document = await invoice(world, seeded=seeded)
    await world.object_store.delete(structure_key(document.id))
    again = await fields_step(world, model(labelled())).run(document)
    assert isinstance(again, MetadataResult)
    assert label(seeded, again, "Fällig am") == LabelCheck("Zahlbar bis", LabelOutcome.UNKNOWN)
    assert again.result.outcome is Outcome.OK


async def test_an_unreadable_structure_is_skipped(world: World) -> None:
    seeded, document = await invoice(world)
    await world.object_store.put(structure_key(document.id), b"{", content_type="application/json")
    result = await fields_step(world, model(labelled())).run(document)
    assert isinstance(result, MetadataResult)
    assert label(seeded, result, "Rechnungsbetrag") == LabelCheck(
        "Gesamtbetrag", LabelOutcome.UNKNOWN
    )


async def test_a_failing_label_check_does_not_fail_the_node(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recorded only: a store that fails leaves the labels unknown, a failure of the check
    itself leaves them out; the outcome stays."""
    seeded, document = await invoice(world)
    get = world.object_store.get

    async def failing(key: str) -> bytes:
        if key == structure_key(document.id):
            raise OSError("the store is gone")
        return await get(key)

    monkeypatch.setattr(world.object_store, "get", failing)
    result = await fields_step(world, model(labelled())).run(document)
    assert isinstance(result, MetadataResult)
    assert result.result.outcome is Outcome.OK
    assert label(seeded, result, "Rechnungsbetrag") == LabelCheck(
        "Gesamtbetrag", LabelOutcome.UNKNOWN
    )
    monkeypatch.undo()

    def broken(*args: object) -> LabelCheck:
        raise ZeroDivisionError

    monkeypatch.setattr(nodes, "check_label", broken)
    _, document = await invoice(world, seeded=seeded)
    result = await fields_step(world, model(labelled())).run(document)
    assert isinstance(result, MetadataResult)
    assert result.result.outcome is Outcome.OK
    assert label(seeded, result, "Rechnungsbetrag") is None


async def test_fields_without_a_value_have_no_label_check(world: World) -> None:
    seeded, result = await read(world, extraction())
    assert label(seeded, result, "Bezahlt") is None  # no value given
    assert label(seeded, result, "Rechnungsbetrag") == LabelCheck(None, LabelOutcome.NO_LABEL)


async def test_the_labels_of_the_model_s_proposal_are_taken_over(world: World) -> None:
    seeded, document = await invoice(world)
    fields: Any = json.loads(json.dumps(FIELDS))
    for entry in fields:
        entry["label"] = LABELS[entry["key"]]
    signal = await judge(world, document, model(proposal(fields=fields)))
    assert isinstance(signal, MetadataResult)
    await record(world, document, Node.JUDGE, signal.result)
    document.document_type_id = seeded.types["Rechnung"].id
    result = await fields_step(world, None).run(document)
    assert isinstance(result, MetadataResult)
    assert result.result.input == {"taken_over": 4}
    assert label(seeded, result, "Rechnungsbetrag") == LabelCheck(
        "Gesamtbetrag", LabelOutcome.BESIDE
    )
    assert label(seeded, result, "Bezahlt") is None
