"""What a kind of identifier is (`IdentifierType`), what a reader takes for one (`Candidate`),
and what the kinds share: separators between the characters of a number, a value after its
label."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar


class IdentifierKind(StrEnum):
    IBAN = "iban"
    VAT_ID = "vat_id"
    CUSTOMER_NUMBER = "customer_number"  # also contract, policy and membership numbers
    PERSONNEL_NUMBER = "personnel_number"  # an employee's number at the employer
    EMAIL_DOMAIN = "email_domain"  # of e-mail addresses and web addresses
    TAX_ID = "tax_id"  # the German tax ID of a person (steuerliche Identifikationsnummer)
    SOCIAL_SECURITY_NUMBER = "social_security_number"  # Renten-/Sozialversicherungsnummer
    HEALTH_INSURANCE_NUMBER = "health_insurance_number"  # Krankenversichertennummer
    EMAIL_ADDRESS = "email_address"  # a whole address, a person's


type Key = tuple[IdentifierKind, str]
"""An identifier's kind and normalised value: what compares."""


@dataclass(frozen=True)
class Candidate:
    """A value a reader takes for an identifier of `kind`, as it read it (`raw`), and where it
    stands in the text it read, if it tells (characters `start` to `end`). Readers are the
    patterns of each kind in a text (`IdentifierType.find`) and a GiroCode's IBAN; a language
    model could be one. Lekto checks each against its kind (`IdentifierType.normalise`) and
    weighs them together (`identifiers_from`)."""

    kind: IdentifierKind
    raw: str
    span: tuple[int, int] | None = None


SEPARATORS = re.compile(r"[\s./-]+")
"""What may stand between the characters of a number as written."""
WRITTEN_SEPARATORS = r"[\s./\u00ad-]*"
"""Between the characters of a number as a text writes it: separators, also several (two
spaces, a line break and its indent of an OCR text) and soft hyphens, or none."""

# A label, then the value: its first word, and further words that hold a digit (`DE 123 456
# 789`, `123 456`), not the words after it (`DE123456789 Steuernummer`).
VALUE = r"\.?\s*[:.]?\s*([a-z0-9][a-z0-9./-]*(?: (?=[a-z./-]*\d)[a-z0-9./-]+)*)"


class IdentifierType:
    """One kind of identifier, all it knows in one place (each kind's module defines one, the
    registry lists them): whose it is (`for_contacts`, `for_persons`), whether a contact's may
    name the user it belongs to (`names_user`), its comparable form (`normalise`), how it is
    found in a text (`find`), how a value of it may stand in one (`written`) and when a found
    value is it (`matches`)."""

    kind: ClassVar[IdentifierKind]
    for_contacts: ClassVar[bool] = False
    for_persons: ClassVar[bool] = False
    names_user: ClassVar[bool] = False

    def normalise(self, raw: str) -> str:
        """The comparable form of `raw`; ValidationError, with the kind's reason, if it is none
        of the kind."""
        raise NotImplementedError

    def find(self, text: str) -> Iterator[Candidate]:
        """What `text` (as `evidence.normalise` makes it: lower case, whitespace collapsed)
        shows of the kind, unchecked."""
        return iter(())

    def written(self, value: str) -> str:
        """A pattern of how `value` may stand in a text, regardless of case: its characters with
        separators between them or none (`WRITTEN_SEPARATORS`), not within a longer word or
        number."""
        pattern = WRITTEN_SEPARATORS.join(re.escape(char) for char in value)
        return rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])"

    def matches(self, value: str, found: str) -> bool:
        """Whether a value found (normalised) is the identifier `value`."""
        return found == value


def after_label(kind: IdentifierKind, label: re.Pattern[str], text: str) -> Iterator[Candidate]:
    """The values `label` (a pattern whose first group is the value) finds in `text`."""
    for match in label.finditer(text):
        yield Candidate(kind, match.group(1), match.span(1))
