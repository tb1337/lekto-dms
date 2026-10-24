"""Identifiers of contacts and of persons. A contact's are values a document of the contact
carries and no other contact's does (an IBAN, a VAT number, the customer number, the personnel
number at an employer, the domain of its e-mail addresses); found in the text, they are hard
evidence for the contact. A person's (a user's profile) are their own numbers: an IBAN, the tax
ID, the social security and the health insurance number, e-mail addresses; found in the text,
they are hard evidence for whose document it is. A value is never both a contact's and a
person's; a customer or personnel number of a contact may name the user it belongs to.

Each kind is a type of its own, in its own module (`base.IdentifierType`: whose it is, its
comparable form, how it is found in a text and written there); the registry lists them
(`registry.TYPES`). Readers take values for identifiers (`Candidate`); Lekto checks each
against its kind and weighs them together (`reading.identifiers_from`), whoever read them: the
patterns of each kind in a text, a GiroCode, and in time a language model.

Admins enter identifiers by hand. Training learns more from confirmed documents (see
`learning.mine_identifiers`): a value that stands in at least two of them, all of one contact.
A value in documents of several contacts (the owner's own IBAN on every direct debit) is never
learned. An admin can reject a learned one; it is then not learned again.

Who sees a contact's identifier (issue #82, Tobi 24.10.2026: "wenn Datenschutz dann richtig";
`seen_by`): one entered by hand that names no user is the contact's own and everyone's to see;
one that names a user (a customer or personnel number) only that user's and the admins'; a
learned one only theirs who are a member of a space a document it was learned from lies in,
so a number learned from the pay slips in a personal space stays its user's; a rejected one
the admins' alone. Training gives a learned customer or personnel number the user every one of
its documents surely belongs to (`Confirmed.whose`); a user maintains the numbers that name
them in their profile, and may decline a learned one (it is then rejected).

An identifier may point to one of its contact's topics (a personnel number to "work", a policy
number to "health insurance"): found in a document, it is evidence for the pair of contact and
topic. A learned one gets a topic only if all the confirmed documents it stands in carry it.
"""

from lekto.core.domain.identifiers.base import Candidate, IdentifierKind, IdentifierType, Key
from lekto.core.domain.identifiers.email_domain import FREE_MAIL
from lekto.core.domain.identifiers.health_insurance_number import health_insurance_number_valid
from lekto.core.domain.identifiers.iban import iban_valid
from lekto.core.domain.identifiers.identifier import (
    MAX_IDENTIFIERS,
    Identifier,
    IdentifierSource,
    matches,
)
from lekto.core.domain.identifiers.learning import LEARN_FROM, Confirmed, mine_identifiers
from lekto.core.domain.identifiers.reading import (
    candidates_in,
    identifiers_from,
    identifiers_in,
    of_person,
)
from lekto.core.domain.identifiers.registry import (
    CONTACT_KINDS,
    NAMING_KINDS,
    PERSON_KINDS,
    TYPES,
    catalog,
    normalise_identifier,
    type_of,
)
from lekto.core.domain.identifiers.social_security_number import social_security_number_valid
from lekto.core.domain.identifiers.tax_id import tax_id_valid
from lekto.core.domain.identifiers.visibility import seen_by

__all__ = [
    "CONTACT_KINDS",
    "FREE_MAIL",
    "LEARN_FROM",
    "MAX_IDENTIFIERS",
    "NAMING_KINDS",
    "PERSON_KINDS",
    "TYPES",
    "Candidate",
    "Confirmed",
    "Identifier",
    "IdentifierKind",
    "IdentifierSource",
    "IdentifierType",
    "Key",
    "candidates_in",
    "catalog",
    "health_insurance_number_valid",
    "iban_valid",
    "identifiers_from",
    "identifiers_in",
    "matches",
    "mine_identifiers",
    "normalise_identifier",
    "of_person",
    "seen_by",
    "social_security_number_valid",
    "tax_id_valid",
    "type_of",
]
