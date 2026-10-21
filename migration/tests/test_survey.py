"""The first plan from what Paperless and Lekto hold, and adding to it what changed."""

from datetime import date
from pathlib import Path

from lekto_migration import plan as plans
from lekto_migration.directory import Directory
from lekto_migration.fake_paperless import sample_archive
from lekto_migration.paperless import Snapshot
from lekto_migration.survey import draft, merge
from tests.conftest import PDF

TODAY = date(2026, 10, 21)


def snapshot() -> Snapshot:
    archive = sample_archive(PDF)
    return Snapshot(
        version="3.3.0",
        users=archive.users,
        groups=archive.groups,
        correspondents=archive.correspondents,
        document_types=archive.document_types,
        tags=archive.tags,
        custom_fields=archive.custom_fields,
        storage_paths=archive.storage_paths,
        documents=archive.documents,
    )


def lekto() -> Directory:
    directory = Directory({"id": "admin", "username": "root"})
    directory.add("contact", {"id": "c1", "name": "acme energy"})
    directory.add("field", {"id": "f1", "name": "Net", "data_type": "amount"})
    directory.add("user", {"id": "u1", "username": "Anna"})
    return directory


def test_the_first_plan_takes_everything_over_by_name() -> None:
    plan = plans.parse(draft(snapshot(), lekto(), source="http://p", target="http://l"))
    assert (plan.source, plan.target) == ("http://p", "http://l")
    assert plan.settings == plans.Settings()

    anna, bob = plan.entry("users", "anna"), plan.entry("users", "bob")
    assert anna is not None and anna.targets == (plans.Target("user", "anna"),)
    assert bob is not None and bob.targets == (plans.Target("user", "bob", create=True),)
    # "ACME Energy" and "acme energy" are one name; Lekto has it already.
    assert list(plan.entries["correspondents"]) == ["acme energy", "unused"]
    acme = plan.entry("correspondents", "ACME ENERGY")
    assert acme is not None and acme.targets == (plans.Target("contact", "ACME Energy"),)
    child = plan.entry("tags", "tax/2024")
    assert child is not None
    assert child.targets == (plans.Target("tag", "tax/2024", parent="tax", create=True),)
    net, kind = plan.entry("custom_fields", "Net"), plan.entry("custom_fields", "Kind")
    assert net is not None and net.targets == (plans.Target("field", "Net"),)
    assert kind is not None
    assert kind.targets == (plans.Target("field", "Kind", type="choice", create=True),)
    related, bank = plan.entry("custom_fields", "Related"), plan.entry("storage_paths", "Bank")
    assert related is not None and related.dropped and bank is not None and bank.dropped
    assert plan.asn.targets == (plans.Target("field", "ASN", type="number", create=True),)


def test_the_first_plan_explains_itself() -> None:
    text = plans.text(draft(snapshot(), lekto(), source="http://p", target="http://l"))
    assert text.startswith("# Lekto migration plan")
    assert "# data type 'documentlink' has no counterpart in Lekto" in text
    assert "Lekto has no storage paths" in text


def test_without_serial_numbers_the_asn_is_dropped() -> None:
    source = snapshot()
    for document in source.documents:
        document["archive_serial_number"] = None
    assert plans.parse(draft(source, lekto(), source="p", target="l")).asn.dropped


def test_adding_what_is_new_keeps_what_a_person_wrote(tmp_path: Path) -> None:
    source = snapshot()
    document = draft(source, lekto(), source="http://p", target="http://l")
    path = tmp_path / "migration-plan.yaml"
    plans.dump(document, path)
    edited = path.read_text().replace(
        "  Unused: {to: contact, name: Unused, create: true}",
        "  Unused: drop  # nobody writes to us",
    )
    path.write_text(edited)
    _, document = plans.load(path)

    source.tags.append({"id": 9, "name": "Insurance", "parent": None})
    source.document_types.clear()
    changes = merge(document, source, lekto(), TODAY)
    assert changes.added == ["tags.Insurance"]
    assert changes.gone == ["document_types.Invoice"]
    plans.dump(document, path)
    text = path.read_text()
    assert (
        "Insurance: {to: tag, name: Insurance, create: true}  # new in Paperless (2026-10-21)"
        in text
    )
    assert "# not in Paperless (2026-10-21)" in text
    assert "Unused: drop  # nobody writes to us" in text

    _, document = plans.load(path)
    assert not merge(document, source, lekto(), date(2026, 10, 22))  # nothing new


def test_a_section_the_person_removed_comes_back() -> None:
    document = draft(snapshot(), lekto(), source="p", target="l")
    del document["tags"]
    del document["asn"]
    changes = merge(document, snapshot(), lekto(), TODAY)
    assert changes.added == ["tags.tax", "tags.tax/2024", "asn"]
