"""Persons: their identifiers with check digits, their profiles, and finding them in a text."""

from datetime import date

import pytest

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.facts import Strength, facts_in
from lekto.core.domain.identifiers import (
    Identifier,
    IdentifierKind,
    IdentifierSource,
    health_insurance_number_valid,
    identifiers_in,
    mine_identifiers,
    normalise_identifier,
    social_security_number_valid,
    tax_id_valid,
)
from lekto.core.domain.ids import ContactId, UserId, new_id
from lekto.core.domain.master_data import Contact
from lekto.core.domain.profiles import Person, Profile
from lekto.core.domain.users import Role, User
from tests import builders
from tests.person_numbers import health_insurance_number, social_security_number, tax_id

TAX_ID = tax_id()
SV = social_security_number()
KVNR = health_insurance_number()
IBAN = "DE89370400440532013000"
TAX = IdentifierKind.TAX_ID
SOCIAL = IdentifierKind.SOCIAL_SECURITY_NUMBER
HEALTH = IdentifierKind.HEALTH_INSURANCE_NUMBER
ADDRESS = IdentifierKind.EMAIL_ADDRESS
CUSTOMER = IdentifierKind.CUSTOMER_NUMBER


def test_check_digits() -> None:
    assert tax_id_valid(TAX_ID)
    assert not tax_id_valid(TAX_ID[:-1] + str((int(TAX_ID[-1]) + 1) % 10))
    assert not tax_id_valid("0" + TAX_ID[1:])  # never starts with 0
    assert not tax_id_valid(tax_id("1234567890"))  # no digit twice
    assert not tax_id_valid(tax_id("1122345678"))  # two digits twice
    assert tax_id_valid(tax_id("1213456789"))
    assert not tax_id_valid(tax_id("1112345678"))  # three in a row
    assert social_security_number_valid(SV)
    assert not social_security_number_valid(SV[:-1] + str((int(SV[-1]) + 1) % 10))
    assert not social_security_number_valid(social_security_number("12151380"))  # month 13
    assert health_insurance_number_valid(KVNR)
    assert not health_insurance_number_valid(KVNR[:-1] + str((int(KVNR[-1]) + 1) % 10))


@pytest.mark.parametrize(
    ("kind", "raw", "value"),
    [
        (TAX, f"{TAX_ID[:2]} {TAX_ID[2:5]} {TAX_ID[5:8]} {TAX_ID[8:]}", TAX_ID),
        (SOCIAL, f"{SV[:2]} {SV[2:8]} {SV[8].lower()} {SV[9:]}", SV),
        (HEALTH, KVNR.lower(), KVNR),
        (ADDRESS, "mailto:Anna.Example@Mail.Example", "anna.example@mail.example"),
    ],
)
def test_normalised(kind: IdentifierKind, raw: str, value: str) -> None:
    assert normalise_identifier(kind, raw) == value


@pytest.mark.parametrize(
    ("kind", "raw"),
    [(TAX, "12345678901"), (SOCIAL, "12150680M120"), (HEALTH, "A123456789"), (ADDRESS, "anna")],
)
def test_invalid(kind: IdentifierKind, raw: str) -> None:
    with pytest.raises(ValidationError):
        normalise_identifier(kind, raw)


def test_persons_numbers_in_a_text() -> None:
    grouped = f"{TAX_ID[:2]} {TAX_ID[2:5]} {TAX_ID[5:8]} {TAX_ID[8:]}"
    text = (
        f"Identifikationsnummer: {TAX_ID}\nSteuer-ID {grouped}\n"
        f"Sozialversicherungsnummer {SV[:2]} {SV[2:8]} {SV[8]} {SV[9:]}\n"
        f"Versichertennummer: {KVNR}\nKontakt: anna@mail.example\n"
        f"Versicherungsnummer: {SV}\nTelefon 0221 123 456 789"
    )
    found = identifiers_in(text)
    assert {key for key in found if key[0] in {TAX, SOCIAL, HEALTH, ADDRESS}} == {
        (TAX, TAX_ID),
        (SOCIAL, SV),
        (HEALTH, KVNR),
        (ADDRESS, "anna@mail.example"),
    }
    # The pension fund's "Versicherungsnummer" before the number is not a customer number.
    assert (CUSTOMER, SV) not in found
    assert not any(kind is CUSTOMER for kind, _ in found)


def test_a_tax_id_needs_its_label_or_its_groups() -> None:
    assert identifiers_in(f"Rechnung {TAX_ID}") == set()
    assert identifiers_in(f"Rechnung {TAX_ID[:2]} {TAX_ID[2:5]} {TAX_ID[5:8]} {TAX_ID[8:]}") == {
        (TAX, TAX_ID)
    }


def test_the_social_security_label_is_no_customer_label() -> None:
    assert identifiers_in("Rentenversicherungsnummer: 4711 0815") == set()
    assert identifiers_in("Versicherungsnummer: 4711-0815") == {(CUSTOMER, "47110815")}


def test_a_persons_numbers_are_never_learned() -> None:
    contact = ContactId(new_id())
    found = [(TAX, TAX_ID), (IdentifierKind.IBAN, IBAN)]
    learned = mine_identifiers([(contact, None, found), (contact, None, found)])
    assert [item.key for item in learned[contact]] == [(IdentifierKind.IBAN, IBAN)]
    assert mine_identifiers([(contact, None, found)] * 2, taken=[(IdentifierKind.IBAN, IBAN)]) == {}


def test_a_profile() -> None:
    user = UserId(new_id())
    profile = Profile(
        id=user,
        aliases=[" Anna Sample "],
        email="Anna@Mail.Example",
        identifiers=[Identifier.parse(TAX, TAX_ID), Identifier.parse(TAX, TAX_ID)],
    )
    assert profile.aliases == ["Anna Sample"]
    assert profile.email == "anna@mail.example"
    assert [item.key for item in profile.evidence()] == [
        (TAX, TAX_ID),
        (ADDRESS, "anna@mail.example"),
    ]
    with pytest.raises(ValidationError, match="twice"):
        Profile(id=user, aliases=["Anna", "anna"])
    with pytest.raises(ValidationError, match="kind"):
        Profile(id=user, identifiers=[Identifier(CUSTOMER, "4711")])
    with pytest.raises(ValidationError, match="1900"):
        Profile(id=user, birth_date=date(1899, 12, 31))


def test_a_contact_names_a_user_only_by_a_number_entered_by_hand() -> None:
    user = UserId(new_id())
    contact = Contact.create(name="Insurer", now=builders.NOW)
    contact.set_identifiers([Identifier.parse(CUSTOMER, "K-1001", user_id=user)])
    assert contact.identifiers[0].user_id == user
    with pytest.raises(ValidationError, match="names the user"):
        contact.set_identifiers([Identifier.parse(IdentifierKind.IBAN, IBAN, user_id=user)])
    with pytest.raises(ValidationError, match="kind"):
        contact.set_identifiers([Identifier.parse(TAX, TAX_ID)])
    with pytest.raises(ValidationError, match="names the user"):
        Contact(
            id=contact.id,
            name="X",
            identifiers=[Identifier(CUSTOMER, "K2", IdentifierSource.LEARNED, user_id=user)],
            created_at=builders.NOW,
        )


def _anna() -> Person:
    user = User.create(username="anna", role=Role.USER, now=builders.NOW)
    user.display_name = "Anna Example"
    profile = Profile(
        id=user.id,
        aliases=["Anna Sample"],
        birth_date=date(1980, 6, 15),
        identifiers=[Identifier.parse(TAX, TAX_ID), Identifier.parse(IdentifierKind.IBAN, IBAN)],
    )
    return Person.of(user, profile)


def test_persons_by_their_evidence() -> None:
    anna = _anna()
    weak = facts_in("An Frau Anna Sample", [], persons=[anna])
    assert [(p.strength, p.evidence) for p in weak.persons] == [(Strength.WEAK, ("alias",))]
    medium = facts_in("Anna Example, geboren am 15.06.1980", [], persons=[anna])
    assert [(p.strength, p.evidence) for p in medium.persons] == [
        (Strength.MEDIUM, ("birth_date", "name"))
    ]
    hard = facts_in(f"Steuer-ID {TAX_ID}, IBAN DE89 3704 0044 0532 0130 00", [], persons=[anna])
    assert [(p.strength, set(p.evidence)) for p in hard.persons] == [
        (Strength.HARD, {"tax_id", "iban"})
    ]
    # Their own IBAN is no unknown identifier; their numbers are no contact's.
    assert hard.identifiers == ()
    assert facts_in("Niemand", [], persons=[anna]).persons == ()


def test_a_contacts_number_names_its_user() -> None:
    anna = _anna()
    contact = Contact.create(name="Insurer", now=builders.NOW)
    contact.set_identifiers([Identifier.parse(CUSTOMER, "K-4711", user_id=anna.user_id)])
    facts = facts_in("Kundennummer K-4711", [contact], persons=[anna], places=True)
    (person,) = facts.persons
    assert (person.user_id, person.strength, person.evidence) == (
        anna.user_id,
        Strength.HARD,
        ("customer_number",),
    )
    assert person.spans
    assert [item.contact_id for item in facts.identifiers] == [contact.id]
