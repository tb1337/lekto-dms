"""Persons: their identifiers with check digits, their profiles, and finding them in a text."""

from datetime import date

import pytest

from lekto.core.domain.errors import ConflictError, ValidationError
from lekto.core.domain.facts import Strength, facts_in
from lekto.core.domain.identifiers import (
    Confirmed,
    Identifier,
    IdentifierKind,
    IdentifierSource,
    health_insurance_number_valid,
    identifiers_in,
    mine_identifiers,
    normalise_identifier,
    of_person,
    social_security_number_valid,
    tax_id_valid,
)
from lekto.core.domain.ids import ContactId, TagId, UserId, new_id
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
    # An insurer's "Versicherungsnummer" is a policy number since #145.
    assert identifiers_in("Versicherungsnummer: 4711-0815") == {
        (IdentifierKind.POLICY_NUMBER, "47110815")
    }


def test_a_persons_numbers_are_never_learned() -> None:
    contact = ContactId(new_id())
    document = Confirmed(contact, None, frozenset({(TAX, TAX_ID), (IdentifierKind.IBAN, IBAN)}))
    learned = mine_identifiers([document, document])
    assert [item.key for item in learned[contact]] == [(IdentifierKind.IBAN, IBAN)]
    assert mine_identifiers([document] * 2, taken=[(IdentifierKind.IBAN, IBAN)]) == {}


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


def test_a_contact_names_a_user_only_by_a_customer_or_personnel_number() -> None:
    user = UserId(new_id())
    contact = Contact.create(name="Insurer", now=builders.NOW)
    contact.set_identifiers([Identifier.parse(CUSTOMER, "K-1001", user_id=user)])
    assert contact.identifiers[0].user_id == user
    with pytest.raises(ValidationError, match="names the user"):
        contact.set_identifiers([Identifier.parse(IdentifierKind.IBAN, IBAN, user_id=user)])
    with pytest.raises(ValidationError, match="kind"):
        contact.set_identifiers([Identifier.parse(TAX, TAX_ID)])
    # Training finds whose a number is; a rejected one names nobody.
    contact.set_learned([Identifier(CUSTOMER, "K2", IdentifierSource.LEARNED, user_id=user)])
    assert contact.identifiers[1].user_id == user
    with pytest.raises(ValidationError, match="names the user"):
        Contact(
            id=contact.id,
            name="X",
            identifiers=[Identifier(CUSTOMER, "K3", IdentifierSource.REJECTED, user_id=user)],
            created_at=builders.NOW,
        )


def test_a_user_keeps_their_numbers_at_a_contact() -> None:
    """Issue #82: what names a user they enter, take over or decline themselves; the rest of
    the contact stays; a number entered for someone else, or for nobody, is taken."""
    anna, bob = UserId(new_id()), UserId(new_id())
    topic = TagId(new_id())
    insurer = Contact.create(
        name="Insurer",
        now=builders.NOW,
        topic_ids=[topic],
        identifiers=[
            Identifier.parse(IdentifierKind.IBAN, IBAN),
            Identifier.parse(CUSTOMER, "K-1001", user_id=anna),
            Identifier.parse(CUSTOMER, "K-9009", user_id=bob),
        ],
    )
    learned = [
        Identifier(CUSTOMER, "K2002", IdentifierSource.LEARNED, user_id=anna),
        Identifier(CUSTOMER, "K3003", IdentifierSource.LEARNED, user_id=anna),
    ]
    insurer.set_learned(learned)
    insurer.set_numbers_of(
        anna,
        [Identifier.parse(CUSTOMER, "K 2002", topic_id=topic), Identifier.parse(CUSTOMER, "K4004")],
        declined=[(CUSTOMER, "K3003")],
    )
    assert [(item.value, item.source, item.user_id) for item in insurer.identifiers] == [
        (IBAN, IdentifierSource.MANUAL, None),
        ("K2002", IdentifierSource.MANUAL, anna),  # taken over
        ("K4004", IdentifierSource.MANUAL, anna),
        ("K9009", IdentifierSource.MANUAL, bob),  # not hers: stays
        ("K3003", IdentifierSource.REJECTED, None),  # declined; K1001 she took away
    ]
    assert insurer.identifiers[1].topic_id == topic
    for taken in ("K9009", IBAN):
        kind = IdentifierKind.IBAN if taken == IBAN else CUSTOMER
        with pytest.raises(ConflictError, match="already taken"):
            insurer.set_numbers_of(anna, [Identifier.parse(kind, taken)])
    with pytest.raises(ValidationError, match="names the user"):
        insurer.set_numbers_of(anna, [Identifier.parse(IdentifierKind.VAT_ID, "DE123456789")])
    with pytest.raises(ValidationError):
        insurer.set_numbers_of(
            anna, [Identifier.parse(CUSTOMER, "K5005", topic_id=TagId(new_id()))]
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


@pytest.mark.parametrize("written", ["15.06.1980", "15.06.80", "15.6.80"])
def test_a_birth_date_is_compared_in_any_form(written: str) -> None:
    # Two digits match the known birth date by day, month and year without its century: no
    # guess of the century (Tobi, 22.10.2026).
    found = facts_in(f"geb. {written}", [], persons=[_anna()])
    assert [(p.strength, p.evidence) for p in found.persons] == [(Strength.MEDIUM, ("birth_date",))]


def test_another_birth_date_names_no_one() -> None:
    assert facts_in("geb. 15.06.81", [], persons=[_anna()]).persons == ()


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


def test_a_pension_funds_insurance_number_is_the_social_security_number() -> None:
    """The DRV writes "Versicherungsnummer" before the social security number, in groups."""
    grouped = f"{SV[:2]} {SV[2:8]} {SV[8]} {SV[9:]}"
    assert identifiers_in(f"Versicherungsnummer: {grouped}") == {(SOCIAL, SV)}


def test_the_health_insurance_number_after_its_long_label() -> None:
    assert identifiers_in(f"Krankenversicherungsnummer: {KVNR}") == {(HEALTH, KVNR)}


def test_a_tax_id_after_its_label_with_the_short_form() -> None:
    assert identifiers_in(f"Identifikationsnummer (IdNr.): {TAX_ID}") == {(TAX, TAX_ID)}


def test_a_customer_number_that_stands_in_a_persons_number_is_theirs() -> None:
    personal = [(SOCIAL, SV)]
    assert of_person((CUSTOMER, SV[:8]), personal)
    assert of_person((CUSTOMER, SV), personal)
    assert of_person((CUSTOMER, IBAN), [(IdentifierKind.IBAN, IBAN)])  # an "account number"
    assert not of_person((CUSTOMER, "4711"), personal)  # too short to tell
    assert not of_person((CUSTOMER, IBAN[4:12]), [(IdentifierKind.IBAN, IBAN)])
    contact = ContactId(new_id())
    document = Confirmed(contact, None, frozenset({(CUSTOMER, SV[:8]), (CUSTOMER, "K4711")}))
    learned = mine_identifiers([document] * 2, personal=personal)
    assert [item.key for item in learned[contact]] == [(CUSTOMER, "K4711")]


def test_a_deactivated_or_unlisted_user_is_never_named() -> None:
    """Only the persons given are found, also by a contact's number that names a user."""
    anna = _anna()
    contact = Contact.create(name="Insurer", now=builders.NOW)
    contact.set_identifiers([Identifier.parse(CUSTOMER, "K-4711", user_id=anna.user_id)])
    assert facts_in("Kundennummer K-4711", [contact], persons=[]).persons == ()


def test_a_person_in_public_form_is_found_by_their_display_name_alone() -> None:
    anna = _anna()
    contact = Contact.create(name="Insurer", now=builders.NOW)
    contact.set_identifiers([Identifier.parse(CUSTOMER, "K-4711", user_id=anna.user_id)])
    text = f"Anna Sample, 15.06.1980, Steuer-ID {TAX_ID}, Kundennummer K-4711"
    assert facts_in(text, [contact], persons=[anna.public()]).persons == ()
    named = facts_in(f"An Anna Example. {text}", [contact], persons=[anna.public()])
    assert [(p.strength, p.evidence) for p in named.persons] == [(Strength.WEAK, ("name",))]
    # Her IBAN shows as unknown: that it is hers is private.
    iban = facts_in("IBAN DE89 3704 0044 0532 0130 00", [], persons=[anna.public()])
    assert [item.key for item in iban.identifiers] == [(IdentifierKind.IBAN, IBAN)]


def test_a_profile_declines_only_what_is_not_its_own() -> None:
    """An IBAN declined once and entered later is the person's: no longer declined."""
    iban = Identifier(IdentifierKind.IBAN, "DE89370400440532013000")
    other = Identifier(IdentifierKind.IBAN, "DE02120300000000202051")
    profile = Profile(id=UserId(new_id()), identifiers=[iban], declined=[iban, other, other])
    assert profile.declined == [other]
    assert other.key not in {item.key for item in profile.evidence()}
