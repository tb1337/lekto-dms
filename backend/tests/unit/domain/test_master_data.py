from datetime import UTC, datetime

import pytest

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.master_data import (
    MAX_ALIASES,
    MAX_DESCRIPTION,
    MAX_GROUPS,
    Assignment,
    Contact,
    DocumentType,
    Tag,
    TagScope,
)

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("kind", [Contact, DocumentType, Tag])
def test_master_data_has_a_name(kind: type[Contact | DocumentType | Tag]) -> None:
    item = kind.create(name=" Stadtwerke ", now=NOW)
    assert item.name == "Stadtwerke"
    item.rename("Stadtwerke Köln")
    assert item.name == "Stadtwerke Köln"
    with pytest.raises(ValidationError):
        item.rename(" ")
    with pytest.raises(ValidationError):
        kind.create(name="", now=NOW)


def test_contact_aliases() -> None:
    contact = Contact.create(name="Nord", now=NOW, aliases=[" Nord AG ", "nord ag", "Nord\n\x00KV"])
    assert contact.aliases == ["Nord AG", "Nord KV"]
    assert contact.is_named("nord kv") and not contact.is_named("Nord Leben")
    with pytest.raises(ValidationError):
        contact.set_aliases(["Nord"])
    with pytest.raises(ValidationError):
        contact.set_aliases([" "])
    with pytest.raises(ValidationError):
        contact.set_aliases(f"Alias {number}" for number in range(MAX_ALIASES + 1))
    contact.rename("Nord AG")  # an alias that becomes the name is no longer an alias
    assert contact.aliases == ["Nord KV"]


def test_document_type_description() -> None:
    kind = DocumentType.create(name="Pay slip", now=NOW, description="  ")
    assert kind.description is None
    kind.describe(" Entgeltbescheinigung ")
    assert kind.description == "Entgeltbescheinigung"
    with pytest.raises(ValidationError):
        kind.describe("x" * (MAX_DESCRIPTION + 1))


def test_a_tag_has_a_fixed_scope_and_defaults_by_scope() -> None:
    document = Tag.create(name="Paid", now=NOW)
    assert (document.scope, document.assignment, document.shown) == (
        TagScope.DOCUMENT,
        Assignment.AUTO,
        True,
    )
    assert document.is_target
    status = Tag.create(name="To pay", now=NOW, assignment=Assignment.MANUAL)
    assert not status.is_target
    group = Tag.create(name="Insurance", now=NOW, scope=TagScope.CONTACT)
    assert (group.assignment, group.shown, group.is_target) == (Assignment.MANUAL, False, False)
    shown = Tag.create(name="Invoice", now=NOW, scope=TagScope.DOCUMENT_TYPE, shown=True)
    assert shown.shown


def test_groups_are_set_by_hand_and_no_tag_is_its_own_parent() -> None:
    with pytest.raises(ValidationError, match="by hand"):
        Tag.create(name="Insurance", now=NOW, scope=TagScope.CONTACT, assignment=Assignment.AUTO)
    group = Tag.create(name="Insurance", now=NOW, scope=TagScope.CONTACT)
    with pytest.raises(ValidationError, match="by hand"):
        group.assign(Assignment.AUTO)
    with pytest.raises(ValidationError, match="own parent"):
        group.move(group.id)


def test_contacts_and_types_are_in_groups() -> None:
    group = Tag.create(name="Insurance", now=NOW, scope=TagScope.CONTACT)
    contact = Contact.create(name="Nord", now=NOW)
    assert contact.group_ids == frozenset()
    contact.set_groups([group.id, group.id])
    assert contact.group_ids == {group.id}
    kind = DocumentType.create(name="Invoice", now=NOW)
    kind.set_groups([group.id])
    assert kind.group_ids == {group.id}
    with pytest.raises(ValidationError, match="groups"):
        kind.set_groups(Tag.create(name=str(n), now=NOW).id for n in range(MAX_GROUPS + 1))
