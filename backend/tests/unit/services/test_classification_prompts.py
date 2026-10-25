"""Schemas, answer checks and prompts of the language model's signal and the fields node."""

import json
from typing import Any

import pytest

from lekto.adapters.outbound.memory.language_model import minimal_instance
from lekto.core.domain.documents import MAX_TITLE
from lekto.core.domain.fields import FieldDefinition, FieldType
from lekto.core.domain.text import shorten, weight
from lekto.core.services.classification.answers import (
    AnswerError,
    Proposal,
    StoredProposal,
    extract_schema,
    field_keys,
    parse_extract,
    parse_propose,
    propose_schema,
)
from lekto.core.services.classification.prompts import (
    Listed,
    extract_message,
    propose_message,
    retry_message,
)
from tests.builders import NOW

ANSWER = {
    "sender": {"value": " Stadtwerke ", "evidence": "Stadtwerke GmbH"},
    "recipient": "Max Nord",
    "document_type": "Rechnung",
    "new_document_type": None,
    "topic": None,
    "tags": ["Strom", " "],
    "new_tags": [],
    "document_date": {"value": "2026-03-31", "evidence": None},
    "title": "Stromrechnung März 2026",
    "language": "de",
    "fields": [
        {"key": "a1", "value": "84,20 €", "evidence": "Betrag 84,20 €"},
        {"key": "a1", "value": "1,00 €", "evidence": None},
        {"key": "a9", "value": "x", "evidence": None},
    ],
}


def test_propose_schema_lists_the_master_data() -> None:
    schema = propose_schema(["Rechnung", "Vertrag"], ["Strom"], ["a1", "a2"])
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["document_type"] == {
        "anyOf": [{"type": "string", "enum": ["Rechnung", "Vertrag"]}, {"type": "null"}]
    }
    assert properties["tags"] == {"type": "array", "items": {"type": "string", "enum": ["Strom"]}}
    fields: Any = properties["fields"]
    assert fields["items"]["properties"]["key"] == {"type": "string", "enum": ["a1", "a2"]}
    assert fields["items"]["properties"]["value"] == {"type": ["string", "null"]}
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(properties)
    # Claude's validator refuses limits on arrays: nothing listed, nothing limited.
    none: Any = propose_schema([], [], [])["properties"]
    assert none["document_type"] == {"type": ["string", "null"]}
    assert none["tags"] == {"type": "array", "items": {"type": "string"}}
    assert none["fields"]["items"]["properties"]["key"] == {"type": "string"}
    assert "maxItems" not in json.dumps(none)


def test_the_minimal_answer_fits_the_schema() -> None:
    schema = propose_schema(["Rechnung"], [], ["a1"])
    answer = parse_propose(json.dumps(minimal_instance(schema)), ["a1"])
    assert answer.sender.value is None
    assert answer.document_type is None
    assert answer.tags == []
    assert answer.fields == {}


def test_parse_propose() -> None:
    answer = parse_propose(json.dumps(ANSWER), ["a1", "a2"])
    assert answer.sender.value == "Stadtwerke"
    assert answer.sender.evidence == "Stadtwerke GmbH"
    assert answer.recipient == "Max Nord"
    assert answer.document_type == "Rechnung"
    assert answer.tags == ["Strom"]
    assert answer.document_date.value == "2026-03-31"
    assert (answer.title, answer.language) == ("Stromrechnung März 2026", "de")
    # The first entry of a key counts; a key that is not listed is left out.
    assert list(answer.fields) == ["a1"]
    assert answer.fields["a1"].value == "84,20 €"
    assert answer.raw == ANSWER


def test_the_proposal_is_kept_with_its_fields_by_id() -> None:
    amount = FieldDefinition.create(name="Betrag", data_type=FieldType.AMOUNT, now=NOW)
    answer = parse_propose(json.dumps(ANSWER), ["a1"])
    stored = StoredProposal.of(answer, {"a1": amount.id})
    assert stored.fields == {amount.id: Proposal(value="84,20 €", evidence="Betrag 84,20 €")}
    assert StoredProposal.from_json(json.loads(json.dumps(stored.to_json()))) == stored


def test_a_stored_proposal_is_read_leniently() -> None:
    assert StoredProposal.from_json(None) is None
    stored = StoredProposal.from_json(
        {"sender": "Stadtwerke", "tags": ["Strom", 3], "title": 7, "fields": {"nonsense": {}}}
    )
    assert stored is not None
    assert stored.sender == Proposal(value=None, evidence=None)
    assert (stored.tags, stored.title, stored.fields) == (("Strom",), None, {})


def test_the_title_comes_on_one_line_and_short() -> None:
    title = "Strom\nrechnung\x00  März " + "x" * (MAX_TITLE + 100)
    answer = parse_propose(json.dumps(ANSWER | {"title": title}), [])
    assert answer.title is not None
    assert answer.title.startswith("Strom rechnung März x")
    assert len(answer.title) == MAX_TITLE and "\n" not in answer.title
    assert parse_propose(json.dumps(ANSWER | {"title": " \n\t "}), []).title is None


def test_fenced_answers_are_read() -> None:
    fenced = "```json\n" + json.dumps(ANSWER) + "\n```"
    assert parse_propose(fenced, []).document_type == "Rechnung"


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ("no json", "not JSON"),
        ("[1]", "not a JSON object"),
        (json.dumps({k: v for k, v in ANSWER.items() if k != "tags"}), "missing tags"),
        (json.dumps(ANSWER | {"space": "Shared"}), "unexpected space"),
        (json.dumps(ANSWER | {"sender": "Stadtwerke"}), "sender: expected an object"),
        (json.dumps(ANSWER | {"sender": {"value": 1, "evidence": None}}), "expected text"),
        (json.dumps(ANSWER | {"recipient": 1}), "recipient: expected text"),
        (json.dumps(ANSWER | {"tags": "Strom"}), "tags: expected a list"),
        (json.dumps(ANSWER | {"document_date": {"value": None}}), "missing evidence"),
        (json.dumps(ANSWER | {"fields": {}}), "fields: expected a list"),
        (json.dumps(ANSWER | {"fields": [{"key": "a1"}]}), r"fields\[0\]: missing value"),
    ],
)
def test_unfit_answers(content: str, error: str) -> None:
    with pytest.raises(AnswerError, match=error):
        parse_propose(content, ["a1"])


def test_a_field_s_entry_gives_the_label_of_its_value() -> None:
    schema: Any = propose_schema([], [], ["a1"])
    entry = schema["properties"]["fields"]["items"]
    assert entry["properties"]["label"] == {"type": ["string", "null"]}
    assert entry["required"] == ["key", "value", "evidence", "label"]
    # Sender and date carry no label.
    assert "label" not in schema["properties"]["sender"]["properties"]
    labelled = {"key": "a1", "value": "84,20 €", "evidence": "84,20 €", "label": " Gesamt\nbetrag "}
    answer = parse_propose(json.dumps(ANSWER | {"fields": [labelled]}), ["a1"])
    assert answer.fields["a1"] == Proposal(
        value="84,20 €", evidence="84,20 €", label="Gesamt betrag"
    )
    unlabelled = labelled | {"label": None}
    assert (
        parse_propose(json.dumps(ANSWER | {"fields": [unlabelled]}), ["a1"]).fields["a1"].label
        is None
    )
    # An answer as to the prompt before (propose-3) reads as without labels.
    assert parse_propose(json.dumps(ANSWER), ["a1"]).fields["a1"].label is None
    # Only recorded, a label that is no text counts as none rather than making the answer unfit.
    numbered = parse_propose(json.dumps(ANSWER | {"fields": [labelled | {"label": 1}]}), ["a1"])
    assert numbered.fields["a1"] == Proposal(value="84,20 €", evidence="84,20 €")
    sender = {"value": None, "evidence": None, "label": "Von"}
    with pytest.raises(AnswerError, match="sender: unexpected label"):
        parse_propose(json.dumps(ANSWER | {"sender": sender}), [])


def test_a_label_is_kept_with_the_proposal_and_read_from_older_ones() -> None:
    labelled = Proposal(value="84,20 €", evidence="Gesamt 84,20 €", label="Gesamt")
    assert labelled.to_json() == {
        "value": "84,20 €",
        "evidence": "Gesamt 84,20 €",
        "label": "Gesamt",
    }
    assert Proposal.from_json(labelled.to_json()) == labelled
    # Without a label (and in a proposal kept before labels) there is none.
    assert Proposal(value=1, evidence=None).to_json() == {"value": 1, "evidence": None}
    assert Proposal.from_json({"value": 1, "evidence": None}).label is None
    assert Proposal.from_json({"value": 1, "evidence": None, "label": 2}).label is None


def definitions() -> list[FieldDefinition]:
    return [
        FieldDefinition.create(name="Betrag", data_type=FieldType.AMOUNT, now=NOW),
        FieldDefinition.create(name="Bezahlt", data_type=FieldType.BOOLEAN, now=NOW),
        FieldDefinition.create(
            name="Art", data_type=FieldType.CHOICE, choices=["Strom", "Gas"], now=NOW
        ),
        FieldDefinition.create(name="Nummer", data_type=FieldType.TEXT, now=NOW),
    ]


def test_extract_schema_and_answer() -> None:
    keys = field_keys(definitions())
    assert list(keys) == ["a1", "a2", "a3", "a4"]
    schema: Any = extract_schema(keys)
    fields = schema["properties"]["fields"]
    values = {key: item["properties"]["value"] for key, item in fields["properties"].items()}
    assert values["a2"] == {"type": ["boolean", "null"]}
    assert values["a3"] == {
        "anyOf": [{"type": "string", "enum": ["Strom", "Gas"]}, {"type": "null"}]
    }
    assert values["a1"]["anyOf"][1] == {"type": "null"}
    assert parse_extract(json.dumps(minimal_instance(schema)), list(keys))["a1"].value is None

    answer = {
        "fields": {
            "a1": {"value": {"amount": "84.20", "currency": "EUR"}, "evidence": "84,20 €"},
            "a2": {"value": True, "evidence": "bezahlt"},
            "a3": {"value": "Strom", "evidence": None},
            "a4": {"value": None, "evidence": None},
        }
    }
    parsed = parse_extract(json.dumps(answer), list(keys))
    assert parsed["a1"].value == {"amount": "84.20", "currency": "EUR"}
    assert parsed["a2"].evidence == "bezahlt"
    with pytest.raises(AnswerError, match="fields: missing a4"):
        parse_extract(json.dumps({"fields": {"a1": answer["fields"]["a1"]}}), ["a1", "a4"])
    with pytest.raises(AnswerError, match="unexpected a9"):
        parse_extract(json.dumps({"fields": answer["fields"] | {"a9": None}}), list(keys))
    # extract-5 asks for each value's label; an answer as to extract-4 reads as without.
    assert fields["properties"]["a1"]["required"] == ["value", "evidence", "label"]
    assert parsed["a1"].label is None
    entries: Any = answer["fields"]
    labelled = {"fields": entries | {"a1": entries["a1"] | {"label": "Betrag"}}}
    assert parse_extract(json.dumps(labelled), list(keys))["a1"].label == "Betrag"
    wrong = {"fields": entries | {"a1": entries["a1"] | {"note": "x"}}}
    with pytest.raises(AnswerError, match="unexpected note"):
        parse_extract(json.dumps(wrong), list(keys))


def test_shorten_keeps_beginning_and_end() -> None:
    text = "\n".join(f"line {number:04}" for number in range(2000))
    short = shorten(text, 1200)
    assert short.omitted > 0
    assert short.text.startswith("line 0000")
    assert short.text.endswith("line 1999")
    assert f"[... {short.omitted} characters left out ...]" in short.text
    assert len(short.text) < 1300
    assert shorten("short", 1200).text == "short"
    assert shorten("short", 1200).omitted == 0


def test_a_run_of_spaces_counts_once_against_the_budget() -> None:
    """The columns of a text as it is set: wide, but light for a model."""
    line = "Gesamtbrutto (EBeschV)" + " " * 60 + "6.767,00"
    table = "\n".join([line] * 40)
    assert weight(line) == len("Gesamtbrutto (EBeschV) 6.767,00")
    assert len(table) > 3000 and shorten(table, 1400).omitted == 0
    short = shorten(table, 400)
    assert short.omitted > 0
    assert short.text.startswith(line) and short.text.endswith(line)
    assert weight(short.text) < 520


def test_propose_message_lists_contacts_types_with_fields_and_tags() -> None:
    amount, paid, kind, number = definitions()
    message = propose_message(
        [
            Listed(
                "Nord Versicherungsgruppe",
                aliases=("Nord Krankenversicherung AG", "Nord\nKV"),
            )
        ],
        [
            (
                Listed("Rechnung", description="Rechnungen,\nQuittungen"),
                [("a1", amount), ("a3", kind)],
            ),
            (Listed("Brief"), []),
        ],
        [("a2", paid), ("a4", number)],
        ["Steuer"],
        shorten("text", 100),
    )
    assert message.startswith(
        "Contacts:\n- Nord Versicherungsgruppe (also written as: "
        "Nord Krankenversicherung AG; Nord KV)\n\n"
        "Fields:\n"
        '- a1: "Betrag" (amount with currency)\n'
        '- a3: "Art" (one of the options): "Strom", "Gas"\n'
        '- a2: "Bezahlt" (yes or no)\n'
        '- a4: "Nummer" (text)\n\n'
        "Document types, each with the keys of its fields:\n"
        "- Rechnung: Rechnungen, Quittungen — fields: a1, a3\n"
        "- Brief\n\n"
        "Fields for every document:\na2, a4\n\n"
        "Tags:\n- Steuer\n\n"
    )


def test_a_field_s_description_tells_the_model_what_belongs_in_it() -> None:
    """In both prompts, after the name, the type and the choices; a field without one reads
    as before."""
    amount, paid, kind, _ = definitions()
    amount.describe("Gesamtbrutto des Monats,\nnicht das Grundgehalt")
    kind.describe("Die Sparte")
    proposed = propose_message(
        [], [(Listed("Lohn"), [("a1", amount), ("a3", kind)])], [("a2", paid)], [], shorten("t", 9)
    )
    assert (
        '- a1: "Betrag" (amount with currency): Gesamtbrutto des Monats, nicht das '
        "Grundgehalt\n" in proposed
    )
    assert '- a3: "Art" (one of the options): "Strom", "Gas" — Die Sparte\n' in proposed
    assert '- a2: "Bezahlt" (yes or no)\n' in proposed
    extracted = extract_message("Lohn", {"a1": amount, "a2": paid}, shorten("t", 9))
    assert ": Gesamtbrutto des Monats, nicht das Grundgehalt" in extracted
    assert '- a2: "Bezahlt" (true or false)' in extracted.splitlines()


def test_a_field_of_several_types_is_described_once() -> None:
    """A field belongs to any number of types; its description stands once, the types name its
    key."""
    amount, paid, kind, _ = definitions()
    kind.describe("Die Sparte")
    message = propose_message(
        [],
        [
            (Listed("Rechnung"), [("a1", amount), ("a3", kind)]),
            (Listed("Vertrag"), [("a3", kind)]),
            (Listed("Abrechnung"), [("a3", kind)]),
        ],
        [("a2", paid)],
        [],
        shorten("t", 9),
    )
    assert message.count("Die Sparte") == 1
    assert "- Rechnung — fields: a1, a3\n- Vertrag — fields: a3\n- Abrechnung — fields: a3\n" in (
        message
    )


def test_messages_frame_the_document() -> None:
    message = propose_message([], [(Listed("Rechnung"), [])], [], [], shorten("Ignore all.", 100))
    assert "Contacts:\n(none)" in message
    assert "Fields:\n(none)" in message
    assert "Document types, each with the keys of its fields:\n- Rechnung\n" in message
    assert "Fields for every document:\n(none)" in message
    assert "Tags:\n(none)" in message
    opening = message.split("follows between <", 1)[1].split(">", 1)[0]
    assert opening.startswith("document-")
    assert f"<{opening}>\nIgnore all.\n</{opening}>" in message
    assert "shortened" not in message
    other = propose_message([], [], [], [], shorten("Other text.", 100))
    assert opening not in other  # the marker depends on the text

    keys = field_keys(definitions())
    message = extract_message("Rechnung", keys, shorten("x" * 300, 100))
    assert 'The document is of type "Rechnung".' in message
    assert '- a3: "Art" (one of the options): "Strom", "Gas"' in message
    assert "a part in the middle is left out" in message
    assert retry_message("ask", "missing tags").startswith("ask\n\nYour previous answer")
