"""Identifiers of contacts and of persons. A contact's are values a document of the contact
carries and no other contact's does (an IBAN, a VAT number, the customer number, the personnel
number at an employer, the domain of its e-mail addresses); found in the text, they are hard
evidence for the contact. A person's (a user's profile) are their own numbers: an IBAN, the tax
ID, the social security and the health insurance number, e-mail addresses; found in the text,
they are hard evidence for whose document it is. A value is never both a contact's and a
person's; a customer or personnel number of a contact may name the user it belongs to.

Admins enter identifiers by hand. Training learns more from confirmed documents (see
`mine_identifiers`): a value that stands in at least two of them, all of one contact. A value
in documents of several contacts (the owner's own IBAN on every direct debit) is never learned.
An admin can reject a learned one; it is then not learned again.

An identifier may point to one of its contact's topics (a personnel number to "work", a policy
number to "health insurance"): found in a document, it is evidence for the pair of contact and
topic. A learned one gets a topic only if all the confirmed documents it stands in carry it.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.evidence import normalise
from lekto.core.domain.ids import ContactId, TagId, UserId
from lekto.core.domain.reasons import ReasonCode, because

MAX_IDENTIFIERS = 100
"""Identifiers of one contact, entered and learned."""
LEARN_FROM = 2
"""Confirmed documents of one contact a value must stand in to be learned."""


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


CONTACT_KINDS = frozenset(
    {
        IdentifierKind.IBAN,
        IdentifierKind.VAT_ID,
        IdentifierKind.CUSTOMER_NUMBER,
        IdentifierKind.PERSONNEL_NUMBER,
        IdentifierKind.EMAIL_DOMAIN,
    }
)
"""The kinds a contact's identifiers have; training learns only these."""
PERSON_KINDS = frozenset(
    {
        IdentifierKind.IBAN,
        IdentifierKind.TAX_ID,
        IdentifierKind.SOCIAL_SECURITY_NUMBER,
        IdentifierKind.HEALTH_INSURANCE_NUMBER,
        IdentifierKind.EMAIL_ADDRESS,
    }
)
"""The kinds a person's identifiers have."""
NAMING_KINDS = frozenset({IdentifierKind.CUSTOMER_NUMBER, IdentifierKind.PERSONNEL_NUMBER})
"""The kinds of a contact's identifiers that may name the user they belong to (a contract, a
policy, a personnel number)."""


class IdentifierSource(StrEnum):
    MANUAL = "manual"
    LEARNED = "learned"
    REJECTED = "rejected"  # learned, then rejected by an admin: not learned again


@dataclass(frozen=True)
class Identifier:
    """`value` is normalised (see `normalise_identifier`); kind and value are unique across
    all contacts. `topic_id`: the topic of its contact it points to, if any (the contact checks
    that it enables it). `user_id`: the user a contact's customer or personnel number belongs
    to, if one does (entered by hand only); found in a document, it is evidence for them too.
    A person's identifier has neither."""

    kind: IdentifierKind
    value: str
    source: IdentifierSource = IdentifierSource.MANUAL
    topic_id: TagId | None = None
    user_id: UserId | None = None

    @classmethod
    def parse(
        cls,
        kind: IdentifierKind,
        raw: str,
        source: IdentifierSource = IdentifierSource.MANUAL,
        topic_id: TagId | None = None,
        user_id: UserId | None = None,
    ) -> "Identifier":
        return cls(kind, normalise_identifier(kind, raw), source, topic_id, user_id)

    @property
    def key(self) -> tuple[IdentifierKind, str]:
        return self.kind, self.value

    @property
    def counts(self) -> bool:
        """Whether it is evidence (a rejected one only keeps training from learning it)."""
        return self.source is not IdentifierSource.REJECTED


# --- normalising ------------------------------------------------------------------------------

_IBAN = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}")
_VAT_ID = re.compile(r"[A-Z]{2,3}(?=[A-Z0-9]*\d{6})[A-Z0-9]{8,12}")
_CUSTOMER_NUMBER = re.compile(r"(?=[A-Z0-9]*\d)[A-Z0-9]{4,30}")
_PERSONNEL_NUMBER = re.compile(r"(?=[A-Z0-9]*\d)[A-Z0-9]{3,30}")
_DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
_ADDRESS = re.compile(r"[a-z0-9._%+-]+@(?:[a-z0-9-]+\.)+[a-z]{2,63}")
_TAX_ID = re.compile(r"[1-9]\d{10}")
_SOCIAL_SECURITY_NUMBER = re.compile(r"\d{4}(?:0[1-9]|1[0-2])\d{2}[A-Z]\d{3}")
_HEALTH_INSURANCE_NUMBER = re.compile(r"[A-Z]\d{9}")
_SEPARATORS = re.compile(r"[\s./-]+")

FREE_MAIL = frozenset(
    {
        *("aol.com", "arcor.de", "bluewin.ch", "freenet.de", "gmail.com", "googlemail.com"),
        *("gmx.at", "gmx.ch", "gmx.de", "gmx.net", "hotmail.com", "hotmail.de", "icloud.com"),
        *("live.com", "live.de", "mail.de", "mailbox.org", "me.com", "msn.com", "online.de"),
        *("outlook.com", "outlook.de", "posteo.de", "proton.me", "protonmail.com"),
        *("t-online.de", "web.de", "yahoo.com", "yahoo.de"),
    }
)
"""Domains of free mail providers: their addresses belong to people, not to one contact."""


def normalise_identifier(kind: IdentifierKind, raw: str) -> str:
    """The comparable form of an identifier: IBAN, VAT, customer and personnel numbers without
    spaces and separators in upper case (an IBAN with a valid check sum, a personnel number
    without leading zeros), a domain in lower case without `www.`; ValidationError if `raw` is
    none of its kind."""
    text = raw.strip()
    match kind:
        case IdentifierKind.IBAN:
            value = re.sub(r"\s+", "", text).upper()
            if not _IBAN.fullmatch(value) or not iban_valid(value):
                raise ValidationError(because(ReasonCode.NOT_IBAN, value=raw))
        case IdentifierKind.VAT_ID:
            value = _SEPARATORS.sub("", text).upper()
            if not _VAT_ID.fullmatch(value):
                raise ValidationError(because(ReasonCode.NOT_VAT_ID, value=raw))
        case IdentifierKind.CUSTOMER_NUMBER:
            value = _SEPARATORS.sub("", text).upper()
            if not _CUSTOMER_NUMBER.fullmatch(value):
                raise ValidationError(because(ReasonCode.NOT_CUSTOMER_NUMBER, value=raw))
        case IdentifierKind.PERSONNEL_NUMBER:
            # Written with or without leading zeros (`00012345`, `12345`): one number.
            written = _SEPARATORS.sub("", text).upper()
            value = written.lstrip("0")
            if not _PERSONNEL_NUMBER.fullmatch(written) or not value:
                raise ValidationError(because(ReasonCode.NOT_PERSONNEL_NUMBER, value=raw))
        case IdentifierKind.EMAIL_DOMAIN:
            value = text.lower().removeprefix("mailto:").rpartition("@")[2]
            value = re.sub(r"^(?:https?://)?(?:www\.)?", "", value).split("/")[0].rstrip(".")
            if not _DOMAIN.fullmatch(value):
                raise ValidationError(because(ReasonCode.NOT_DOMAIN, value=raw))
            if value in FREE_MAIL:
                raise ValidationError(because(ReasonCode.FREE_MAIL_DOMAIN, value=value))
        case IdentifierKind.TAX_ID:
            value = _SEPARATORS.sub("", text)
            if not tax_id_valid(value):
                raise ValidationError(because(ReasonCode.NOT_TAX_ID, value=raw))
        case IdentifierKind.SOCIAL_SECURITY_NUMBER:
            value = _SEPARATORS.sub("", text).upper()
            if not social_security_number_valid(value):
                raise ValidationError(because(ReasonCode.NOT_SOCIAL_SECURITY_NUMBER, value=raw))
        case IdentifierKind.HEALTH_INSURANCE_NUMBER:
            value = _SEPARATORS.sub("", text).upper()
            if not health_insurance_number_valid(value):
                raise ValidationError(because(ReasonCode.NOT_HEALTH_INSURANCE_NUMBER, value=raw))
        case IdentifierKind.EMAIL_ADDRESS:
            value = text.lower().removeprefix("mailto:")
            if not _ADDRESS.fullmatch(value):
                raise ValidationError(because(ReasonCode.NOT_EMAIL_ADDRESS, value=raw))
    return value


def iban_valid(iban: str) -> bool:
    """The ISO 13616 check sum (mod 97) of a compact IBAN in upper case."""
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(char, 36)) for char in rearranged)
    return int(digits) % 97 == 1


def tax_id_valid(value: str) -> bool:
    """A German tax ID: 11 digits, the first not 0; among the first ten, exactly one digit
    stands twice or three times (three not in a row), the others at most once; the last is the
    check digit (ISO 7064, MOD 11,10)."""
    if not _TAX_ID.fullmatch(value):
        return False
    first = value[:10]
    counts = Counter(first)
    repeated = [digit for digit, count in counts.items() if count > 1]
    if len(repeated) != 1 or counts[repeated[0]] > 3:
        return False
    if counts[repeated[0]] == 3 and repeated[0] * 3 in first:
        return False
    product = 10
    for digit in first:
        total = (int(digit) + product) % 10 or 10
        product = total * 2 % 11
    return (11 - product) % 10 == int(value[10])


def social_security_number_valid(value: str) -> bool:
    """A German social security (pension insurance) number in compact form: area (2 digits),
    birth date (DDMMYY), the initial of the birth name, a serial number (2 digits) and the
    check digit: the letter as its position in the alphabet (two digits), the 12 digits
    weighted 2, 1, 2, 5, 7, 1, 2, 1, 2, 1, 2, 1, the digit sums of the products added, modulo
    10."""
    if not _SOCIAL_SECURITY_NUMBER.fullmatch(value):
        return False
    digits = f"{value[:8]}{ord(value[8]) - ord('A') + 1:02d}{value[9:11]}"
    weights = (2, 1, 2, 5, 7, 1, 2, 1, 2, 1, 2, 1)
    total = sum(
        sum(divmod(int(digit) * weight, 10)) for digit, weight in zip(digits, weights, strict=True)
    )
    return total % 10 == int(value[11])


def health_insurance_number_valid(value: str) -> bool:
    """A German health insurance number (Krankenversichertennummer): a letter and nine digits,
    the last the check digit: the letter as its position in the alphabet (two digits) and the
    first eight digits, weighted 1, 2, 1, 2, …, the digit sums of the products added, modulo
    10."""
    if not _HEALTH_INSURANCE_NUMBER.fullmatch(value):
        return False
    digits = f"{ord(value[0]) - ord('A') + 1:02d}{value[1:9]}"
    total = sum(
        sum(divmod(int(digit) * (2 if position % 2 else 1), 10))
        for position, digit in enumerate(digits)
    )
    return total % 10 == int(value[9])


# --- finding in a text ------------------------------------------------------------------------

# Groups of four, the country also apart from its check digits (`DE 89 3704 …`).
_IBAN_IN_TEXT = re.compile(
    r"(?<![a-z0-9])[a-z]{2} ?\d{2}(?: ?[a-z0-9]{4}){2,7}(?: ?[a-z0-9]{1,4})?"
)
_SHORTEST_IBAN = 15  # characters (Norway)
_GERMAN_VAT = re.compile(r"(?<![a-z0-9])de ?\d{3} ?\d{3} ?\d{3}(?![a-z0-9])")
# A label, then the value: its first word, and further words that hold a digit (`DE 123 456
# 789`, `123 456`), not the words after it (`DE123456789 Steuernummer`).
_VALUE = r"\.?\s*[:.]?\s*([a-z0-9][a-z0-9./-]*(?: (?=[a-z./-]*\d)[a-z0-9./-]+)*)"
_VAT_LABEL = re.compile(
    r"(?<![a-z])(?:ust[-.\s]*id(?:[-.\s]*nr)?|umsatzsteuer[-\s]*id(?:entifikations)?[-\s]*"
    r"(?:nummer|nr)|vat[-\s]*(?:id|no|number|reg(?:istration)?(?:[-\s]*no)?)?"
    r"|uid[-\s]*(?:nr|nummer)?)" + _VALUE
)
# Not the social security number ("Sozialversicherungsnummer", "Rentenversicherungsnummer"):
# that is a person's.
_CUSTOMER_LABEL = re.compile(
    r"(?:kunden[-\s]*(?:nummer|nr|konto)|kd[-.\s]*nr|kundennr|vertrags[-\s]*(?:nummer|nr|konto)"
    r"|(?<!sozial)(?<!sozial-)(?<!renten)(?<!renten-)"
    r"versicherungs[-\s]*(?:nummer|nr|schein[-\s]*(?:nummer|nr))|mitglieds[-\s]*(?:nummer|nr)"
    r"|customer[-\s]*(?:no|number|id)|account[-\s]*(?:no|number))" + _VALUE
)
_PERSONNEL_LABEL = re.compile(
    r"(?<![a-z])(?:personal[-\s]*(?:nummer|nr)|pers[-.\s]*nr|mitarbeiter[-\s]*(?:nummer|nr)"
    r"|employee[-\s]*(?:no|number|id)|personnel[-\s]*(?:no|number))" + _VALUE
)
_EMAIL = re.compile(r"[a-z0-9._%+-]+@((?:[a-z0-9-]+\.)+[a-z]{2,63})")
_TAX_ID_LABEL = re.compile(
    r"(?<![a-z])(?:steuer[-\s]*id(?:entifikations)?(?:[-\s]*(?:nummer|nr))?"
    r"|steuerliche[-\s]*identifikations[-\s]*(?:nummer|nr)|identifikations[-\s]*(?:nummer|nr)"
    r"|id[-.\s]*nr|tin)\.?(?:\s*\([a-z.\s-]{1,20}\))?\s*[:.]?\s*"
    r"(\d{2} ?\d{3} ?\d{3} ?\d{3}|\d{11})(?!\d)"
)
_GROUPED_TAX_ID = re.compile(r"(?<![\d.,/-])\d{2} \d{3} \d{3} \d{3}(?![\d.,/-]?\d)")
_SOCIAL_SECURITY_IN_TEXT = re.compile(
    r"(?<![a-z0-9])\d{2} ?\d{2} ?\d{2} ?\d{2} ?[a-z] ?\d{2} ?\d(?![a-z0-9])"
)
_HEALTH_INSURANCE_LABEL = re.compile(
    r"(?<![a-z])(?:(?:kranken)?versicherten[-\s]*(?:nummer|nr|id)"
    r"|kranken[-\s]*versicherungs[-\s]*(?:nummer|nr)|kvnr)\.?\s*[:.]?\s*"
    r"([a-z] ?\d(?: ?\d){8})(?![a-z0-9])"
)
_PERSONAL_KINDS = frozenset(PERSON_KINDS - CONTACT_KINDS)
_WEB = re.compile(r"(?<![a-z0-9@.-])(?:https?://(?:www\.)?|www\.)((?:[a-z0-9-]+\.)+[a-z]{2,63})")


def identifiers_in(text: str) -> set[tuple[IdentifierKind, str]]:
    """The identifiers `text` shows, normalised: IBANs and German VAT numbers anywhere, other
    VAT numbers, customer and personnel numbers after their label ("USt-IdNr.", "Kundennummer",
    "Vertragsnummer", "Personalnummer", ...), the domains of e-mail and web addresses (free
    mail aside) and the addresses themselves; a person's numbers with a valid check digit: the
    tax ID after its label ("Steuer-ID", "IdNr.") or in its groups (`12 345 678 901`), the social
    security number anywhere, the health insurance number after its label
    ("Versichertennummer", "Krankenversicherungsnummer"). A customer or personnel number that
    is one of the person's numbers found, stands in one or overlaps it is theirs only (a pension
    fund writes "Versicherungsnummer" before the social security number, `65 170839 J 003`)."""
    normalised = normalise(text)
    found: set[tuple[IdentifierKind, str]] = set()
    naming: list[tuple[tuple[IdentifierKind, str], tuple[int, int]]] = []
    personal_spans: list[tuple[int, int]] = []

    def add(kind: IdentifierKind, raw: str, span: tuple[int, int] | None = None) -> None:
        with suppress(ValidationError):
            key = (kind, normalise_identifier(kind, raw))
            if kind in NAMING_KINDS and span is not None:
                naming.append((key, span))
                return
            found.add(key)
            if kind in _PERSONAL_KINDS and span is not None:
                personal_spans.append(span)

    for match in _IBAN_IN_TEXT.finditer(normalised):
        # The groups may run into what follows (`DE89 3704 … 3000 Sparkasse`): the longest
        # start with a valid check sum is the IBAN.
        compact = match.group().replace(" ", "")
        for end in range(len(compact), _SHORTEST_IBAN - 1, -1):
            if iban_valid(compact[:end].upper()):
                add(IdentifierKind.IBAN, compact[:end])
                break
    for match in _GERMAN_VAT.finditer(normalised):
        add(IdentifierKind.VAT_ID, match.group())
    for match in _VAT_LABEL.finditer(normalised):
        add(IdentifierKind.VAT_ID, match.group(1))
    for match in _CUSTOMER_LABEL.finditer(normalised):
        add(IdentifierKind.CUSTOMER_NUMBER, match.group(1), match.span(1))
    for match in _PERSONNEL_LABEL.finditer(normalised):
        add(IdentifierKind.PERSONNEL_NUMBER, match.group(1), match.span(1))
    for pattern in (_EMAIL, _WEB):
        for match in pattern.finditer(normalised):
            add(IdentifierKind.EMAIL_DOMAIN, match.group(1))
    for match in _EMAIL.finditer(normalised):
        add(IdentifierKind.EMAIL_ADDRESS, match.group())
    for match in _TAX_ID_LABEL.finditer(normalised):
        add(IdentifierKind.TAX_ID, match.group(1), match.span(1))
    for match in _GROUPED_TAX_ID.finditer(normalised):
        add(IdentifierKind.TAX_ID, match.group(), match.span())
    for match in _SOCIAL_SECURITY_IN_TEXT.finditer(normalised):
        add(IdentifierKind.SOCIAL_SECURITY_NUMBER, match.group(), match.span())
    for match in _HEALTH_INSURANCE_LABEL.finditer(normalised):
        add(IdentifierKind.HEALTH_INSURANCE_NUMBER, match.group(1), match.span(1))
    personal = [key for key in found if key[0] in _PERSONAL_KINDS]
    for key, (start, end) in naming:
        overlaps = any(
            start < theirs_end and theirs_start < end for theirs_start, theirs_end in personal_spans
        )
        if not overlaps and not of_person(key, personal):
            found.add(key)
    return found


_CONTAINED = 6
"""Characters a customer or personnel number has at least to count as part of a person's number
it stands in."""


def of_person(
    key: tuple[IdentifierKind, str], personal: Iterable[tuple[IdentifierKind, str]]
) -> bool:
    """Whether an identifier is one of a person's values `personal`: the same, or a customer or
    personnel number with the value of one of them (of any kind: the IBAN as an "account
    number"), or one that stands in a tax ID, social security or health insurance number (a
    pension fund's "Versicherungsnummer" is the start of the social security number)."""
    kind, value = key
    for theirs in personal:
        if theirs == key:
            return True
        if kind not in NAMING_KINDS:
            continue
        their_kind, their_value = theirs
        compact = re.sub(r"[^A-Z0-9]", "", their_value.upper())
        if value == compact:
            return True
        if their_kind in _PERSONAL_KINDS and len(value) >= _CONTAINED and value in compact:
            return True
    return False


def matches(identifier: Identifier, found: tuple[IdentifierKind, str]) -> bool:
    """Whether a found value is the identifier; a domain also stands for its subdomains
    (`service.stadtwerke.de` for `stadtwerke.de`)."""
    kind, value = found
    if kind is not identifier.kind:
        return False
    if kind is IdentifierKind.EMAIL_DOMAIN:
        return value == identifier.value or value.endswith("." + identifier.value)
    return value == identifier.value


# --- learning ---------------------------------------------------------------------------------


def mine_identifiers(
    documents: Iterable[
        tuple[ContactId | None, TagId | None, Iterable[tuple[IdentifierKind, str]]]
    ],
    taken: Iterable[tuple[IdentifierKind, str]] = (),
    personal: Iterable[tuple[IdentifierKind, str]] = (),
) -> Mapping[ContactId, list[Identifier]]:
    """The identifiers to learn from confirmed documents (each its contact, its topic and the
    identifiers in its text): a value that stands in at least `LEARN_FROM` documents, all with
    the same contact. A document without a contact counts as another contact. `taken` (entered
    by hand or rejected anywhere) is never learned, nor what is one of the persons' values
    `personal` (`of_person`: also a customer number that stands in a social security number).
    A learned value points to a topic if all its documents carry that one; otherwise to none.
    Only the kinds of contacts are learned (`CONTACT_KINDS`): a person's numbers never become a
    contact's."""
    holders: dict[tuple[IdentifierKind, str], list[tuple[ContactId | None, TagId | None]]] = (
        defaultdict(list)
    )
    for contact, topic, found in documents:
        for key in set(found):
            holders[key].append((contact, topic))
    skip = set(taken)
    persons = list(personal)
    learned: dict[ContactId, list[Identifier]] = defaultdict(list)
    for (kind, value), pairs in sorted(holders.items()):
        owners = {contact for contact, _ in pairs}
        if (
            kind not in CONTACT_KINDS
            or (kind, value) in skip
            or of_person((kind, value), persons)
            or len(pairs) < LEARN_FROM
            or len(owners) != 1
        ):
            continue
        (owner,) = owners
        topics = {topic for _, topic in pairs}
        topic = next(iter(topics)) if len(topics) == 1 else None
        if owner is not None:
            learned[owner].append(Identifier(kind, value, IdentifierSource.LEARNED, topic))
    return {owner: found[:MAX_IDENTIFIERS] for owner, found in learned.items()}
