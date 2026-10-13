from datetime import UTC, datetime

import pytest

from papiq.core.domain.errors import ValidationError
from papiq.core.domain.identifiers import (
    Identifier,
    IdentifierKind,
    IdentifierSource,
    identifiers_in,
    matches,
    mine_identifiers,
    normalise_identifier,
)
from papiq.core.domain.ids import ContactId, new_id
from papiq.core.domain.master_data import Contact

NOW = datetime(2026, 10, 13, tzinfo=UTC)
IBAN = IdentifierKind.IBAN
VAT = IdentifierKind.VAT_ID
CUSTOMER = IdentifierKind.CUSTOMER_NUMBER
DOMAIN = IdentifierKind.EMAIL_DOMAIN
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
        (VAT, "DE 123 456 789", "DE123456789"),
        (VAT, "ATU12345678", "ATU12345678"),
        (CUSTOMER, "K-778.81/2", "K778812"),
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
        (VAT, "DE12345"),
        (CUSTOMER, "Musterkunde"),  # no digit
        (CUSTOMER, "12"),
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
        (CUSTOMER, "123456789"),
        (CUSTOMER, "K77881"),
        (DOMAIN, "stadtwerke-musterstadt.de"),
    }


def test_a_domain_stands_for_its_subdomains() -> None:
    domain = Identifier(DOMAIN, "stadtwerke.example")
    assert matches(domain, (DOMAIN, "service.stadtwerke.example"))
    assert not matches(domain, (DOMAIN, "neue-stadtwerke.example"))
    assert not matches(Identifier(CUSTOMER, "4711"), (CUSTOMER, "47110"))


def test_training_learns_what_only_one_contacts_documents_carry() -> None:
    utility, bank = ContactId(new_id()), ContactId(new_id())
    learned = mine_identifiers(
        [
            (utility, {(IBAN, THEIR_IBAN), (IBAN, OWN_IBAN)}),
            (utility, {(IBAN, THEIR_IBAN), (IBAN, OWN_IBAN), (CUSTOMER, "4711")}),
            (bank, {(IBAN, OWN_IBAN), (VAT, "DE123456789")}),
            (bank, {(IBAN, OWN_IBAN)}),
        ]
    )
    # The owner's IBAN stands at both; the customer number and the VAT number only once.
    assert learned == {utility: [Identifier(IBAN, THEIR_IBAN, IdentifierSource.LEARNED)]}


def test_a_document_without_contact_or_a_taken_value_keeps_it_from_being_learned() -> None:
    utility = ContactId(new_id())
    found = {(IBAN, THEIR_IBAN)}
    assert mine_identifiers([(utility, found), (utility, found), (None, found)]) == {}
    assert mine_identifiers([(utility, found), (utility, found)], taken=found) == {}


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
