"""Facts as values of a document: found in the text and the codes, with role and origin."""

from dataclasses import replace

import pytest

from lekto.core.domain.document_facts import (
    ROLES,
    DocumentFact,
    FactCriterion,
    FactOrigin,
    FactRole,
    FactState,
    ReadFact,
    checked_read,
    fact_tokens,
    found_facts,
    merged,
    with_read,
)
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers import IdentifierKind, identifiers_in, places_in, referred_in
from lekto.core.domain.reasons import Reason, ReasonCode

IBAN = (IdentifierKind.IBAN, "DE02120300000000202051")
VAT = (IdentifierKind.VAT_ID, "DE312456789")
TEXT = "USt-IdNr. DE 312 456 789\nBitte überweisen Sie auf DE02 1203 0000 0000 2020 51."


def test_every_kind_has_a_role() -> None:
    assert set(ROLES) == set(IdentifierKind)
    assert ROLES[IdentifierKind.TAX_ID] is FactRole.PERSON
    assert ROLES[IdentifierKind.CUSTOMER_NUMBER] is FactRole.CONTACT


def test_facts_are_found_as_the_text_reads_with_where_they_come_from() -> None:
    assert identifiers_in(TEXT) == {IBAN, VAT}
    coded = (IdentifierKind.IBAN, "DE89370400440532013000")
    vat, iban, code = found_facts(TEXT, {IBAN, VAT}, {IBAN, coded})

    assert (vat.key, vat.role, vat.origins) == (
        VAT,
        FactRole.CONTACT,
        frozenset({FactOrigin.PATTERN}),
    )
    assert (vat.written, vat.position) == ("DE 312 456 789", TEXT.index("DE 312"))
    assert iban.origins == {FactOrigin.PATTERN, FactOrigin.CODE}
    assert iban.written == "DE02 1203 0000 0000 2020 51"
    # Only in a code: no place in the text, last.
    assert (code.key, code.origins, code.written, code.position) == (
        coded,
        frozenset({FactOrigin.CODE}),
        None,
        None,
    )
    assert all(fact.state is FactState.FOUND for fact in (vat, iban, code))


@pytest.mark.parametrize(
    ("text", "written"),
    [
        ("IBAN DE02 1203  0000 0000 2020 51", "DE02 1203  0000 0000 2020 51"),
        ("IBAN DE02 1203 0000\n    0000 2020 51", "DE02 1203 0000\n    0000 2020 51"),
        ("IBAN DE02 1203 0000 0000 20\u00ad20 51", "DE02 1203 0000 0000 20\u00ad20 51"),
    ],
)
def test_a_fact_stands_where_the_text_writes_it_with_its_separators(
    text: str, written: str
) -> None:
    """Two spaces, a line break with its indent, a soft hyphen: as an OCR text writes it."""
    (fact,) = found_facts(text, identifiers_in(text), (), places_in(text))
    assert (fact.position, fact.written) == (text.index("DE02"), written)


def test_a_fact_stands_where_its_reader_took_it() -> None:
    """After its label, not at a postcode of the same digits before it."""
    text = "12345 Berlin\nPersonalnummer: 00012345"
    (fact,) = found_facts(text, identifiers_in(text), (), places_in(text))
    assert (fact.position, fact.written) == (text.index("00012345"), "00012345")


def test_a_person_s_decision_outlasts_what_is_found_again() -> None:
    vat, iban = found_facts(TEXT, {IBAN, VAT})
    rejected = replace(vat, state=FactState.REJECTED)
    corrected = replace(iban, value="DE89370400440532013000", state=FactState.CORRECTED)
    other = replace(vat, kind=IdentifierKind.CUSTOMER_NUMBER, value="4711", position=None)

    after = merged([rejected, corrected, iban], [vat, iban, other])

    # The person's two stay, the IBAN found again (another value) comes in again.
    assert after == [rejected, iban, corrected, other]
    assert merged([vat], [iban]) == [iban]  # what was found before goes


@pytest.mark.parametrize(
    "change",
    [{"value": ""}, {"origins": frozenset()}, {"position": -1}],
)
def test_a_fact_is_checked(change: dict[str, object]) -> None:
    fields: dict[str, object] = {
        "kind": IdentifierKind.IBAN,
        "value": "DE02120300000000202051",
        "role": FactRole.CONTACT,
        "origins": frozenset({FactOrigin.PATTERN}),
        "position": 0,
    }
    with pytest.raises(ValidationError):
        DocumentFact(**(fields | change))  # type: ignore[arg-type]


def test_what_is_written_is_kept_short() -> None:
    fact = DocumentFact(
        kind=IdentifierKind.EMAIL_DOMAIN,
        value="example.org",
        role=FactRole.CONTACT,
        origins=frozenset({FactOrigin.PATTERN}),
        written="x" * 500,
    )
    assert fact.written == "x" * 200


# --- facts the language model reads ------------------------------------------------------------

REMINDER = "Mahnung\nIhre Rechnung Nr. 4711 vom 04.06.2026 ist noch offen.\nKundennummer 20047718"
ASKED = frozenset(IdentifierKind) - {IdentifierKind.VAT_ID, IdentifierKind.TAX_ID}
ROLES_ASKED = frozenset(FactRole) - {FactRole.PERSON}


def check(
    text: str, given: ReadFact, personal: frozenset[tuple[IdentifierKind, str]] = frozenset()
) -> DocumentFact | Reason:
    return checked_read(text, given, kinds=ASKED, roles=ROLES_ASKED, personal=personal)


def read(kind: str, value: str, role: str, evidence: str | None = None) -> ReadFact:
    return ReadFact(kind=kind, value=value, role=role, evidence=evidence)


def test_a_fact_the_model_read_is_checked_as_a_field_s_value() -> None:
    fact = check(REMINDER, read("invoice_number", "4711", "refers", "Rechnung Nr. 4711"))
    assert isinstance(fact, DocumentFact)
    assert (fact.key, fact.role, fact.origins) == (
        (IdentifierKind.INVOICE_NUMBER, "4711"),
        FactRole.REFERS,
        frozenset({FactOrigin.MODEL}),
    )
    assert (fact.written, fact.position) == ("4711", REMINDER.index("4711"))


@pytest.mark.parametrize(
    ("given", "code"),
    [
        (read("shoe_size", "42", "own", "42"), ReasonCode.FACT_KIND_UNKNOWN),
        (read("invoice_number", "4711", "boss", "Nr. 4711"), ReasonCode.FACT_KIND_UNKNOWN),
        # What it was not asked for: a person's kind, its role, a kind the patterns read surely.
        (read("tax_id", "86095742001", "person", "86095742001"), ReasonCode.FACT_NOT_ASKED),
        (read("invoice_number", "4711", "person", "Nr. 4711"), ReasonCode.FACT_NOT_ASKED),
        (read("vat_id", "DE312456789", "contact", "DE312456789"), ReasonCode.FACT_NOT_ASKED),
        (read("creditor_id", "DE00ZZZ09999999999", "contact", "x"), ReasonCode.NOT_OF_KIND),
        (read("invoice_number", "4712", "refers", "Nr. 4712"), ReasonCode.FACT_NOT_IN_TEXT),
        (read("invoice_number", "4711", "refers"), ReasonCode.QUOTE_MISSING),
        (read("invoice_number", "4711", "refers", "Rechnung 4711"), ReasonCode.QUOTE_NOT_IN_TEXT),
        (
            read("invoice_number", "4711", "refers", "ist noch offen"),
            ReasonCode.QUOTE_WITHOUT_VALUE,
        ),
    ],
)
def test_what_the_model_read_wrong_is_refused(given: ReadFact, code: ReasonCode) -> None:
    refused = check(REMINDER, given)
    assert isinstance(refused, Reason)
    assert refused.code is code


def test_the_model_decides_the_role_of_what_the_patterns_found() -> None:
    """An invoice that names its own number "Ihre Rechnung Nr.": the patterns take it for a
    reference, the model for its own; a number only the model read comes in."""
    text = "Ihre Rechnung Nr. 4711\nVertrag 55-66-77"
    found = found_facts(text, identifiers_in(text), (), places_in(text), referred_in(text))
    assert [fact.role for fact in found] == [FactRole.REFERS]
    own = check(text, read("invoice_number", "4711", "own", "Ihre Rechnung Nr. 4711"))
    contract = check(text, read("contract_number", "55-66-77", "target", "Vertrag 55-66-77"))
    assert isinstance(own, DocumentFact) and isinstance(contract, DocumentFact)
    invoice, other = with_read(found, [own, contract])
    assert (invoice.role, invoice.origins) == (
        FactRole.OWN,
        frozenset({FactOrigin.PATTERN, FactOrigin.MODEL}),
    )
    assert (other.key, other.origins) == (
        (IdentifierKind.CONTRACT_NUMBER, "556677"),
        frozenset({FactOrigin.MODEL}),
    )


def test_a_person_s_number_never_comes_in_under_another_kind() -> None:
    """The tax ID the patterns found, or a user's number, given as a customer number."""
    text = "Steuer-ID 86 095 742 001\nKundennummer 86095742001\nMitglied 123FK456789"
    tax = (IdentifierKind.TAX_ID, "86095742001")
    child = (IdentifierKind.CHILD_BENEFIT_NUMBER, "123FK456789")
    refused = check(
        text,
        read("customer_number", "86095742001", "contact", "Kundennummer 86095742001"),
        frozenset({tax}),
    )
    assert isinstance(refused, Reason) and refused.code is ReasonCode.FACT_OF_A_PERSON
    member = check(
        text,
        read("membership_number", "123FK456789", "target", "Mitglied 123FK456789"),
        frozenset({child}),
    )
    assert isinstance(member, Reason) and member.code is ReasonCode.FACT_OF_A_PERSON


def test_the_day_of_a_letter_needs_its_letter() -> None:
    text = "Musterstadt, 20.06.2026\nIhr Schreiben vom 18.06.2026"
    dated = check(text, read("letter_date", "2026-06-20", "refers", "Musterstadt, 20.06.2026"))
    assert isinstance(dated, Reason) and dated.code is ReasonCode.QUOTE_WITHOUT_VALUE
    letter = check(
        text, read("letter_date", "2026-06-18", "refers", "Ihr Schreiben vom 18.06.2026")
    )
    assert isinstance(letter, DocumentFact)
    week = check(text, read("letter_date", "2026-W25-4", "refers", "Ihr Schreiben vom 18.06.2026"))
    assert isinstance(week, Reason)


def test_a_criterion_finds_a_fact_by_its_parts() -> None:
    fact = DocumentFact(
        kind=IdentifierKind.INVOICE_NUMBER,
        value="R20260815",
        role=FactRole.OWN,
        origins=frozenset({FactOrigin.PATTERN}),
    )
    tokens = fact_tokens([fact])
    kind = IdentifierKind.INVOICE_NUMBER
    for criterion in (
        FactCriterion.written(kind, "R-2026-0815", FactRole.OWN),
        FactCriterion.written(kind, "r 2026 0815", None),
        FactCriterion(kind, role=FactRole.OWN),
        FactCriterion(kind),
        FactCriterion(role=FactRole.OWN),
    ):
        assert criterion.token in tokens
    assert FactCriterion(role=FactRole.REFERS).token not in tokens
    assert fact_tokens([replace(fact, state=FactState.REJECTED)]) == frozenset()
    for wrong in ({}, {"value": "4711"}):
        with pytest.raises(ValidationError):
            FactCriterion(**wrong)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        FactCriterion.written(IdentifierKind.CREDITOR_ID, "DE00", None)
