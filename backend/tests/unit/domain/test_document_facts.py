"""Facts as values of a document: found in the text and the codes, with role and origin."""

from dataclasses import replace

import pytest

from lekto.core.domain.document_facts import (
    ROLES,
    DocumentFact,
    FactOrigin,
    FactRole,
    FactState,
    ReadFact,
    checked_read,
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


def read(kind: str, value: str, role: str, evidence: str | None = None) -> ReadFact:
    return ReadFact(kind=kind, value=value, role=role, evidence=evidence)


def test_a_fact_the_model_read_is_checked_as_a_field_s_value() -> None:
    fact = checked_read(REMINDER, read("invoice_number", "4711", "refers", "Rechnung Nr. 4711"))
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
        # A person's numbers are no reader's to give.
        (read("tax_id", "86095742001", "person", "86095742001"), ReasonCode.FACT_KIND_UNKNOWN),
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
    refused = checked_read(REMINDER, given)
    assert isinstance(refused, Reason)
    assert refused.code is code


def test_the_model_decides_the_role_of_what_the_patterns_found() -> None:
    """An invoice that names its own number "Ihre Rechnung Nr.": the patterns take it for a
    reference, the model for its own; a number only the model read comes in."""
    text = "Ihre Rechnung Nr. 4711\nVertrag 55-66-77"
    found = found_facts(text, identifiers_in(text), (), places_in(text), referred_in(text))
    assert [fact.role for fact in found] == [FactRole.REFERS]
    own = checked_read(text, read("invoice_number", "4711", "own", "Ihre Rechnung Nr. 4711"))
    contract = checked_read(text, read("contract_number", "55-66-77", "target", "Vertrag 55-66-77"))
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
