"""Facts in rules (#145 PR 8): the condition "fact" (kind, role; `is`, `in`, `matches`,
`present`, `missing`) and what templates see of the facts (`facts`, `fact_list`)."""

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from lekto.core.domain.codes import Code
from lekto.core.domain.document_facts import DocumentFact, FactOrigin, FactRole, FactState
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import Money
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import DocumentTypeId, new_id
from lekto.core.domain.locations import Box
from lekto.core.domain.rule_conditions import Facts, evaluate, pattern_subjects
from lekto.core.domain.rules import AddTags, Condition, ConditionField, Operator, SetTitle
from lekto.core.domain.rules_json import condition_from_json, condition_to_json
from lekto.core.domain.templates import facts_values, unknown_values
from tests.unit.domain.rules_support import PAID, all_, doc, rule

K = IdentifierKind


def fact(
    kind: IdentifierKind,
    value: str,
    role: FactRole,
    *,
    written: str | None = None,
    position: int | None = 0,
    origins: frozenset[FactOrigin] = frozenset({FactOrigin.PATTERN}),
    state: FactState = FactState.FOUND,
) -> DocumentFact:
    return DocumentFact(
        kind=kind,
        value=value,
        role=role,
        origins=origins,
        written=written,
        position=position,
        state=state,
    )


REMINDER = (
    fact(K.INVOICE_NUMBER, "M77", FactRole.OWN, written="M-77", position=10),
    fact(K.INVOICE_NUMBER, "4711", FactRole.REFERS, written="4711", position=40),
    fact(K.INVOICE_NUMBER, "4712", FactRole.REFERS, written="4712", position=60),
    fact(K.CUSTOMER_NUMBER, "887766", FactRole.CONTACT, state=FactState.REJECTED),
    fact(K.TAX_ID, "86095742001", FactRole.PERSON, position=80),
)


def on(condition: Condition, kept: tuple[DocumentFact, ...] = REMINDER) -> bool | None:
    facts = Facts.of(doc(), kept_facts=kept)
    return evaluate(all_(condition), facts, {})


def fact_cond(
    op: Operator, value: object = None, role: FactRole | None = None, kind: K = K.INVOICE_NUMBER
) -> Condition:
    return Condition(
        field=ConditionField.FACT,
        op=op,
        value=value,  # type: ignore[arg-type]
        fact_kind=kind,
        fact_role=role,
    )


def test_a_fact_condition_looks_at_the_kind_and_role() -> None:
    assert on(fact_cond(Operator.PRESENT, role=FactRole.REFERS))
    assert on(fact_cond(Operator.MISSING, role=FactRole.THREAD))
    assert on(fact_cond(Operator.IS, "M-77"))  # as written, compared as Lekto compares
    assert not on(fact_cond(Operator.IS, "M-77", FactRole.REFERS))
    assert on(fact_cond(Operator.IN, ["9999", "47 11"], FactRole.REFERS))
    # A fact a person rejected does not count.
    assert on(fact_cond(Operator.MISSING, kind=K.CUSTOMER_NUMBER))


def test_a_fact_condition_is_checked_and_kept() -> None:
    for wrong in (
        {"field": ConditionField.FACT, "op": Operator.PRESENT},
        {"field": ConditionField.TEXT, "op": Operator.PRESENT, "fact_kind": K.INVOICE_NUMBER},
        {"field": ConditionField.FACT, "op": Operator.CONTAINS, "fact_kind": K.INVOICE_NUMBER},
        {
            "field": ConditionField.FACT,
            "op": Operator.IS,
            "value": "DE00",
            "fact_kind": K.CREDITOR_ID,
        },
    ):
        with pytest.raises(ValidationError):
            Condition(**wrong)
    kept = fact_cond(Operator.IS, "M-77", FactRole.OWN)
    assert kept.value == "M77"
    assert condition_from_json(condition_to_json(kept)) == kept
    assert condition_to_json(kept) == {
        "field": "fact",
        "op": "is",
        "value": "M77",
        "fact_kind": "invoice_number",
        "fact_role": "own",
    }


def test_a_fact_pattern_runs_against_each_value_as_written() -> None:
    matches = fact_cond(Operator.MATCHES, "^47", FactRole.REFERS)
    subjects = pattern_subjects(
        [rule(AddTags(frozenset({PAID})), when=all_(matches))], doc(), None, REMINDER
    )
    # Each on its own: a pattern does not run across two values.
    assert subjects == {("fact:invoice_number:refers", "^47", False): ("4711", "4712")}
    wrapped = fact(K.INVOICE_NUMBER, "RE20260042", FactRole.OWN, written="RE-2026/\n00\u00ad42")
    across = fact_cond(Operator.MATCHES, "^RE")
    assert pattern_subjects(
        [rule(AddTags(frozenset({PAID})), when=all_(across))], doc(), None, (wrapped,)
    ) == {("fact:invoice_number:", "^RE", False): ("RE-2026/ 0042",)}
    facts = Facts.of(
        doc(),
        kept_facts=REMINDER,
        patterns={("fact:invoice_number:refers", "^47", False): True},
    )
    assert evaluate(all_(matches), facts, {})


def test_templates_see_the_facts() -> None:
    giro = Code(
        page=1,
        format="QR Code",
        text="BCD\n002\n1\nSCT\n\nStadtwerke\nDE89370400440532013000\nEUR84.20\n\n\nStrom März",
        box=Box(0.1, 0.1, 0.1, 0.1),
    )
    values = facts_values(REMINDER, [giro])
    assert values["facts"] == {
        "invoice_number": "M-77",
        "refers": {"invoice_number": "4711"},
        "girocode": {
            "name": "Stadtwerke",
            "iban": "DE89370400440532013000",
            "amount": Money(Decimal("84.20"), "EUR"),
            "purpose": "Strom März",
        },
    }
    listed: Any = values["fact_list"]
    assert isinstance(listed, list)
    # Not the rejected one, not a person's number.
    assert [item["value"] for item in listed] == ["M77", "4711", "4712"]
    assert listed[0] == {
        "kind": "invoice_number",
        "value": "M77",
        "written": "M-77",
        "role": "own",
        "origin": "pattern",
    }
    # On one line, a soft hyphen gone; a number a person marked as a person's is left out.
    wrapped = fact(K.INVOICE_NUMBER, "RE20260042", FactRole.OWN, written="RE-2026/\n00\u00ad42")
    private = fact(K.IBAN, "DE89370400440532013000", FactRole.PERSON, written="DE89 3704")
    assert facts_values([wrapped, private])["facts"] == {"invoice_number": "RE-2026/ 0042"}
    corrected = replace(REMINDER[0], origins=frozenset({FactOrigin.PATTERN, FactOrigin.PERSON}))
    origins: Any = facts_values([corrected])["fact_list"]
    assert origins[0]["origin"] == "person"
    assert facts_values([]) == {"facts": None, "fact_list": None}


def test_a_template_names_facts_a_document_can_have() -> None:
    paths = [
        "facts.invoice_number",
        "facts.refers.invoice_number",
        "facts.girocode.amount.currency",
        "facts.girocode.iban",
        "facts",
        "facts.invoice_numbr",
        "facts.tax_id",  # a person's alone: templates never see it
        "facts.girocode.amout",
        "facts.invoice_number.x",
    ]
    assert unknown_values(paths, set()) == [
        "facts.girocode.amout",
        "facts.invoice_number.x",
        "facts.invoice_numbr",
        "facts.tax_id",
    ]


def test_only_a_template_on_facts_or_an_ask_needs_the_codes() -> None:
    present = fact_cond(Operator.PRESENT)
    assert not rule(AddTags(frozenset({PAID})), when=all_(present)).definition.uses_codes
    giro = SetTitle(template="Zahlung {{ facts.girocode.amount }}")
    assert rule(giro).definition.uses_codes


def test_a_relation_condition_looks_at_the_types_it_refers_to() -> None:
    invoice, contract = DocumentTypeId(new_id()), DocumentTypeId(new_id())

    def holds(
        op: Operator,
        value: object = None,
        referred: tuple[DocumentTypeId | None, ...] = (invoice, None),
    ) -> bool:
        condition = Condition(field=ConditionField.RELATION, op=op, value=value)  # type: ignore[arg-type]
        facts = Facts.of(doc(), referred_types=referred)
        return bool(evaluate(all_(condition), facts, {}))

    assert holds(Operator.PRESENT)
    assert holds(Operator.MISSING, referred=())
    assert holds(Operator.IS, str(invoice))
    assert not holds(Operator.IN, [str(contract)])
    with pytest.raises(ValidationError):
        Condition(field=ConditionField.RELATION, op=Operator.IS, value="Rechnung")
    kept = Condition(field=ConditionField.RELATION, op=Operator.IN, value=[str(invoice)])
    assert condition_from_json(condition_to_json(kept)) == kept
    rule_ = rule(AddTags(frozenset({PAID})), when=all_(kept))
    assert rule_.definition.references().document_types == frozenset({invoice})
