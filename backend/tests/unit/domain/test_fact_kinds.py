"""The kinds of facts of #145: found after their labels (or anywhere, where their form tells),
normalised, with their roles; a reference "Ihre Rechnung Nr." refers to another's document."""

import pytest

from lekto.core.domain.document_facts import (
    NUMBER_KINDS,
    ROLES,
    FactRole,
    found_facts,
)
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers import (
    LEARN_FROM,
    Confirmed,
    Identifier,
    IdentifierKind,
    IdentifierSource,
    identifiers_in,
    matches,
    mine_identifiers,
    normalise_identifier,
    places_in,
    referred_in,
    related_keys,
)
from lekto.core.domain.identifiers.creditor_id import creditor_id_valid
from lekto.core.domain.ids import ContactId, new_id

K = IdentifierKind


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("Vertragsnummer: 123-456-789", K.CONTRACT_NUMBER, "123456789"),
        ("Contract No. AB-1234", K.CONTRACT_NUMBER, "AB1234"),
        ("Versicherungsscheinnummer KV 1234567", K.POLICY_NUMBER, "KV1234567"),
        ("Policennummer: 9988776", K.POLICY_NUMBER, "9988776"),
        ("Mitgliedsnummer 004711", K.MEMBERSHIP_NUMBER, "004711"),
        ("Zählernummer: 1ESY1234567", K.METER_NUMBER, "1ESY1234567"),
        (
            "Zählpunkt DE0001234567890000000000000000001",
            K.METER_NUMBER,
            "DE0001234567890000000000000000001",
        ),
        ("Darlehensnummer 6001234567", K.LOAN_NUMBER, "6001234567"),
        ("Mandatsreferenz: M-000123", K.MANDATE_REFERENCE, "M000123"),
        ("Kfz-Kennzeichen: M-AB 1234", K.LICENSE_PLATE, "MAB1234"),
        ("Kfz-Kennzeichen M AB 1234", K.LICENSE_PLATE, "MAB1234"),
        ("Fahrzeugkennzeichen HH-X 12E", K.LICENSE_PLATE, "HHX12E"),
        ("Rechnungsnummer: R-2026-0815", K.INVOICE_NUMBER, "R20260815"),
        ("Invoice No. 2026/104", K.INVOICE_NUMBER, "2026104"),
        ("Gutschriftsnummer G-1001", K.CREDIT_NOTE_NUMBER, "G1001"),
        ("Bestellnummer 4500012345", K.ORDER_NUMBER, "4500012345"),
        ("Auftragsnummer: A 77881", K.ORDER_NUMBER, "A77881"),
        ("Aktenzeichen: 4 C 123/26 bitte angeben", K.FILE_REFERENCE, "4C12326"),
        ("Unser Zeichen AB-12/3", K.OUR_REFERENCE, "AB123"),
        ("Ihr Zeichen: XY 99", K.YOUR_REFERENCE, "XY99"),
        ("Schadennummer 2026-55-1", K.CLAIM_NUMBER, "2026551"),
        ("Ticket-Nr. #T-7781", K.TICKET_NUMBER, "T7781"),
        ("Vorgangsnummer 12345", K.TICKET_NUMBER, "12345"),
        ("Steuernummer 123/456/78901", K.TAX_NUMBER, "12345678901"),
        ("Amtsgericht München HRB 12345", K.COMMERCIAL_REGISTER, "HRB12345"),
        ("Gläubiger-ID: DE98 ZZZ 09999999999", K.CREDITOR_ID, "DE98ZZZ09999999999"),
        ("Einzug durch DE98ZZZ09999999999", K.CREDITOR_ID, "DE98ZZZ09999999999"),
        ("Kindergeldnummer 123FK456789", K.CHILD_BENEFIT_NUMBER, "123FK456789"),
        ("Kindergeldnummer: 123 FK 456789", K.CHILD_BENEFIT_NUMBER, "123FK456789"),
        # A label at the end of a compound word.
        ("Bausparvertragsnummer 12345678", K.CONTRACT_NUMBER, "12345678"),
        ("Hausratversicherungsnummer 12345", K.POLICY_NUMBER, "12345"),
        ("Kfz-Versicherungsnummer KV-998877", K.POLICY_NUMBER, "KV998877"),
        ("Vereinsmitgliedsnummer 4711", K.MEMBERSHIP_NUMBER, "4711"),
        ("Stromzählernummer 1ESY1234567", K.METER_NUMBER, "1ESY1234567"),
        # A reference ends before a joining word or a date; parts joined by a dash between spaces.
        ("Az. 4 C 123/26 vom 12.10.2026", K.FILE_REFERENCE, "4C12326"),
        ("Gz.: II 3 - 1234/26", K.FILE_REFERENCE, "II3123426"),
        ("HRB 12345 B", K.COMMERCIAL_REGISTER, "HRB12345B"),
        ("HRB 4711 AG Mannheim", K.COMMERCIAL_REGISTER, "HRB4711"),
        ("HRB 12345 DE 123456789", K.COMMERCIAL_REGISTER, "HRB12345"),
    ],
)
def test_each_kind_is_found_and_normalised(text: str, kind: IdentifierKind, value: str) -> None:
    assert (kind, value) in identifiers_in(text)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Rentenversicherungsnummer: 65 170839 J 003", K.POLICY_NUMBER),
        ("Krankenversicherungsnummer A123456789", K.POLICY_NUMBER),
        ("Kundennummer 4711", K.CONTRACT_NUMBER),  # the customer number keeps its kind
        ("IBAN DE89 3704 0044 0532 0130 00", K.CREDITOR_ID),  # no letter in the business code
        ("Gläubiger-ID DE98ZZZ09999999998", K.CREDITOR_ID),  # the check digits do not fit
        ("Aktenzeichen: bitte angeben", K.FILE_REFERENCE),
        # A label is a whole word.
        ("Invoice November 2026", K.INVOICE_NUMBER),
        ("Membership November 2026", K.MEMBERSHIP_NUMBER),
        ("Your refund 302-1234567-1234567", K.YOUR_REFERENCE),
        ("Case notes 12", K.TICKET_NUMBER),
        ("Azubi 2026", K.FILE_REFERENCE),
        # A person's insurance number, also hyphenated or with its check digit misread.
        ("Sozial-Versicherungsnummer 12 345678 A 124", K.POLICY_NUMBER),
        ("Sozialversicherungsnummer 12345678A124", K.POLICY_NUMBER),
        # No plate: no letters, an authority's reference.
        ("Polizeiliches Kennzeichen 12345", K.LICENSE_PLATE),
        ("Unser Kennzeichen 123/45", K.LICENSE_PLATE),
        # A person's tax ID after "Steuernummer" is no tax number.
        ("Steuernummer: 86 095 742 001", K.TAX_NUMBER),
        ("Steuernummer 86095742001", K.TAX_NUMBER),
        # A DIN 5008 line of references runs labels and values together: none is taken.
        ("unser zeichen datum ab-123 xy-45 01.10.2026", K.OUR_REFERENCE),
    ],
)
def test_what_is_no_fact_of_a_kind(text: str, kind: IdentifierKind) -> None:
    assert kind not in {found for found, _ in identifiers_in(text)}


def test_the_creditor_id_check() -> None:
    assert creditor_id_valid("DE98ZZZ09999999999")
    assert not creditor_id_valid("DE98ZZZ0999999999X")
    with pytest.raises(ValidationError, match="no valid creditor id"):
        normalise_identifier(K.CREDITOR_ID, "DE00ZZZ09999999999")


def test_every_kind_has_a_role_and_the_numbers_of_documents_are_no_identifiers() -> None:
    assert ROLES[K.INVOICE_NUMBER] is FactRole.OWN
    assert ROLES[K.FILE_REFERENCE] is FactRole.THREAD
    assert ROLES[K.YOUR_REFERENCE] is FactRole.REFERS
    assert ROLES[K.CONTRACT_NUMBER] is FactRole.TARGET
    assert ROLES[K.CREDITOR_ID] is FactRole.CONTACT
    assert ROLES[K.CHILD_BENEFIT_NUMBER] is FactRole.PERSON
    assert {
        K.INVOICE_NUMBER,
        K.CREDIT_NOTE_NUMBER,
        K.ORDER_NUMBER,
        K.FILE_REFERENCE,
        K.OUR_REFERENCE,
        K.CLAIM_NUMBER,
        K.TICKET_NUMBER,
        K.YOUR_REFERENCE,
    } == NUMBER_KINDS


def test_a_number_after_ihre_refers_to_another_s_document() -> None:
    """A reminder: "Ihre Rechnung Nr. 4711" is the invoice's number, this one refers to it;
    the reminder's own number is its own."""
    text = "Mahnung Nr. M-77\nRechnungsnummer: M-77\nIhre Rechnung Nr. 4711 vom 04.06. ist offen."
    assert referred_in(text) == {(K.INVOICE_NUMBER, "4711")}
    facts = {
        fact.value: fact.role
        for fact in found_facts(text, identifiers_in(text), (), places_in(text), referred_in(text))
    }
    assert facts == {"M77": FactRole.OWN, "4711": FactRole.REFERS}
    # Written alone as well, it is the document's own.
    both = "Rechnungsnummer 4711\nIhre Rechnung Nr. 4711"
    assert referred_in(both) == set()


def test_only_a_document_s_own_number_refers_after_ihre() -> None:
    """The addressee's contract, file reference or child benefit number keeps its role."""
    text = (
        "Ihre Vertragsnummer: 1234567\nIhr Aktenzeichen 4 C 123/26\n"
        "Ihre Kindergeldnummer 123FK456789"
    )
    roles = {
        fact.kind: fact.role
        for fact in found_facts(text, identifiers_in(text), (), places_in(text), referred_in(text))
    }
    assert roles == {
        K.CONTRACT_NUMBER: FactRole.TARGET,
        K.FILE_REFERENCE: FactRole.THREAD,
        K.CHILD_BENEFIT_NUMBER: FactRole.PERSON,
    }


@pytest.mark.parametrize("kind", [K.CONTRACT_NUMBER, K.POLICY_NUMBER, K.MEMBERSHIP_NUMBER])
def test_a_contact_s_customer_number_still_matches_what_it_was(kind: IdentifierKind) -> None:
    """Until #145 a contract, policy or membership number was a customer number: a contact's
    customer number of that value is still its identifier."""
    customer = Identifier.parse(K.CUSTOMER_NUMBER, "123-456-789")
    assert matches(customer, (kind, "123456789"))
    assert not matches(customer, (kind, "123456788"))
    assert not matches(customer, (K.INVOICE_NUMBER, "123456789"))
    assert not matches(Identifier.parse(kind, "123456789"), (K.CUSTOMER_NUMBER, "123456789"))


def test_a_customer_number_rejected_still_keeps_the_numbers_it_was_from_being_learned() -> None:
    contact = ContactId(new_id())
    documents = [
        Confirmed(contact=contact, topic=None, found=frozenset({(K.CONTRACT_NUMBER, "12345")}))
        for _ in range(LEARN_FROM)
    ]
    assert mine_identifiers(documents) == {
        contact: [Identifier(K.CONTRACT_NUMBER, "12345", IdentifierSource.LEARNED)]
    }
    assert mine_identifiers(documents, taken=[(K.CUSTOMER_NUMBER, "12345")]) == {}
    assert related_keys((K.CONTRACT_NUMBER, "1")) == {
        (K.CONTRACT_NUMBER, "1"),
        (K.CUSTOMER_NUMBER, "1"),
    }
    assert related_keys((K.IBAN, "1")) == {(K.IBAN, "1")}
