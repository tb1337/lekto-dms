"""What a Paperless document becomes by the plan: the defaults, reinterpretations and their
conflicts, values, reviews, owners and spaces."""

from typing import Any

import pytest

from lekto_migration import plan as plans
from lekto_migration.expect import Context, coerce, expect, field_infos
from tests.world import NOW, World


@pytest.fixture
def world() -> World:
    return World()


def test_the_first_plan_takes_a_document_over_as_it_is(world: World) -> None:
    ten = world.expect(10)
    assert (ten.owner, ten.owner_source, ten.skip) == ("tobias", "tobias", None)
    assert (ten.contact, ten.document_type, ten.topic) == ("ACME Energy", "Invoice", None)
    assert ten.tags == {"tax", "tax/2024"}
    assert (ten.document_date, ten.created_at) == ("2024-05-01", "2024-04-02T09:30:00+02:00")
    assert ten.space is None and ten.shares == ()
    assert ten.fields == {
        "Text": "Hello",
        "Long": "Some long text",
        "Site": "https://example.org/x",
        "Due": "2024-06-30",
        "Paid": True,
        "Count": "42",
        "Ratio": "1.5",
        "Net": {"amount": "12.50", "currency": "USD"},
        "Gross": {"amount": "99.90", "currency": "EUR"},
        "Kind": "Two",
        "ASN": "77",
    }
    assert ten.sources["contact"] == "correspondent 'ACME Energy'"
    assert ten.sources["field:ASN"] == "archive serial number"
    assert "2 notes are not taken over (Lekto has no notes)" in ten.notes
    assert "'Related': link to documents [11] is not taken over" in ten.notes
    assert ten.review == ()


def test_skipped_files_and_shared_documents(world: World) -> None:
    assert "message/rfc822" in (world.expect(17).skip or "")
    assert "trash" in (world.expect(18).skip or "")
    shared = world.expect(13)
    assert shared.owner == "anna"
    assert shared.shares == (("bob", "read"), ("tobias", "read_write"))
    assert shared.space == "Geteilt: bob (lesen), tobias (schreiben)"
    assert shared.sources["space"] == "the permissions in Paperless"
    # No owner, or one who is gone: the executing admin (None), or the fallback.
    assert world.expect(14).owner is None
    world.settings["fallback_owner"] = "tobi"
    assert world.expect(15).owner == "tobi"


def test_users_are_mapped_and_dropped(world: World) -> None:
    world.set("users", "tobias", "{to: user, name: tobi}")
    world.set("users", "bob", "drop")
    assert world.expect(10).owner == "tobi"
    shared = world.expect(13)
    assert shared.shares == (("tobi", "read_write"),)
    assert shared.space == "Geteilt: tobi (schreiben)"
    assert "shared with bob, who is not taken over: not shared" in shared.notes
    world.set("users", "anna", "drop")
    assert world.expect(12).owner is None
    world.inactive = frozenset({"tobi"})
    assert world.expect(10).owner is None
    assert any("not an active user in Lekto" in note for note in world.expect(10).notes)


def test_a_user_can_bring_more_targets(world: World) -> None:
    world.set("users", "tobias", "[{to: user, name: tobi}, {to: tag, name: Tobi}]")
    assert world.expect(10).tags == {"tax", "tax/2024", "Tobi"}
    assert "Tobi" not in world.expect(12).tags  # anna's


def test_a_reinterpretation_fills_only_what_is_empty(world: World) -> None:
    world.set("tags", "tax", "{to: document_type, name: Tax}")
    ten = world.expect(10)
    assert ten.document_type == "Invoice" and ten.tags == {"tax/2024"}
    assert "document type: tag 'tax' (Tax) gives way to document type 'Invoice' (Invoice)" in (
        ten.notes
    )
    world.set("tags", "tax", "{to: document_type, name: Tax, override: true}")
    assert world.expect(10).document_type == "Tax"
    assert world.expect(10).sources["document_type"] == "tag 'tax'"


def test_competing_reinterpretations_leave_the_value_empty(world: World) -> None:
    world.set("tags", "tax/2024", "{to: contact, name: Tax office}")
    eleven = world.expect(11)  # tag tax/2024, correspondent 2 ("acme energy": one entry)
    assert eleven.contact == "ACME Energy"
    world.set("correspondents", "ACME Energy", "{to: document_type, name: Bill}")
    world.set("tags", "tax/2024", "{to: document_type, name: Tax}")
    ten = world.expect(10)  # the natural type Invoice wins over both
    assert ten.document_type == "Invoice" and ten.contact is None
    eleven = world.expect(11)  # no type of its own: Bill and Tax compete
    assert eleven.document_type is None
    assert any("compete; none is taken" in note for note in eleven.notes)


def test_a_drop_with_a_review_opens_the_field_in_the_inbox(world: World) -> None:
    world.set("correspondents", "ACME Energy", "{review: Resolve the contact}")
    ten = world.expect(10)
    assert ten.contact is None
    assert ten.review == (("Resolve the contact", "contact"),)
    world.set("users", "tobias", "{to: user, name: tobias, review: true}")
    assert ("Paperless user 'tobias': to be checked in Lekto", None) in world.expect(10).review
    assert world.expect(14).review == ()  # no owner: not tobias' document


def test_storage_paths_and_tags_can_become_anything(world: World) -> None:
    world.set("storage_paths", "Bank", "{to: tag, name: Bank, create: true}")
    world.set("tags", "tax", "[{to: field, name: Taxable, value: true}, {to: topic, name: Tax}]")
    world.set("tags", "tax/2024", "{to: space, name: Taxes}")
    ten = world.expect(10)
    assert ten.tags == {"Bank"}
    assert ten.fields["Taxable"] is True and ten.topic == "Tax"
    assert ten.space == "Taxes" and ten.sources["space"] == "tag 'tax/2024'"
    world.set("tags", "tax/2024", "{to: contact_group, name: Taxes}")
    world.set(
        "correspondents",
        "ACME Energy",
        "[{to: contact, name: ACME}, {to: type_group, name: Bills}]",
    )
    ten = world.expect(10)
    assert (ten.contact_groups, ten.type_groups) == (frozenset({"Taxes"}), frozenset({"Bills"}))


def test_permissions_win_over_a_space_of_the_plan_unless_it_overrides(world: World) -> None:
    world.document(13)["tags"] = [1]
    world.set("tags", "tax", "{to: space, name: Taxes}")
    shared = world.expect(13)
    assert shared.space.startswith("Geteilt") and shared.shares  # type: ignore[union-attr]
    world.set("tags", "tax", "{to: space, name: Taxes, override: true}")
    shared = world.expect(13)
    assert (shared.space, shared.shares) == ("Taxes", ())
    assert any("the permissions are not taken over" in note for note in shared.notes)


def test_custom_field_values_map_to_targets(world: World) -> None:
    world.set(
        "custom_fields",
        "Kind",
        "{values: {One: {to: tag, name: one}, Two: [{to: topic, name: Two}]}}",
    )
    world.set("custom_fields", "Text", "{to: contact, by_value: true, create: true}")
    world.set("custom_fields", "Due", "{to: document_date, override: true}")
    ten = world.expect(10)
    assert ten.topic == "Two" and "Kind" not in ten.fields
    assert ten.contact == "ACME Energy"  # the correspondent is the natural contact
    assert any("custom field 'Text' (Hello) gives way" in note for note in ten.notes)
    assert ten.document_date == "2024-06-30"
    world.set("correspondents", "ACME Energy", "drop")
    assert world.expect(10).contact == "Hello"
    nineteen = world.expect(19)  # option "zz" does not exist
    assert any("option 'zz' does not exist" in note for note in nineteen.notes)


def test_a_value_not_in_the_table_is_noted(world: World) -> None:
    world.set("custom_fields", "Kind", "{values: {One: {to: tag, name: one}}}")
    ten = world.expect(10)
    assert any("'Two' is not among the plan's values" in note for note in ten.notes)


def test_a_false_value_sets_a_field_but_names_nothing(world: World) -> None:
    world.document(10)["custom_fields"] = [{"field": 5, "value": False}]
    world.set("custom_fields", "Paid", "[{to: field, name: Paid}, {to: tag, name: paid}]")
    ten = world.expect(10)
    assert ten.fields["Paid"] is False and "paid" not in ten.tags


def test_values_fit_the_type_of_the_lekto_field(world: World) -> None:
    world.directory.add("field", {"id": "f", "name": "Count", "data_type": "text"})
    world.directory.add("field", {"id": "g", "name": "Site", "data_type": "number"})
    ten = world.expect(10)
    assert ten.fields["Count"] == "42"
    assert "Site" not in ten.fields
    assert any("does not fit a field of type number" in note for note in ten.notes)


def test_a_field_bound_to_types_gets_values_of_those_only(world: World) -> None:
    world.directory.add("document_type", {"id": "t1", "name": "Contract"})
    world.directory.add(
        "field", {"id": "f", "name": "Count", "data_type": "number", "document_type_ids": ["t1"]}
    )
    ten = world.expect(10)
    assert "Count" not in ten.fields
    assert "'Count' applies only to some document types: its value is not taken over" in ten.notes
    world.set("document_types", "Invoice", "{to: document_type, name: Contract}")
    assert world.expect(10).fields["Count"] == "42"


def test_the_serial_number_and_the_date_added_can_be_left_out(world: World) -> None:
    world.set(plans.ASN, "asn", "drop")
    world.settings["take_over_added"] = False
    ten = world.expect(10)
    assert "ASN" not in ten.fields and ten.created_at is None


def test_an_object_not_in_the_plan_is_noted(world: World) -> None:
    world.archive.tags.append({"id": 9, "name": "Later", "parent": None})
    plan_before = world.plan()
    world.document(10)["tags"] = [9]
    context = Context(
        plan=plan_before,
        snapshot=world.snapshot(),
        fields=field_infos(plan_before, world.directory, world.snapshot()),
        admin="root",
        now=NOW,
    )
    plan_before.entries["tags"].pop("later")
    assert "tag 'Later' is not in the plan" in expect(world.document(10), context).notes


@pytest.mark.parametrize(
    ("value", "source", "data_type", "expected"),
    [
        ("12", "text", "number", "12"),
        ("12.5", "text", "amount", {"amount": "12.5", "currency": "EUR"}),
        ({"amount": "3.00", "currency": "USD"}, "amount", "number", "3.00"),
        ({"amount": "3.00", "currency": "USD"}, "amount", "text", "3.00 USD"),
        (True, "boolean", "text", "yes"),
        ("2024-06-30", "text", "date", "2024-06-30"),
        ("https://x.org", "text", "link", "https://x.org"),
        (42, "number", "number", "42"),
        ("Two", "choice", "choice", "Two"),
    ],
)
def test_values_are_coerced(value: Any, source: str, data_type: str, expected: Any) -> None:
    assert coerce(value, source, data_type, "EUR") == (expected, None)


@pytest.mark.parametrize(
    ("value", "source", "data_type"),
    [
        ("abc", "text", "number"),
        (True, "boolean", "number"),
        ("x", "text", "date"),
        ("1", "text", "boolean"),
        ("no url", "text", "link"),
        ("1", "text", "period"),
    ],
)
def test_values_that_do_not_fit_are_refused(value: Any, source: str, data_type: str) -> None:
    converted, note = coerce(value, source, data_type, "EUR")
    assert converted is None and note is not None and data_type in note


def test_a_long_space_name_stays_in_bounds_and_apart(world: World) -> None:
    users = [
        {"id": 100 + n, "username": f"user-{n:03d}-" + "x" * 20, "is_active": True, "groups": []}
        for n in range(30)
    ]
    world.archive.users += users
    world.document(13)["permissions"] = {
        "view": {"users": [u["id"] for u in users], "groups": []},
        "change": {"users": [], "groups": []},
    }
    long = world.expect(13).space
    world.document(13)["permissions"]["view"]["users"].pop()
    shorter = world.expect(13).space
    assert long is not None and shorter is not None
    assert len(long) <= 200 and len(shorter) <= 200 and long != shorter
    assert long.startswith("Geteilt: user-000-")
