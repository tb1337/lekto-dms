from datetime import UTC, datetime

import pytest

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers import (
    CONTACT_KINDS,
    NAMING_KINDS,
    PERSON_KINDS,
    TYPES,
    Candidate,
    Confirmed,
    Identifier,
    IdentifierKind,
    IdentifierSource,
    KeyIndex,
    catalog,
    identifiers_from,
    identifiers_in,
    matches,
    mine_identifiers,
    normalise_identifier,
    seen_by,
)
from lekto.core.domain.ids import ContactId, SpaceId, TagId, UserId, new_id
from lekto.core.domain.master_data import Contact
from tests.person_numbers import social_security_number

NOW = datetime(2026, 10, 13, tzinfo=UTC)
IBAN = IdentifierKind.IBAN
VAT = IdentifierKind.VAT_ID
CUSTOMER = IdentifierKind.CUSTOMER_NUMBER
PERSONNEL = IdentifierKind.PERSONNEL_NUMBER
DOMAIN = IdentifierKind.EMAIL_DOMAIN
TAX = IdentifierKind.TAX_ID
SOCIAL = IdentifierKind.SOCIAL_SECURITY_NUMBER
HEALTH = IdentifierKind.HEALTH_INSURANCE_NUMBER
ADDRESS = IdentifierKind.EMAIL_ADDRESS
OWN_IBAN = "DE02120300000000202051"
THEIR_IBAN = "DE89370400440532013000"

LETTER = """\
# Stadtwerke Musterstadt GmbH
USt-IdNr.: DE123456789 Steuernummer 12/345/67890
Kundennummer: 4711-0815 · Vertragsnummer 123 456 789
IBAN DE89 3704 0044 0532 0130 00 BIC COBADEFFXXX
privat 12345678, August 2026
Fragen? service@stadtwerke-musterstadt.de oder www.stadtwerke-musterstadt.de
Ihre Adresse: max.nord@gmail.com
| Kd.-Nr. | K-77881 |
"""


@pytest.mark.parametrize(
    ("kind", "raw", "value"),
    [
        (IBAN, "de89 3704 0044 0532 0130 00", THEIR_IBAN),
        (IBAN, "NO93 8601 1117 947", "NO9386011117947"),  # the shortest
        (IBAN, "MT84 MALT 0110 0001 2345 MTLC AST0 01S", "MT84MALT011000012345MTLCAST001S"),
        (VAT, "DE 123 456 789", "DE123456789"),
        (VAT, "ATU12345678", "ATU12345678"),
        (CUSTOMER, "K-778.81/2", "K778812"),
        (PERSONNEL, "00012345", "12345"),  # one number with or without leading zeros
        (PERSONNEL, "12-345", "12345"),
        (PERSONNEL, "0815", "815"),
        (PERSONNEL, "A-4711", "A4711"),
        (DOMAIN, "Service@Stadtwerke.example", "stadtwerke.example"),
        (DOMAIN, "https://www.stadtwerke.example/kontakt", "stadtwerke.example"),
    ],
)
def test_identifiers_are_normalised(kind: IdentifierKind, raw: str, value: str) -> None:
    assert normalise_identifier(kind, raw) == value


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        (IBAN, "DE89 3704 0044 0532 0130 01"),  # check sum
        # The check sum fits, but the length or the country does not.
        (IBAN, "DE54 3704 0044 0532 0130 001"),
        (IBAN, "RF18 5390 0754 7034"),  # a creditor reference (ISO 11649)
        (IBAN, "NR03 1234 5678 9012"),
        (VAT, "DE12345"),
        (CUSTOMER, "Musterkunde"),  # no digit
        (CUSTOMER, "12"),
        (PERSONNEL, "12"),
        (PERSONNEL, "000"),
        (PERSONNEL, "Muster"),
        (DOMAIN, "keine domain"),
        (DOMAIN, "gmail.com"),
    ],
)
def test_what_is_no_identifier(kind: IdentifierKind, raw: str) -> None:
    with pytest.raises(ValidationError):
        normalise_identifier(kind, raw)


def test_identifiers_in_a_letter() -> None:
    assert identifiers_in(LETTER) == {
        (IBAN, THEIR_IBAN),
        (VAT, "DE123456789"),
        (CUSTOMER, "47110815"),
        # Kinds of their own since #145: the contract number, the company's tax number.
        (IdentifierKind.CONTRACT_NUMBER, "123456789"),
        (IdentifierKind.TAX_NUMBER, "1234567890"),
        (CUSTOMER, "K77881"),
        (DOMAIN, "stadtwerke-musterstadt.de"),
        (IdentifierKind.EMAIL_ADDRESS, "service@stadtwerke-musterstadt.de"),
        (IdentifierKind.EMAIL_ADDRESS, "max.nord@gmail.com"),
    }


@pytest.mark.parametrize(
    "text",
    [
        "IBAN DE89 3704 0044 0532 0130 00",
        "IBAN: DE 89 3704 0044 0532 0130 00\nBank Musterstadt",  # the country apart
        "DE89370400440532013000",
    ],
)
def test_an_iban_however_it_is_grouped(text: str) -> None:
    assert identifiers_in(text) == {(IBAN, THEIR_IBAN)}


@pytest.mark.parametrize("text", ["de 12 Seiten 2026 bis 2030", "DE 89 3704 0044 0532 0130 01"])
def test_no_iban_without_its_check_sum(text: str) -> None:
    assert IBAN not in {kind for kind, _ in identifiers_in(text)}


@pytest.mark.parametrize(
    "text",
    [
        "Verwendungszweck RF18 5390 0754 7034",  # a creditor reference
        "Vertrags-NR03 1234 5678 9012",
        "Konto DE54 3704 0044 0532 0130 001",  # one place too many
    ],
)
def test_no_iban_without_its_country_and_length(text: str) -> None:
    assert IBAN not in {kind for kind, _ in identifiers_in(text)}


def test_an_iban_ends_where_its_country_says() -> None:
    assert identifiers_in("IBAN DE89 3704 0044 0532 0130 00 1234 Sparkasse") == {(IBAN, THEIR_IBAN)}


@pytest.mark.parametrize(
    ("text", "value"),
    [
        (" Personalnummer     : 00012345        Druckdatum    : 15.07.2026", "12345"),
        ("Arbeitnehmerin: Erika Musterfrau · Personalnummer 4711 · Steuerklasse 1", "4711"),
        ("Pers.-Nr. 0815", "815"),
        ("PersNr: 123", "123"),
        ("Personal-Nr. 12-345", "12345"),
        ("Mitarbeiter-Nr. A-4711", "A4711"),
        ("Employee ID: 99881", "99881"),
    ],
)
def test_a_personnel_number_after_its_label(text: str, value: str) -> None:
    assert identifiers_in(text) == {(PERSONNEL, value)}


def test_no_personnel_number_without_label_or_value() -> None:
    assert identifiers_in("Supers Nr 4711, Nummer 12345") == set()
    assert identifiers_in("Personalnummer: siehe oben; Personalnummer 12") == set()


def test_a_key_index_tells_what_a_found_key_is_without_comparing_each() -> None:
    """`KeyIndex.matching` agrees with `matches`: a customer number is found as a contract
    number of its value, a domain as its subdomain, nothing else."""
    domain = Identifier(DOMAIN, "stadtwerke.example")
    customer = Identifier(CUSTOMER, "4711")
    iban = Identifier(IdentifierKind.IBAN, "DE02120300000000202051")
    index = KeyIndex((item, item.value) for item in (domain, customer, iban))
    found = [
        (DOMAIN, "stadtwerke.example"),
        (DOMAIN, "service.stadtwerke.example"),
        (DOMAIN, "neue-stadtwerke.example"),
        (CUSTOMER, "4711"),
        (IdentifierKind.CONTRACT_NUMBER, "4711"),
        (IdentifierKind.POLICY_NUMBER, "4711"),
        (CUSTOMER, "47110"),
        (IdentifierKind.IBAN, "DE02120300000000202051"),
        (IdentifierKind.CREDITOR_ID, "DE02120300000000202051"),
    ]
    for key in found:
        expected = [item.value for item in (domain, customer, iban) if matches(item, key)]
        assert index.matching(key) == expected, key
    assert index.matching((DOMAIN, "example")) == []
    # A contract number entered as such is not a customer number.
    contract = KeyIndex([(Identifier(IdentifierKind.CONTRACT_NUMBER, "4711"), "contract")])
    assert contract.matching((CUSTOMER, "4711")) == []
    assert contract.matching((IdentifierKind.CONTRACT_NUMBER, "4711")) == ["contract"]


def test_a_domain_stands_for_its_subdomains() -> None:
    domain = Identifier(DOMAIN, "stadtwerke.example")
    assert matches(domain, (DOMAIN, "service.stadtwerke.example"))
    assert not matches(domain, (DOMAIN, "neue-stadtwerke.example"))
    assert not matches(Identifier(CUSTOMER, "4711"), (CUSTOMER, "47110"))


def test_training_learns_what_only_one_contacts_documents_carry() -> None:
    utility, bank = ContactId(new_id()), ContactId(new_id())
    learned = mine_identifiers(
        [
            Confirmed(utility, None, frozenset({(IBAN, THEIR_IBAN), (IBAN, OWN_IBAN)})),
            Confirmed(
                utility, None, frozenset({(IBAN, THEIR_IBAN), (IBAN, OWN_IBAN), (CUSTOMER, "4711")})
            ),
            Confirmed(bank, None, frozenset({(IBAN, OWN_IBAN), (VAT, "DE123456789")})),
            Confirmed(bank, None, frozenset({(IBAN, OWN_IBAN)})),
        ]
    )
    # The owner's IBAN stands at both; the customer number and the VAT number only once.
    assert learned == {utility: [Identifier(IBAN, THEIR_IBAN, IdentifierSource.LEARNED)]}


def test_a_document_without_contact_or_a_taken_value_keeps_it_from_being_learned() -> None:
    utility = ContactId(new_id())
    found = frozenset({(IBAN, THEIR_IBAN)})
    theirs, unknown = Confirmed(utility, None, found), Confirmed(None, None, found)
    assert mine_identifiers([theirs, theirs, unknown]) == {}
    assert mine_identifiers([theirs, theirs], taken=found) == {}


def test_a_learned_identifier_points_to_the_topic_all_its_documents_carry() -> None:
    employer = ContactId(new_id())
    work, health = TagId(new_id()), TagId(new_id())
    number, policy, domain = (PERSONNEL, "4711"), (CUSTOMER, "KV-1"), (DOMAIN, "nord.example")
    learned = mine_identifiers(
        [
            Confirmed(employer, work, frozenset({number, domain})),
            Confirmed(employer, work, frozenset({number, domain})),
            Confirmed(employer, health, frozenset({policy, domain})),
            Confirmed(employer, health, frozenset({policy})),
            Confirmed(employer, None, frozenset({policy})),
        ]
    )
    assert learned == {
        employer: [
            Identifier(CUSTOMER, "KV-1", IdentifierSource.LEARNED),  # one without a topic
            Identifier(DOMAIN, "nord.example", IdentifierSource.LEARNED),  # two topics
            Identifier(PERSONNEL, "4711", IdentifierSource.LEARNED, work),
        ]
    }


def test_a_contact_keeps_entered_learned_and_rejected_identifiers_apart() -> None:
    iban = Identifier(IBAN, THEIR_IBAN)
    domain = Identifier(DOMAIN, "stadtwerke.example")
    vat = Identifier(VAT, "DE123456789")
    contact = Contact.create(name="Stadtwerke", now=NOW, identifiers=[iban])
    contact.set_learned([domain, vat, iban])
    assert [(item.kind, item.source) for item in contact.identifiers] == [
        (IBAN, IdentifierSource.MANUAL),
        (VAT, IdentifierSource.LEARNED),
        (DOMAIN, IdentifierSource.LEARNED),
    ]
    # Taking over a learned one, rejecting another.
    contact.set_identifiers([iban, vat], rejected=[domain])
    assert [(item.kind, item.source) for item in contact.identifiers] == [
        (IBAN, IdentifierSource.MANUAL),
        (VAT, IdentifierSource.MANUAL),
        (DOMAIN, IdentifierSource.REJECTED),
    ]
    assert [item.kind for item in contact.evidence()] == [IBAN, VAT]
    # Training does not bring a rejected one back; entering it by hand does.
    contact.set_learned([domain])
    assert contact.identifiers[-1].source is IdentifierSource.REJECTED
    contact.set_identifiers([domain])
    assert [(item.kind, item.source) for item in contact.identifiers] == [
        (DOMAIN, IdentifierSource.MANUAL)
    ]
    assert contact.drop_identifier(domain.key)
    assert contact.identifiers == []


def test_a_learned_number_belongs_to_whom_all_its_documents_surely_belong() -> None:
    """Issue #82: a customer or personnel number gets the user every document of it is surely
    theirs alone; what is learned notes the spaces of its documents."""
    employer = ContactId(new_id())
    anna, bob = UserId(new_id()), UserId(new_id())
    own, shared = SpaceId(new_id()), SpaceId(new_id())
    number, iban = (PERSONNEL, "12345"), (IBAN, THEIR_IBAN)

    def learn(*whose: frozenset[UserId]) -> list[Identifier]:
        documents = [
            Confirmed(employer, None, frozenset({number, iban}), space, users)
            for space, users in zip((own, shared), whose, strict=True)
        ]
        return list(mine_identifiers(documents)[employer])

    assert learn(frozenset({anna}), frozenset({anna})) == [
        Identifier(IBAN, THEIR_IBAN, IdentifierSource.LEARNED, learned_in=frozenset({own, shared})),
        Identifier(
            PERSONNEL, "12345", IdentifierSource.LEARNED, None, anna, frozenset({own, shared})
        ),
    ]
    # Another user, both, or nobody surely: nobody's.
    for whose in (
        (frozenset({anna}), frozenset({bob})),
        (frozenset({anna}), frozenset({anna, bob})),
        (frozenset({anna}), frozenset()),
    ):
        assert [item.user_id for item in learn(*whose)] == [None, None]


def test_who_sees_a_contacts_identifier() -> None:
    anna, bob = UserId(new_id()), UserId(new_id())
    own, other = SpaceId(new_id()), SpaceId(new_id())
    public = Identifier(IBAN, THEIR_IBAN)
    hers = Identifier(CUSTOMER, "K4711", user_id=anna)
    learned = Identifier(IBAN, OWN_IBAN, IdentifierSource.LEARNED, learned_in=frozenset({own}))
    learned_hers = Identifier(
        PERSONNEL, "12345", IdentifierSource.LEARNED, None, anna, frozenset({own, other})
    )
    old = Identifier(VAT, "DE123456789", IdentifierSource.LEARNED)  # before 0040: no spaces
    rejected = Identifier(DOMAIN, "nord.example", IdentifierSource.REJECTED)
    seen = {
        name: [seen_by(item, user, spaces) for item in (public, hers, learned, learned_hers)]
        for name, user, spaces in (
            ("anna", anna, {own}),
            ("bob in her space", bob, {own}),
            ("bob", bob, {other}),
        )
    }
    assert seen == {
        "anna": [True, True, True, True],
        "bob in her space": [True, False, True, False],
        "bob": [True, False, False, False],
    }
    assert not seen_by(old, anna, {own, other})
    assert not seen_by(rejected, anna, {own})


def test_every_kind_has_its_type_and_says_whose_it_is() -> None:
    assert set(TYPES) == set(IdentifierKind)
    assert all(TYPES[kind].kind is kind for kind in IdentifierKind)
    contracts = {
        IdentifierKind.CONTRACT_NUMBER,
        IdentifierKind.POLICY_NUMBER,
        IdentifierKind.MEMBERSHIP_NUMBER,
        IdentifierKind.METER_NUMBER,
        IdentifierKind.LOAN_NUMBER,
        IdentifierKind.MANDATE_REFERENCE,
        IdentifierKind.LICENSE_PLATE,
    }
    companies = {
        IdentifierKind.CREDITOR_ID,
        IdentifierKind.COMMERCIAL_REGISTER,
        IdentifierKind.TAX_NUMBER,
    }
    assert {IBAN, VAT, CUSTOMER, PERSONNEL, DOMAIN} | contracts | companies == CONTACT_KINDS
    assert {IBAN, TAX, SOCIAL, HEALTH, ADDRESS, IdentifierKind.CHILD_BENEFIT_NUMBER} == PERSON_KINDS
    # A tax number may be the one the tax office gave a user.
    assert {CUSTOMER, PERSONNEL, IdentifierKind.TAX_NUMBER} | contracts == NAMING_KINDS
    assert catalog()["customer_number"] == {"contact": True, "person": False, "names_user": True}


def test_candidates_of_any_reader_are_checked_and_weighed() -> None:
    """Without their place (a GiroCode's, in time a language model's), candidates are checked
    against their kind; a customer number that stands in a person's number found does not
    count."""
    social = social_security_number()
    found = identifiers_from(
        [
            Candidate(IBAN, "DE89 3704 0044 0532 0130 00"),
            Candidate(IBAN, "DE00 1234"),  # no IBAN: left out
            Candidate(SOCIAL, social),
            Candidate(CUSTOMER, social[:8]),
            Candidate(CUSTOMER, "K-4711"),
        ]
    )
    assert found == {
        (IBAN, THEIR_IBAN),
        (SOCIAL, social),
        (CUSTOMER, "K4711"),
    }
