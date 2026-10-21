"""The migration plan: what it may say, what it refuses, and that it keeps a person's comments;
and the selection of documents by it."""

from pathlib import Path
from typing import Any

import pytest

from lekto_migration import plan as plans
from lekto_migration.plan import PlanError, Target
from lekto_migration.select import Names, selected

EXAMPLE = """\
# The plan of the move to Lekto.
source: http://paperless:8000
target: http://lekto:8000

settings:
  currency: EUR
  fallback_owner: tobi
  take_over_added: true
  space_name: "Geteilt: {members}"

documents:
  include:
    added: {from: 2018-01-01}
  exclude:
    tags: [Privat]

users:
  Tobias: {to: user, name: tobi}
  anna: [{to: user, name: anna, create: true}, {to: tag, name: Anna}]
  scanner: drop

correspondents:
  Telekom: {to: contact, name: Deutsche Telekom AG}
  Sonstiges: {review: Resolve the contact in Lekto}   # kept for later

tags:
  Rechnung: {to: document_type, name: Rechnung, override: true}
  bezahlt: {to: field, name: Bezahlt, value: true, type: boolean, create: true}
  Krankenkasse:
    - {to: topic, name: Krankenversicherung, create: true}
    - {to: tag, name: Gesundheit, parent: Privates, create: true}
  Inbox: drop

custom_fields:
  Betrag: {to: field, name: Betrag}
  Rechnungsdatum: {to: document_date, override: true}
  Kategorie:
    values:
      Auto: {to: tag, name: Auto}
      Haus: [{to: topic, name: Wohnen}]
      Sonst: drop
  Versicherer: {to: contact, by_value: true, create: true, review: true}

storage_paths:
  Steuern: {to: tag, name: Steuern}

asn: {to: field, name: ASN}
"""


def parse(text: str) -> plans.Plan:
    return plans.parse(plans.yaml().load(text))


def problems(text: str) -> list[str]:
    with pytest.raises(PlanError) as raised:
        parse(text)
    return raised.value.problems


HEAD = "source: http://p\ntarget: http://l\n"


def test_a_plan_says_where_everything_goes() -> None:
    plan = parse(EXAMPLE)
    assert (plan.source, plan.target) == ("http://paperless:8000", "http://lekto:8000")
    assert plan.settings.fallback_owner == "tobi" and plan.settings.currency == "EUR"
    assert plan.selection.include == {"added": {"from": plans.yaml().load("2018-01-01")}}
    assert plan.selection.exclude == {"tags": ["Privat"]}

    tobias = plan.entry("users", "TOBIAS")
    assert tobias is not None and tobias.targets == (Target("user", "tobi"),)
    anna = plan.entry("users", "anna")
    assert anna is not None and [t.to for t in anna.targets] == ["user", "tag"]
    scanner = plan.entry("users", "scanner")
    assert scanner is not None and scanner.dropped

    other = plan.entry("correspondents", "Sonstiges")
    assert other is not None and other.dropped
    assert other.review_reason() == "Resolve the contact in Lekto"
    assert plan.entry("tags", "rechnung") == plans.Entry(
        "tags", "Rechnung", (Target("document_type", "Rechnung", override=True),)
    )
    paid = plan.entry("tags", "bezahlt")
    assert paid is not None and paid.targets[0].value is True
    assert paid.targets[0].type == "boolean" and paid.targets[0].create
    health = plan.entry("tags", "Krankenkasse")
    assert health is not None and health.targets[1].parent == "Privates"
    assert health.targets[1].scope == "document" and health.targets[0].scope == "topic"

    kind = plan.entry("custom_fields", "Kategorie")
    assert kind is not None and kind.targets == ()
    assert kind.values["Auto"] == (Target("tag", "Auto"),)
    assert kind.values["Sonst"] == ()
    insurer = plan.entry("custom_fields", "Versicherer")
    assert insurer is not None and insurer.targets[0].by_value
    assert insurer.review_reason() == "Paperless custom field 'Versicherer': to be checked in Lekto"
    date = plan.entry("custom_fields", "Rechnungsdatum")
    assert date is not None and date.targets == (Target("document_date", override=True),)
    assert plan.asn.targets == (Target("field", "ASN"),)
    assert plan.entry("tags", "unknown") is None


def test_a_missing_section_is_empty_and_asn_is_dropped_by_default() -> None:
    plan = parse(HEAD)
    assert plan.entries["tags"] == {} and plan.asn.dropped
    assert plan.settings == plans.Settings()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("source: ''\ntarget: http://l\n", "source:"),
        (HEAD + "other: 1\n", "unknown section 'other'"),
        (HEAD + "tags: [a]\n", "tags: a mapping"),
        (HEAD + "tags:\n  a: {to: shelf, name: x}\n", "tags.a.to: one of"),
        (HEAD + "tags:\n  a: {to: user, name: x}\n", "only a Paperless user"),
        (HEAD + "tags:\n  a: {to: tag}\n", "'name' says which"),
        (HEAD + "tags:\n  a: {to: field, name: X}\n", "'value' says what"),
        (HEAD + "tags:\n  a: {to: tag, name: X, value: 1}\n", "value: only for"),
        (HEAD + "tags:\n  a: {to: tag, by_value: true}\n", "by_value"),
        (HEAD + "tags:\n  a: {to: tag, name: X, type: text}\n", "type: for a field"),
        (HEAD + "tags:\n  a: {to: field, name: X, value: 1, type: blob}\n", "type: for a field"),
        (HEAD + "tags:\n  a: {to: contact, name: X, parent: Y}\n", "parent:"),
        (HEAD + "tags:\n  a: {to: document_date, value: soon}\n", "a date such as"),
        (HEAD + "tags:\n  a: {to: tag, name: X, create: yes please}\n", "create: true or false"),
        (HEAD + "tags:\n  a: {name: X}\n", "a target needs 'to'"),
        (HEAD + "tags:\n  a: {to: tag, name: X, colour: red}\n", "unknown key 'colour'"),
        (HEAD + "tags:\n  a: 7\n", "a target, a list of targets or drop"),
        (HEAD + "tags:\n  a: drop\n  A: drop\n", "in the plan twice"),
        (HEAD + "tags:\n  a: {values: {x: {to: tag, name: y}}}\n", "only a custom field"),
        (HEAD + "custom_fields:\n  a: {to: field, name: X, value: 1}\n", "value: only for"),
        (HEAD + "custom_fields:\n  a: {to: document_date, name: X}\n", "no 'name' here"),
        (HEAD + "users:\n  a: {to: tag, name: X}\n", "exactly one Lekto user"),
        (HEAD + "users:\n  a: [{to: user, name: x}, {to: user, name: y}]\n", "exactly one"),
        (HEAD + "tags:\n  a: {to: tag, name: X, review: 12}\n", "review: true, or a reason"),
        (HEAD + "settings: {currency: euro}\n", "settings.currency"),
        (HEAD + "settings: {space_name: Shared}\n", "settings.space_name"),
        (HEAD + "settings: {space_name: 'Geteilt: {shares}'}\n", "{shares} is now {members}"),
        (HEAD + "settings: {text_threshold: 2}\n", "settings.text_threshold"),
        (HEAD + "settings: {take_over_added: maybe}\n", "settings.take_over_added"),
        (HEAD + "settings: {colour: red}\n", "settings.colour"),
        (HEAD + "documents: {include: {colour: red}}\n", "unknown criterion"),
        (HEAD + "documents: {sometimes: {}}\n", "only include and exclude"),
    ],
)
def test_what_a_plan_may_not_say(body: str, expected: str) -> None:
    found = problems(body)
    assert any(expected in problem for problem in found), found


def test_every_problem_is_named_at_once() -> None:
    found = problems(HEAD + "tags:\n  a: {to: shelf}\n  b: {to: tag}\nsettings: {currency: x}\n")
    assert len(found) == 3


def test_writing_it_back_keeps_the_comments(tmp_path: Path) -> None:
    path = tmp_path / "migration-plan.yaml"
    path.write_text(EXAMPLE)
    plan, document = plans.load(path)
    document["correspondents"]["Neu"] = "drop"
    plans.dump(document, path)
    text = path.read_text()
    assert text.startswith("# The plan of the move to Lekto.")
    assert "# kept for later" in text
    again, _ = plans.load(path)
    assert again.entry("correspondents", "neu") is not None
    assert again.entries["tags"] == plan.entries["tags"]


def test_a_plan_that_is_no_yaml_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "migration-plan.yaml"
    path.write_text("tags: [unclosed\n")
    with pytest.raises(PlanError, match="not valid YAML"):
        plans.load(path)
    path.write_text("- a list\n")
    with pytest.raises(PlanError, match="mapping"):
        plans.load(path)
    with pytest.raises(PlanError):
        plans.load(tmp_path / "missing.yaml")


# --- selection --------------------------------------------------------------------------------

NAMES = Names(
    users={1: "tobias", 2: "anna", 3: "bob"},
    correspondents={1: "ACME Energy"},
    document_types={1: "Invoice"},
    storage_paths={1: "Bank"},
    tags={1: "tax", 2: "Privat"},
    custom_fields={
        1: {"id": 1, "name": "Amount", "data_type": "monetary"},
        2: {
            "id": 2,
            "name": "Kind",
            "data_type": "select",
            "extra_data": {"select_options": [{"id": "a", "label": "Car"}]},
        },
        3: {"id": 3, "name": "Due", "data_type": "date"},
    },
    members={7: frozenset({3})},
)
DOCUMENT: dict[str, Any] = {
    "id": 10,
    "title": "Electricity March",
    "created": "2024-05-01",
    "added": "2024-05-02T09:30:00+02:00",
    "modified": "2024-06-01T00:00:00Z",
    "owner": 1,
    "correspondent": 1,
    "document_type": None,
    "storage_path": 1,
    "tags": [1],
    "archive_serial_number": 77,
    "custom_fields": [
        {"field": 1, "value": "EUR12.50"},
        {"field": 2, "value": "a"},
        {"field": 3, "value": "2024-06-30"},
    ],
    "notes": [],
    "permissions": {"view": {"users": [2], "groups": [7]}, "change": {"users": [], "groups": []}},
    "original_file_name": "scan.pdf",
    "mime_type": "application/pdf",
}


@pytest.mark.parametrize(
    ("criteria", "expected"),
    [
        ({}, True),
        ({"id": [10, 11]}, True),
        ({"id": {"from": 11}}, False),
        ({"asn": {"from": 70, "to": 80}}, True),
        ({"title": "electricity"}, True),
        ({"title": {"matches": "^Elec.*h$"}}, True),
        ({"original_file_name": {"contains": ".jpg"}}, False),
        ({"mime_type": ["image/jpeg", "application/pdf"]}, True),
        ({"correspondent": "acme energy"}, True),
        ({"document_type": [None]}, True),
        ({"document_type": "Invoice"}, False),
        ({"storage_path": ["Bank"]}, True),
        ({"owner": "anna"}, False),
        ({"tags": "TAX"}, True),
        ({"tags": {"all": ["tax", "Privat"]}}, False),
        ({"tags": {"none": ["Privat"]}}, True),
        ({"shared_with": "bob"}, True),  # through the group
        ({"shared_with": ["tobias"]}, False),  # the owner is no share
        ({"created": {"from": "2024-01-01", "to": "2024-12-31"}}, True),
        ({"added": {"to": "2024-05-01"}}, False),
        ({"modified": {"from": "2024-06-01"}}, True),
        ({"has_notes": True}, False),
        ({"custom_fields": {"Amount": True}}, True),
        ({"custom_fields": {"Amount": {"from": 10, "to": 20}}}, True),
        ({"custom_fields": {"Kind": "car"}}, True),
        ({"custom_fields": {"Due": {"from": "2024-07-01"}}}, False),
        ({"custom_fields": {"Missing": False}}, True),
        ({"correspondent": "acme energy", "owner": "tobias"}, True),
        ({"correspondent": "acme energy", "owner": "bob"}, False),
    ],
)
def test_include_needs_every_criterion(criteria: dict[str, Any], expected: bool) -> None:
    assert selected(plans.Selection(include=criteria), DOCUMENT, NAMES) is expected


def test_exclude_needs_one_criterion() -> None:
    exclude = {"tags": "Privat", "owner": "tobias"}
    assert not selected(plans.Selection(exclude=exclude), DOCUMENT, NAMES)
    assert selected(plans.Selection(exclude={"tags": "Privat"}), DOCUMENT, NAMES)
    both = plans.Selection(include={"correspondent": "ACME Energy"}, exclude={"asn": [77]})
    assert not selected(both, DOCUMENT, NAMES)
