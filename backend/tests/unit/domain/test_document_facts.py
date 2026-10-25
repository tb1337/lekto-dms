"""Facts as values of a document: found in the text and the codes, with role and origin."""

from dataclasses import replace

import pytest

from lekto.core.domain.document_facts import (
    ROLES,
    DocumentFact,
    FactOrigin,
    FactRole,
    FactState,
    found_facts,
    merged,
)
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.identifiers import IdentifierKind, identifiers_in, places_in

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
