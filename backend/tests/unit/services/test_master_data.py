import pytest

from papiq.core.domain.documents import DocumentChanges
from papiq.core.domain.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from papiq.core.domain.fields import FieldType
from papiq.core.domain.identifiers import Identifier, IdentifierKind, IdentifierSource
from papiq.core.domain.ids import ContactId, DocumentTypeId, new_id
from papiq.core.domain.users import Role
from papiq.core.services.master_data import learn_alias, replace_learned_identifiers
from tests.builders import incoming
from tests.unit.services.conftest import World

MANUAL, LEARNED = IdentifierSource.MANUAL, IdentifierSource.LEARNED
REJECTED = IdentifierSource.REJECTED


async def test_admin_maintains_master_data(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    service = world.master_data
    contact = await service.create_contact(admin.id, "Stadtwerke")
    invoice = await service.create_document_type(admin.id, "Invoice")
    tag = await service.create_tag(admin.id, "Tax")
    total = await service.create_field(
        admin.id, "Total", FieldType.AMOUNT, document_type_ids=[invoice.id]
    )
    period = await service.create_field(
        admin.id, "Period", FieldType.CHOICE, choices=["monthly", "yearly"]
    )
    assert (await service.rename_contact(admin.id, contact.id, "SWK")).name == "SWK"
    assert (await service.rename_document_type(admin.id, invoice.id, "Bill")).name == "Bill"
    assert (await service.rename_tag(admin.id, tag.id, "Taxes")).name == "Taxes"
    assert (await service.rename_field(admin.id, total.id, "Sum")).name == "Sum"
    async with world.uow() as uow:
        assert (await uow.contacts.get(contact.id)).name == "SWK"
        assert (await uow.fields.get(total.id)).document_type_ids == frozenset({invoice.id})
        assert (await uow.fields.get(period.id)).is_global


async def test_no_two_fields_share_a_key_in_templates(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    service = world.master_data
    gross = await service.create_field(admin.id, "LA_Brutto", FieldType.AMOUNT)
    assert gross.key == "la_brutto"
    with pytest.raises(ConflictError, match=r"field\.la_brutto"):
        await service.create_field(admin.id, "LA Brutto", FieldType.AMOUNT)
    net = await service.create_field(admin.id, "LA Netto", FieldType.AMOUNT)
    with pytest.raises(ConflictError, match=r"field\.la_brutto"):
        await service.change_field(admin.id, net.id, name="la-brutto")
    # The field keeps its own key when only the case of its name changes.
    assert (await service.change_field(admin.id, gross.id, name="LA_BRUTTO")).key == "la_brutto"


async def test_only_admins_change_master_data(world: World) -> None:
    admin, user = await world.user(role=Role.ADMIN), await world.user()
    service = world.master_data
    contact = await service.create_contact(admin.id, "Bank")
    with pytest.raises(PermissionDeniedError):
        await service.create_contact(user.id, "Other bank")
    with pytest.raises(PermissionDeniedError):
        await service.rename_contact(user.id, contact.id, "Mine")
    with pytest.raises(PermissionDeniedError):
        await service.create_document_type(user.id, "Letter")
    with pytest.raises(PermissionDeniedError):
        await service.create_tag(user.id, "x")
    with pytest.raises(PermissionDeniedError):
        await service.create_field(user.id, "x", FieldType.TEXT)


async def test_contact_aliases_and_type_descriptions(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    service = world.master_data
    example = await service.create_contact(admin.id, "Nord Versicherungsgruppe", ["Nord AG"])
    other = await service.create_contact(admin.id, "Muster")
    changed = await service.change_contact(
        admin.id,
        example.id,
        aliases=["Nord Krankenversicherung AG", "nord krankenversicherung ag"],
    )
    assert changed.aliases == ["Nord Krankenversicherung AG"]
    assert (await service.rename_contact(admin.id, example.id, "Nord")).aliases == changed.aliases
    # A name or an alias of one contact is never a name or an alias of another.
    for change in (
        service.change_contact(admin.id, other.id, aliases=["Nord"]),
        service.change_contact(admin.id, other.id, name="nord krankenversicherung ag"),
        service.create_contact(admin.id, "Other", ["Nord Krankenversicherung AG"]),
        # As classification compares names: legal forms and punctuation do not count.
        service.create_contact(admin.id, "Other", ["Nord Krankenversicherung"]),
        service.create_contact(admin.id, "Nord Krankenversicherung GmbH"),
    ):
        with pytest.raises(ConflictError):
            await change
    pay = await service.create_document_type(admin.id, "Pay slip", " Entgeltbescheinigung ")
    assert pay.description == "Entgeltbescheinigung"
    kept = await service.change_document_type(admin.id, pay.id, name="Payslip")
    assert kept.description == "Entgeltbescheinigung"
    assert (
        await service.change_document_type(admin.id, pay.id, description="")
    ).description is None


IBAN = Identifier.parse(IdentifierKind.IBAN, "DE89 3704 0044 0532 0130 00")
DOMAIN = Identifier.parse(IdentifierKind.EMAIL_DOMAIN, "stadtwerke.example")


async def test_contact_identifiers(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    service = world.master_data
    utility = await service.create_contact(admin.id, "Stadtwerke", identifiers=[IBAN])
    other = await service.create_contact(admin.id, "Bank")
    assert utility.identifiers == [IBAN]
    # A value another contact entered by hand is a conflict.
    with pytest.raises(ConflictError):
        await service.change_contact(admin.id, other.id, identifiers=[IBAN])
    with pytest.raises(ConflictError):
        await service.create_contact(admin.id, "Other", identifiers=[IBAN])
    # Rejected and entered ones are replaced on their own.
    changed = await service.change_contact(admin.id, utility.id, rejected_identifiers=[DOMAIN])
    assert [item.source for item in changed.identifiers] == [MANUAL, REJECTED]
    changed = await service.change_contact(admin.id, utility.id, identifiers=[])
    assert changed.identifiers == [Identifier(DOMAIN.kind, DOMAIN.value, REJECTED)]
    # Entered by hand elsewhere, a rejected (or learned) value moves.
    moved = await service.change_contact(admin.id, other.id, identifiers=[DOMAIN])
    assert moved.identifiers == [DOMAIN]
    async with world.uow() as uow:
        assert (await uow.contacts.get(utility.id)).identifiers == []


async def test_training_replaces_the_learned_identifiers(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    service = world.master_data
    utility = await service.create_contact(admin.id, "Stadtwerke")
    bank = await service.create_contact(admin.id, "Bank", identifiers=[IBAN])
    learned = [Identifier(DOMAIN.kind, DOMAIN.value, LEARNED)]
    taken = [Identifier(IBAN.kind, IBAN.value, LEARNED)]
    async with world.uow() as uow:
        assert await replace_learned_identifiers(uow, {utility.id: [*learned, *taken]}) == 1
        await uow.commit()
    async with world.uow() as uow:
        assert (await uow.contacts.get(utility.id)).identifiers == learned
        assert (await uow.contacts.get(bank.id)).identifiers == [IBAN]
        # The value moves to another contact in one go.
        assert await replace_learned_identifiers(uow, {bank.id: learned}) == 1
        await uow.commit()
    async with world.uow() as uow:
        assert (await uow.contacts.get(utility.id)).identifiers == []
        assert (await uow.contacts.get(bank.id)).identifiers == [IBAN, *learned]


async def test_required_fields_and_title_patterns(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    service = world.master_data
    payslip = await service.create_document_type(
        admin.id, "Lohnnachweis", title_pattern="Lohn {document_date:YYYY-MM}"
    )
    other = await service.create_document_type(admin.id, "Brief")
    period = await service.create_field(
        admin.id,
        "Zeitraum",
        FieldType.TEXT,
        document_type_ids=[payslip.id, other.id],
        required_document_type_ids=[payslip.id],
    )
    assert period.is_required_for(payslip.id) and not period.is_required_for(other.id)
    note = await service.create_field(admin.id, "Notiz", FieldType.TEXT, required=True)
    assert note.is_required_for(None)
    # A pattern names fields of the type only.
    changed = await service.change_document_type(
        admin.id, payslip.id, title_pattern="Lohn {field:Zeitraum} {field:Notiz}"
    )
    assert changed.title_pattern == "Lohn {field:Zeitraum} {field:Notiz}"
    with pytest.raises(ValidationError):
        await service.change_document_type(admin.id, payslip.id, title_pattern="{field:Betrag}")
    with pytest.raises(ValidationError):
        await service.create_document_type(admin.id, "Neu", title_pattern="{field:Zeitraum}")
    # Renamed, the field is renamed in the patterns; narrowed, it stays required for the rest.
    await service.rename_field(admin.id, period.id, "Abrechnungszeitraum")
    async with world.uow() as uow:
        assert (await uow.document_types.get(payslip.id)).title_pattern == (
            "Lohn {field:Abrechnungszeitraum} {field:Notiz}"
        )
    narrowed = await service.change_field(admin.id, period.id, document_type_ids=[payslip.id])
    assert narrowed.required_types == frozenset({payslip.id})
    optional = await service.change_field(admin.id, period.id, required_document_type_ids=[])
    assert not optional.is_required_for(payslip.id)
    with pytest.raises(ValidationError):
        await service.change_field(admin.id, period.id, required=True)


async def test_learn_alias(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    service = world.master_data
    example = await service.create_contact(admin.id, "Nord Versicherungsgruppe")
    other = await service.create_contact(admin.id, "Muster", ["Nord Kranken"])
    async with world.uow() as uow:
        learned = await learn_alias(uow, example.id, "Nord Krankenversicherung AG")
        assert learned is not None and learned.aliases == ["Nord Krankenversicherung AG"]
        assert await learn_alias(uow, example.id, "nord versicherungsgruppe") is None  # its name
        assert await learn_alias(uow, example.id, "MUSTER") is None  # another contact's name
        assert await learn_alias(uow, example.id, "Muster SE") is None  # the same, compared
        assert await learn_alias(uow, example.id, "Max Mustermann") is None  # unrelated
        assert await learn_alias(uow, example.id, "GmbH") is None  # nothing to compare
        assert await learn_alias(uow, example.id, "Nord\nKranken") is not None  # moves
        await uow.commit()
    async with world.uow() as uow:
        assert (await uow.contacts.get(example.id)).aliases == [
            "Nord Krankenversicherung AG",
            "Nord Kranken",
        ]
        assert (await uow.contacts.get(other.id)).aliases == []


async def test_names_are_unique_per_kind(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    service = world.master_data
    await service.create_tag(admin.id, "Insurance")
    await service.create_contact(admin.id, "Insurance")
    with pytest.raises(ConflictError):
        await service.create_tag(admin.id, "insurance")
    other = await service.create_tag(admin.id, "Car")
    with pytest.raises(ConflictError):
        await service.rename_tag(admin.id, other.id, "INSURANCE")
    assert (await service.rename_tag(admin.id, other.id, "CAR")).name == "CAR"


async def test_field_needs_existing_document_types(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    with pytest.raises(NotFoundError):
        await world.master_data.create_field(
            admin.id, "Total", FieldType.NUMBER, document_type_ids=[DocumentTypeId(new_id())]
        )


async def test_everyone_reads_master_data_sorted(world: World) -> None:
    admin, user = await world.user(role=Role.ADMIN), await world.user()
    for name in ("b", "A", "c"):
        await world.master_data.create_tag(admin.id, name)
    tags = await world.master_data.list_tags(user.id)
    assert [tag.name for tag in tags] == ["A", "b", "c"]
    assert (await world.master_data.get_tag(user.id, tags[0].id)).name == "A"
    contact = await world.master_data.create_contact(admin.id, "ACME")
    assert await world.master_data.list_contacts(user.id) == [contact]
    invoice = await world.master_data.create_document_type(admin.id, "Invoice")
    assert await world.master_data.get_document_type(user.id, invoice.id) == invoice
    note = await world.master_data.create_field(admin.id, "Note", FieldType.TEXT)
    assert await world.master_data.list_fields(user.id) == [note]
    with pytest.raises(NotFoundError):
        await world.master_data.get_contact(user.id, ContactId(new_id()))


async def test_only_unused_master_data_is_deleted_by_admins(world: World) -> None:
    admin, owner = await world.user(role=Role.ADMIN), await world.user()
    contact = await world.master_data.create_contact(admin.id, "ACME")
    tag = await world.master_data.create_tag(admin.id, "tax")
    invoice = await world.master_data.create_document_type(admin.id, "Invoice")
    bound = await world.master_data.create_field(
        admin.id, "Amount", FieldType.AMOUNT, document_type_ids=[invoice.id]
    )
    unused = await world.master_data.create_tag(admin.id, "unused")
    document = await world.pipeline().receive(owner.id, incoming(b"%PDF-1.7 x"), filename="x.pdf")
    await world.drain()
    await world.documents.update_metadata(
        owner.id,
        document.id,
        DocumentChanges(contact_id=contact.id, tag_ids=frozenset({tag.id})),
    )
    with pytest.raises(PermissionDeniedError):
        await world.master_data.delete_tag(owner.id, unused.id)
    for delete in (
        world.master_data.delete_contact(admin.id, contact.id),
        world.master_data.delete_tag(admin.id, tag.id),
        world.master_data.delete_document_type(admin.id, invoice.id),  # a field uses it
    ):
        with pytest.raises(ConflictError):
            await delete
    await world.master_data.delete_tag(admin.id, unused.id)
    await world.master_data.delete_field(admin.id, bound.id)
    await world.master_data.delete_document_type(admin.id, invoice.id)
    assert [t.name for t in await world.master_data.list_tags(admin.id)] == ["tax"]
    with pytest.raises(NotFoundError):
        await world.master_data.delete_tag(admin.id, unused.id)


async def test_field_definitions_change_without_breaking_values(world: World) -> None:
    admin, owner = await world.user(role=Role.ADMIN), await world.user()
    invoice = await world.master_data.create_document_type(admin.id, "Invoice")
    letter = await world.master_data.create_document_type(admin.id, "Letter")
    kind = await world.master_data.create_field(
        admin.id, "Kind", FieldType.CHOICE, choices=["a", "b"]
    )
    document = await world.pipeline().receive(owner.id, incoming(b"%PDF-1.7 x"), filename="x.pdf")
    await world.drain()
    await world.documents.update_metadata(
        owner.id,
        document.id,
        DocumentChanges(document_type_id=invoice.id, fields={kind.id: "a"}),
    )
    change = world.master_data.change_field

    with pytest.raises(PermissionDeniedError):
        await change(owner.id, kind.id, name="Sort")
    changed = await change(admin.id, kind.id, name="Sort", choices=["a", "b", "c"])
    assert changed.name == "Sort" and changed.choices == ("a", "b", "c")
    await change(admin.id, kind.id, choices=["c", "a"])  # b is unused
    with pytest.raises(ConflictError):
        await change(admin.id, kind.id, choices=["c"])  # a is in use
    with pytest.raises(ConflictError):
        await change(admin.id, kind.id, document_type_ids=[letter.id])  # narrower
    await change(admin.id, kind.id, document_type_ids=[invoice.id, letter.id])
    await change(admin.id, kind.id, document_type_ids=[invoice.id])  # values all inside
    await change(admin.id, kind.id, document_type_ids=None)
    with pytest.raises(NotFoundError):
        await change(admin.id, kind.id, document_type_ids=[DocumentTypeId(new_id())])
    stored = await world.master_data.get_field(owner.id, kind.id)
    assert stored.choices == ("c", "a") and stored.document_type_ids is None
    document_now = await world.documents.get(owner.id, document.id)
    assert document_now.fields == {kind.id: "a"}
