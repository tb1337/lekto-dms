from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from lekto.core.domain.documents import (
    UNSET,
    Document,
    DocumentChanges,
    Sha256,
    checked_fields,
    confirms,
)
from lekto.core.domain.errors import NotFoundError, ValidationError
from lekto.core.domain.events import (
    DocumentDeleted,
    DocumentFiled,
    DocumentMoved,
    DocumentReceived,
    DocumentUpdated,
    NodeCompleted,
)
from lekto.core.domain.fields import FieldDefinition, FieldType
from lekto.core.domain.ids import ContactId, DocumentTypeId, TagId, new_id
from lekto.core.domain.pipeline import Node
from tests import builders
from tests.builders import FAILED, NOW, OK, UNCERTAIN

LATER = NOW + timedelta(minutes=5)


def test_sha256_is_lower_case_hex() -> None:
    assert Sha256.of(b"abc").hex.startswith("ba7816bf")
    assert str(Sha256.of(b"abc")) == Sha256.of(b"abc").hex
    for invalid in ("ABC", "g" * 64, "a" * 63, "A" * 64):
        with pytest.raises(ValidationError):
            Sha256(invalid)


def test_receive_records_received_and_step_completed() -> None:
    owner = builders.user()
    document = Document.receive(
        uploaded_by=owner.id,
        space_id=builders.personal_space(owner).id,
        sha256=builders.sha256(),
        original_filename="2026-10 Invoice.pdf",
        media_type="application/pdf",
        result=UNCERTAIN,
        now=NOW,
    )
    assert document.title == "2026-10 Invoice"
    events = document.pull_events()
    assert [type(event) for event in events] == [DocumentReceived, NodeCompleted]
    assert isinstance(events[1], NodeCompleted)
    assert events[1].node is Node.RECEIVE


def test_receive_cannot_fail() -> None:
    owner = builders.user()
    with pytest.raises(ValidationError):
        Document.receive(
            uploaded_by=owner.id,
            space_id=builders.personal_space(owner).id,
            sha256=builders.sha256(),
            original_filename="a.pdf",
            media_type="application/pdf",
            result=FAILED,
            now=NOW,
        )


def test_receive_takes_over_when_it_came_in_but_never_a_moment_ahead() -> None:
    owner = builders.user()

    def received(at: datetime) -> Document:
        return Document.receive(
            uploaded_by=owner.id,
            space_id=builders.personal_space(owner).id,
            sha256=builders.sha256(),
            original_filename="a.pdf",
            media_type="application/pdf",
            result=UNCERTAIN,
            now=NOW,
            received=at,
        )

    earlier = datetime(2023, 1, 2, 8, 30, tzinfo=UTC)
    document = received(earlier)
    assert (document.created_at, document.updated_at) == (earlier, NOW)
    events = document.pull_events()
    assert isinstance(events[0], DocumentReceived)
    assert events[0].occurred_at == NOW
    for wrong in (LATER, datetime(2023, 1, 2, 8, 30)):  # ahead; no time zone
        with pytest.raises(ValidationError):
            received(wrong)


def test_when_it_came_in_is_set_alone_and_confirms_nothing() -> None:
    document = builders.received()
    document.pull_events()
    berlin = timezone(timedelta(hours=2))
    at = datetime(2026, 9, 30, 18, 0, tzinfo=berlin).astimezone(UTC)
    changes = DocumentChanges(created_at=at)
    assert changes.only_receipt
    assert not DocumentChanges(created_at=at, title="Brief").only_receipt
    assert not DocumentChanges().only_receipt
    changed = document.apply_changes(changes, {}, LATER)
    assert changed == ("created_at",)
    assert not confirms(changed, (), (), ())
    assert (document.created_at, document.updated_at) == (at, LATER)
    [event] = document.pull_events()
    assert isinstance(event, DocumentUpdated)
    assert event.fields == ("created_at",)
    assert document.apply_changes(changes, {}, LATER) == ()
    with pytest.raises(ValidationError):
        document.apply_changes(DocumentChanges(created_at=LATER + timedelta(seconds=1)), {}, LATER)
    assert document.created_at == at


def test_metadata_change_records_changed_fields() -> None:
    document = builders.received()
    contact, tag = ContactId(new_id()), TagId(new_id())
    changed = document.apply_changes(
        DocumentChanges(
            title=" Electricity ",
            contact_id=contact,
            tag_ids=frozenset({tag}),
            document_date=date(2026, 9, 30),
        ),
        {},
        LATER,
    )
    assert changed == ("title", "contact_id", "tag_ids", "document_date")
    assert document.title == "Electricity"
    assert document.contact_id == contact
    assert document.tag_ids == {tag}
    assert document.document_date == date(2026, 9, 30)
    assert document.updated_at == LATER
    (event,) = document.pull_events()
    assert isinstance(event, DocumentUpdated)
    assert event.fields == changed


def test_unchanged_metadata_records_nothing() -> None:
    document = builders.received()
    assert document.apply_changes(DocumentChanges(title="scan", contact_id=None), {}, LATER) == ()
    assert document.pull_events() == []
    assert document.updated_at == NOW
    assert DocumentChanges().title is UNSET


def test_tags_set_by_hand_alone_confirm_nothing() -> None:
    """A status tag says nothing about contact and type; any other confirming change does."""
    paid, due, invoice = TagId(new_id()), TagId(new_id()), TagId(new_id())
    manual = {paid, due}
    assert not confirms(("tag_ids",), {invoice}, {invoice, paid}, manual)
    assert not confirms(("tag_ids",), {paid}, {due}, manual)
    assert not confirms(("tag_ids", "title"), {paid}, set(), manual)
    assert confirms(("tag_ids",), {paid}, {paid, invoice}, manual)
    assert confirms(("tag_ids",), {invoice}, {paid}, manual)
    assert confirms(("tag_ids", "contact_id"), set(), {paid}, manual)
    assert confirms(("document_date",), set(), set(), manual)
    assert not confirms(("title",), set(), set(), manual)


def test_field_values_are_validated_and_scoped() -> None:
    invoice, letter = DocumentTypeId(new_id()), DocumentTypeId(new_id())
    total = FieldDefinition.create(
        name="Total", data_type=FieldType.NUMBER, now=NOW, document_type_ids=[invoice]
    )
    note = FieldDefinition.create(name="Note", data_type=FieldType.TEXT, now=NOW)
    definitions = {total.id: total, note.id: note}
    document = builders.received()

    with pytest.raises(ValidationError, match="does not apply"):
        document.apply_changes(DocumentChanges(fields={total.id: 10}), definitions, LATER)
    with pytest.raises(NotFoundError):
        document.apply_changes(
            DocumentChanges(
                fields={FieldDefinition.create(name="x", data_type=FieldType.TEXT, now=NOW).id: "x"}
            ),
            definitions,
            LATER,
        )

    document.apply_changes(
        DocumentChanges(document_type_id=invoice, fields={total.id: 10, note.id: "paid"}),
        definitions,
        LATER,
    )
    assert document.fields == {total.id: Decimal(10), note.id: "paid"}

    with pytest.raises(ValidationError, match="does not accept"):
        document.apply_changes(DocumentChanges(fields={note.id: ""}), definitions, LATER)
    assert document.fields[note.id] == "paid"

    changed = document.apply_changes(DocumentChanges(document_type_id=letter), definitions, LATER)
    assert changed == ("document_type_id", "fields")
    assert document.fields == {note.id: "paid"}

    document.apply_changes(DocumentChanges(fields={note.id: None}), definitions, LATER)
    assert document.fields == {}


def test_field_values_are_checked_without_a_document() -> None:
    invoice = DocumentTypeId(new_id())
    total = FieldDefinition.create(
        name="Total", data_type=FieldType.NUMBER, now=NOW, document_type_ids=[invoice]
    )
    note = FieldDefinition.create(name="Note", data_type=FieldType.TEXT, now=NOW)
    definitions = {total.id: total, note.id: note}
    changes = DocumentChanges(fields={total.id: 10, note.id: None})
    assert checked_fields(changes, definitions, invoice) == {total.id: Decimal(10)}
    with pytest.raises(ValidationError, match="does not apply"):
        checked_fields(changes, definitions, None)
    with pytest.raises(NotFoundError):
        checked_fields(changes, {total.id: total}, invoice)  # removing needs a definition too


def test_failed_validation_changes_nothing() -> None:
    note = FieldDefinition.create(name="Note", data_type=FieldType.TEXT, now=NOW)
    document = builders.received()
    with pytest.raises(ValidationError):
        document.apply_changes(
            DocumentChanges(title="New", fields={note.id: 5}), {note.id: note}, LATER
        )
    assert document.title == "scan"
    assert document.fields == {}
    assert document.pull_events() == []


def test_move_records_filed_and_moved() -> None:
    owner = builders.user()
    document = builders.document(owner, builders.space(owner))
    target = builders.space(owner)
    document.move_to(target.id, LATER, by_person=True, handed_over=True)
    document.move_to(target.id, LATER)
    filed, moved = document.pull_events()
    assert isinstance(filed, DocumentFiled) and isinstance(moved, DocumentMoved)
    assert filed.space_id == moved.space_id == target.id
    assert moved.by_person and moved.handed_over
    assert document.space_id == target.id


def test_a_person_s_move_decides_the_space_and_the_pipeline_s_does_not() -> None:
    owner = builders.user()
    document = builders.document(owner, builders.space(owner))
    assert document.space_confirmed_at is None
    shared, other = builders.space(owner), builders.space(owner)
    document.move_to(shared.id, LATER, by_person=True)
    assert document.space_confirmed_at == LATER
    document.move_to(shared.id, LATER + timedelta(minutes=1), by_person=True)  # kept: decided
    assert document.space_confirmed_at == LATER + timedelta(minutes=1)
    document.move_to(other.id, LATER + timedelta(minutes=2))  # a rule, the judge
    assert document.space_confirmed_at is None
    document.confirm_space(LATER)
    assert document.space_confirmed_at == LATER


def test_a_space_chosen_on_upload_is_decided() -> None:
    owner = builders.user()
    space = builders.space(owner)
    chosen = Document.receive(
        uploaded_by=owner.id,
        space_id=space.id,
        sha256=Sha256.of(b"x"),
        original_filename="x.pdf",
        media_type="application/pdf",
        result=builders.OK,
        now=NOW,
        space_chosen=True,
    )
    assert chosen.space_confirmed_at == NOW
    assert builders.received().space_confirmed_at is None


def test_delete_records_deleted() -> None:
    document = builders.received()
    document.delete(LATER)
    (event,) = document.pull_events()
    assert isinstance(event, DocumentDeleted)
    assert event.occurred_at == LATER


def test_ok_result_constant_is_ok() -> None:
    assert OK.reason is None
