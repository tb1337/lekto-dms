"""The kinds of identifiers Lekto knows, one type each (`TYPES`), and what follows from them:
the kinds of contacts, of persons and those that may name a user, and the comparable form of
a value."""

from collections.abc import Mapping

from lekto.core.domain.identifiers.base import IdentifierKind, IdentifierType
from lekto.core.domain.identifiers.child_benefit_number import ChildBenefitNumber
from lekto.core.domain.identifiers.claim_number import ClaimNumber
from lekto.core.domain.identifiers.commercial_register import CommercialRegister
from lekto.core.domain.identifiers.contract_number import ContractNumber
from lekto.core.domain.identifiers.credit_note_number import CreditNoteNumber
from lekto.core.domain.identifiers.creditor_id import CreditorId
from lekto.core.domain.identifiers.customer_number import CustomerNumber
from lekto.core.domain.identifiers.email_address import EmailAddress
from lekto.core.domain.identifiers.email_domain import EmailDomain
from lekto.core.domain.identifiers.file_reference import FileReference
from lekto.core.domain.identifiers.health_insurance_number import HealthInsuranceNumber
from lekto.core.domain.identifiers.iban import Iban
from lekto.core.domain.identifiers.invoice_number import InvoiceNumber
from lekto.core.domain.identifiers.letter_date import LetterDate
from lekto.core.domain.identifiers.license_plate import LicensePlate
from lekto.core.domain.identifiers.loan_number import LoanNumber
from lekto.core.domain.identifiers.mandate_reference import MandateReference
from lekto.core.domain.identifiers.membership_number import MembershipNumber
from lekto.core.domain.identifiers.meter_number import MeterNumber
from lekto.core.domain.identifiers.order_number import OrderNumber
from lekto.core.domain.identifiers.our_reference import OurReference
from lekto.core.domain.identifiers.personnel_number import PersonnelNumber
from lekto.core.domain.identifiers.policy_number import PolicyNumber
from lekto.core.domain.identifiers.social_security_number import SocialSecurityNumber
from lekto.core.domain.identifiers.tax_id import TaxId
from lekto.core.domain.identifiers.tax_number import TaxNumber
from lekto.core.domain.identifiers.ticket_number import TicketNumber
from lekto.core.domain.identifiers.vat_id import VatId
from lekto.core.domain.identifiers.your_reference import YourReference

TYPES: Mapping[IdentifierKind, IdentifierType] = {
    item.kind: item
    for item in (
        Iban(),
        VatId(),
        CustomerNumber(),
        PersonnelNumber(),
        EmailDomain(),
        TaxId(),
        SocialSecurityNumber(),
        HealthInsuranceNumber(),
        EmailAddress(),
        CreditorId(),
        CommercialRegister(),
        TaxNumber(),
        ContractNumber(),
        PolicyNumber(),
        MembershipNumber(),
        MeterNumber(),
        LoanNumber(),
        MandateReference(),
        LicensePlate(),
        InvoiceNumber(),
        CreditNoteNumber(),
        OrderNumber(),
        FileReference(),
        OurReference(),
        ClaimNumber(),
        TicketNumber(),
        YourReference(),
        LetterDate(),
        ChildBenefitNumber(),
    )
}
"""Every kind's type (a test holds that none is missing)."""

CONTACT_KINDS = frozenset(kind for kind, item in TYPES.items() if item.for_contacts)
"""The kinds a contact's identifiers have; training learns only these."""
PERSON_KINDS = frozenset(kind for kind, item in TYPES.items() if item.for_persons)
"""The kinds a person's identifiers have."""
NAMING_KINDS = frozenset(kind for kind, item in TYPES.items() if item.names_user)
"""The kinds of a contact's identifiers that may name the user they belong to (a contract, a
policy, a personnel number)."""
OWN_KINDS = PERSON_KINDS - CONTACT_KINDS
"""The kinds only a person has (not the IBAN: a contact has one too)."""


def type_of(kind: IdentifierKind) -> IdentifierType:
    return TYPES[kind]


def normalise_identifier(kind: IdentifierKind, raw: str) -> str:
    """The comparable form of an identifier (`IdentifierType.normalise`): numbers without
    spaces and separators in upper case (an IBAN with a valid check sum, a personnel number
    without leading zeros, a person's number with a valid check digit), a domain or an e-mail
    address in lower case; ValidationError if `raw` is none of its kind."""
    return TYPES[kind].normalise(raw)


def catalog() -> dict[str, dict[str, bool]]:
    """The kinds and whose they are, for the OpenAPI document (`x-identifier-kinds`): `contact`,
    `person`, `names_user`."""
    return {
        kind.value: {
            "contact": item.for_contacts,
            "person": item.for_persons,
            "names_user": item.names_user,
        }
        for kind, item in TYPES.items()
    }
