"""What a kind of identifier is (`IdentifierType`), what a reader takes for one (`Candidate`),
and what the kinds share: separators between the characters of a number, a value after its
label."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.reasons import ReasonCode, because


class IdentifierKind(StrEnum):
    """The kinds of identifiers, which are the kinds of facts too (`domain.document_facts`;
    `.idea/fakten.md`, the catalog by role)."""

    IBAN = "iban"
    VAT_ID = "vat_id"
    CUSTOMER_NUMBER = "customer_number"  # until #145 also contract, policy, membership numbers
    PERSONNEL_NUMBER = "personnel_number"  # an employee's number at the employer
    EMAIL_DOMAIN = "email_domain"  # of e-mail addresses and web addresses
    TAX_ID = "tax_id"  # the German tax ID of a person (steuerliche Identifikationsnummer)
    SOCIAL_SECURITY_NUMBER = "social_security_number"  # Renten-/Sozialversicherungsnummer
    HEALTH_INSURANCE_NUMBER = "health_insurance_number"  # Krankenversichertennummer
    EMAIL_ADDRESS = "email_address"  # a whole address, a person's
    # Point to the contact (issue #145).
    CREDITOR_ID = "creditor_id"  # SEPA Gläubiger-Identifikationsnummer
    COMMERCIAL_REGISTER = "commercial_register"  # Handelsregisternummer (HRB 12345)
    TAX_NUMBER = "tax_number"  # a company's Steuernummer
    # Point to what a series refers to: a contract, a policy, a meter.
    CONTRACT_NUMBER = "contract_number"
    POLICY_NUMBER = "policy_number"  # Versicherungsschein-, Policennummer
    MEMBERSHIP_NUMBER = "membership_number"
    METER_NUMBER = "meter_number"  # Zählernummer
    LOAN_NUMBER = "loan_number"  # Darlehensnummer
    MANDATE_REFERENCE = "mandate_reference"  # SEPA Mandatsreferenz
    LICENSE_PLATE = "license_plate"  # Kfz-Kennzeichen
    # Mark the document itself.
    INVOICE_NUMBER = "invoice_number"
    CREDIT_NOTE_NUMBER = "credit_note_number"
    ORDER_NUMBER = "order_number"  # Bestell-, Auftragsnummer
    # Join a strand.
    FILE_REFERENCE = "file_reference"  # Aktenzeichen, Geschäftszeichen
    OUR_REFERENCE = "our_reference"  # "Unser Zeichen"
    CLAIM_NUMBER = "claim_number"  # Schadennummer
    TICKET_NUMBER = "ticket_number"  # Ticket-, Vorgangsnummer
    # Refer to a document.
    YOUR_REFERENCE = "your_reference"  # "Ihr Zeichen"
    # Point to a person.
    CHILD_BENEFIT_NUMBER = "child_benefit_number"  # Kindergeldnummer


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
    refers: bool = False  # after "Ihr", "Ihre", "your": the number of another's document


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


YOUR = r"(?P<your>(?:ihr(?:e[mnrs]?)?|your)\s+)?"
"""Before a label: the number belongs to the addressee's document ("Ihre Rechnung Nr.")."""
_JOINING = r"(?:vom|von|und|bis|am|an|zum|zur|datum|date|dated|from|of|and|to|per)"
"""Words that end a reference: what follows them is another value (a date, a second one)."""
_DATE_PART = r"\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2})(?![a-z0-9])"
REFERENCE_VALUE = (
    rf"\.?\s*[:.]?\s*(?P<value>(?!{_JOINING}(?![a-z0-9]))[a-z0-9][a-z0-9./-]*"
    rf"(?:(?: [-/])? (?!{_JOINING}(?![a-z0-9]))(?!{_DATE_PART})"
    r"(?:[a-z]{1,3} (?=[a-z./-]*\d))?(?=[a-z./-]*\d)[a-z0-9./-]+)*)"
)
"""A value after its label, as `VALUE`, where a short group of letters may stand between
parts with digits (an Aktenzeichen `4 C 123/26`), and parts may be joined by a dash or a slash
between spaces (`II 3 - 1234/26`); a joining word ("vom", "und", "Datum") or a date ends it."""
NUMBER_VALUE = VALUE.replace("(", "(?P<value>", 1)
"""`VALUE` with its group named."""
COMPOUND = r"[a-zäöüß]+"
"""Any word a label may end (`labelled`): "Bausparvertragsnummer", "Stromzählernummer"."""


def labelled(labels: str, value: str = NUMBER_VALUE, *, compounds: str = "") -> re.Pattern[str]:
    """A pattern of a value after one of `labels` (alternatives, in lower case), with "Ihr"
    or "your" before them or not; a label is a whole word ("Invoice November" is none), or
    the end of a compound word where `compounds` (a pattern of the words before it the kind
    allows: "Bauspar" before "vertragsnummer") says so."""
    before = (
        rf"(?:(?<![a-zäöüß]){YOUR}|(?<![a-zäöüß])(?:{compounds})-?)"
        if compounds
        else (rf"(?<![a-zäöüß]){YOUR}")
    )
    return re.compile(rf"{before}(?:{labels})(?![a-zäöüß]){value}")


def after_labels(kind: IdentifierKind, label: re.Pattern[str], text: str) -> Iterator[Candidate]:
    """The values a `labelled` pattern finds in `text`; `refers` after "Ihr"."""
    for match in label.finditer(text):
        yield Candidate(kind, match.group("value"), match.span("value"), match["your"] is not None)


class LabelledNumber(IdentifierType):
    """A number found after its label (`labels`), compared without separators in upper case:
    `shortest` to `longest` letters and digits, one a digit."""

    labels: ClassVar[str]
    compounds: ClassVar[str] = ""  # words a label may end (`labelled`)
    value: ClassVar[str] = NUMBER_VALUE
    shortest: ClassVar[int] = 3
    longest: ClassVar[int] = 30

    def __init__(self) -> None:
        self._label = labelled(self.labels, self.value, compounds=self.compounds)
        self._form = re.compile(rf"(?=[A-Z0-9]*\d)[A-Z0-9]{{{self.shortest},{self.longest}}}")

    def normalise(self, raw: str) -> str:
        value = SEPARATORS.sub("", raw.strip()).upper()
        if not self._form.fullmatch(value):
            raise ValidationError(because(ReasonCode.NOT_OF_KIND, kind=self.kind.value, value=raw))
        return value

    def find(self, text: str) -> Iterator[Candidate]:
        return after_labels(self.kind, self._label, text)
