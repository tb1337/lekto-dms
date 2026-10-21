"""Aligning a migrated document with its source from three states: the migration's last values,
Lekto's, and the plan's."""

from typing import Any

from lekto_migration.align import KEPT, UPDATE, Alignment, align, current, same_value, uploaded

BASE: dict[str, Any] = {
    "title": "Electricity March",
    "contact_id": "acme",
    "document_type_id": "invoice",
    "topic_id": None,
    "document_date": "2024-03-31",
    "created_at": "2024-04-02T07:30:00+00:00",
    "tag_ids": ["tax"],
    "fields": {"amount": {"amount": "84.20", "currency": "EUR"}, "notes": "old notes"},
    "space_id": "default",
}
TYPES = {"amount": "amount", "count": "number", "notes": "text"}
PARENTS: dict[str, str | None] = {"tax/2024": "tax", "tax": None}


def run(
    now: dict[str, Any] | None = None, want: dict[str, Any] | None = None, **base: Any
) -> Alignment:
    had = {**BASE, **base}
    return align(
        had,
        {**had, **(now or {})},
        {**had, **(want or {})},
        parents=PARENTS,
        types=TYPES,
        unmanaged={"notes"},
    )


def test_nothing_changed_nothing_to_do() -> None:
    result = run()
    assert not result.needed and result.differences == []


def test_a_changed_plan_is_applied_where_lekto_still_has_the_migrations_value() -> None:
    result = run(want={"contact_id": "nord", "topic_id": "energy"})
    assert result.changes == {"contact_id": "nord", "topic_id": "energy"}
    assert {d.what: d.action for d in result.differences} == {
        "contact_id": UPDATE,
        "topic_id": UPDATE,
    }
    assert result.applied["contact_id"] == "nord"


def test_what_a_person_changed_stays() -> None:
    result = run(now={"contact_id": "chosen"}, want={"contact_id": "nord"})
    assert result.changes == {}
    (difference,) = result.differences
    assert (difference.what, difference.lekto, difference.plan, difference.action) == (
        "contact_id",
        "chosen",
        "nord",
        KEPT,
    )
    assert result.applied["contact_id"] == "acme"  # still what the migration set


def test_the_receipt_of_a_document_migrated_before_is_taken_over() -> None:
    log = [
        {
            "node": "receive",
            "started_at": "2026-10-10T08:00:00+00:00",
            "output": {"imported": {"title": "Electricity March", "tag_ids": ["tax"]}},
        }
    ]
    base = uploaded(log, "default")
    assert base is not None and base["created_at"] == "2026-10-10T08:00:00+00:00"
    now = {**base, "created_at": "2026-10-10T08:00:01.250000+00:00"}
    want = {**base, "created_at": "2024-04-02T09:30:00+02:00"}
    result = align(base, now, want, parents=PARENTS, types=TYPES)
    assert result.changes == {"created_at": "2024-04-02T09:30:00+02:00"}
    # A receipt a person set since stays.
    moved = {**now, "created_at": "2025-01-01T00:00:00+00:00"}
    assert align(base, moved, want, parents=PARENTS, types=TYPES).changes == {}
    # Not taken over: nothing to do.
    assert not align(base, now, {**want, "created_at": None}, parents=PARENTS, types=TYPES).needed


def test_the_same_moment_in_another_zone_is_no_difference() -> None:
    assert not run(now={"created_at": "2024-04-02T09:30:00+02:00"}).needed


def test_tags_the_plan_adds_and_drops_and_those_a_person_removed() -> None:
    result = run(want={"tag_ids": ["insurance"]})
    assert result.changes == {"tag_ids": ["insurance"]}
    assert {d.what: d.action for d in result.differences} == {
        "tag:insurance": UPDATE,
        "tag:tax": UPDATE,
    }
    removed = run(now={"tag_ids": []}, want={"tag_ids": ["tax"]})
    assert removed.changes == {}
    assert [(d.what, d.action) for d in removed.differences] == [("tag:tax", KEPT)]
    # A tag added in Lekto is not the migration's: it stays.
    added = run(now={"tag_ids": ["mine", "tax"]})
    assert not added.needed


def test_a_child_kept_alone_holds_its_parent_too() -> None:
    result = run(
        now={"tag_ids": ["tax/2024"]}, want={"tag_ids": ["tax", "tax/2024"]}, tag_ids=["tax"]
    )
    assert result.changes == {}


def test_fields_change_by_value_and_unmanaged_ones_stay() -> None:
    result = run(want={"fields": {"amount": {"amount": "90", "currency": "EUR"}, "count": "3"}})
    assert result.changes == {
        "fields": {"amount": {"amount": "90", "currency": "EUR"}, "count": "3"}
    }
    assert "notes" not in result.changes["fields"]  # the notes field of earlier migrations
    same = run(now={"fields": {"amount": {"amount": "84.2", "currency": "EUR"}, "notes": "x"}})
    assert not same.needed
    dropped = run(want={"fields": {}})
    assert dropped.changes == {"fields": {"amount": None}}
    assert "amount" not in dropped.applied["fields"]
    kept = run(
        now={"fields": {"amount": {"amount": "1", "currency": "EUR"}}},
        want={"fields": {"amount": {"amount": "2", "currency": "EUR"}}},
    )
    assert kept.changes == {} and kept.differences[0].action == KEPT


def test_a_document_moves_where_the_plan_wants_it_unless_someone_moved_it() -> None:
    result = run(want={"space_id": "shared"})
    assert result.move == "shared" and result.changes == {}
    assert not run(now={"space_id": "elsewhere"}, want={"space_id": "shared"}).move


def test_current_reads_the_details() -> None:
    values = current({"title": "x", "tag_ids": ["b", "a"], "fields": None, "space_id": "s"})
    assert values["tag_ids"] == ["a", "b"] and values["fields"] == {}
    assert values["contact_id"] is None and values["space_id"] == "s"
    assert uploaded([{"node": "receive", "output": {}}], None) is None


def test_values_compare_by_value() -> None:
    assert same_value("12", "1.2E+1", "number")
    assert same_value(
        {"amount": "99.90", "currency": "EUR"}, {"amount": "9.99E+1", "currency": "EUR"}, "amount"
    )
    assert not same_value(
        {"amount": "1", "currency": "EUR"}, {"amount": "1", "currency": "USD"}, "amount"
    )
    assert not same_value("x", None, "text") and same_value(None, None, "text")
