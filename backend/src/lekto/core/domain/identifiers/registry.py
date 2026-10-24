"""The kinds of identifiers Lekto knows, one type each (`TYPES`), and what follows from them:
the kinds of contacts, of persons and those that may name a user, and the comparable form of
a value."""

from collections.abc import Mapping

from lekto.core.domain.identifiers.base import IdentifierKind, IdentifierType
from lekto.core.domain.identifiers.customer_number import CustomerNumber
from lekto.core.domain.identifiers.email_address import EmailAddress
from lekto.core.domain.identifiers.email_domain import EmailDomain
from lekto.core.domain.identifiers.health_insurance_number import HealthInsuranceNumber
from lekto.core.domain.identifiers.iban import Iban
from lekto.core.domain.identifiers.personnel_number import PersonnelNumber
from lekto.core.domain.identifiers.social_security_number import SocialSecurityNumber
from lekto.core.domain.identifiers.tax_id import TaxId
from lekto.core.domain.identifiers.vat_id import VatId

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
