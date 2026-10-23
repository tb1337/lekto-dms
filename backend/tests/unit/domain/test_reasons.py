"""Reasons with codes (issue #83): every code has its English template, parameters must fit it,
and what was stored without codes reads as written."""

import pytest

from lekto.core.domain.classification import FieldCheck
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.pipeline import Outcome
from lekto.core.domain.reasons import (
    KINDS,
    TEMPLATES,
    Reason,
    ReasonCode,
    because,
    catalog,
    reasons_from_json,
    text_of,
    written,
)


def test_every_code_has_a_template_and_the_catalog_lists_it() -> None:
    assert set(TEMPLATES) == set(ReasonCode)
    listed = catalog()
    assert set(listed) == {code.value for code in ReasonCode}
    assert listed["contact_not_in_text"] == {"contact": "text"}
    assert listed["signals_disagree"] == {"names": "names"}
    assert listed["page_poorly_read"] == {"page": "number", "share": "percent"}
    assert {kind for params in listed.values() for kind in params.values()} <= set(KINDS.values())


def test_the_parameters_must_fit_the_template() -> None:
    with pytest.raises(ValidationError, match="expected \\['contact'\\]"):
        because(ReasonCode.CONTACT_NOT_IN_TEXT)
    with pytest.raises(ValidationError, match="parameters \\['extra'\\]"):
        because(ReasonCode.CONTACT_NONE, extra="x")


def test_the_english_text_writes_each_kind() -> None:
    assert because(ReasonCode.SIGNALS_DISAGREE, names=["A", "B"]).text == (
        "the signals disagree: 'A' or 'B'"
    )
    assert because(ReasonCode.PAGE_POORLY_READ, page=2, share=0.1834).text == (
        "page 2 was poorly read (18% of its words unsure)"
    )
    assert because(ReasonCode.DATE_IMPLAUSIBLE, date="1899-12-31").text == (
        "1899-12-31 is not plausible"
    )
    values: list[JsonValue] = [{"rule": "Paid", "value": True}, {"rule": "Open", "value": None}]
    assert because(ReasonCode.RULES_DISAGREE, values=values).text == (
        "rules set different values ('Paid': yes, 'Open': none)"
    )
    assert because(
        ReasonCode.SPACE_WIDENS_NEEDS_CONFIRMED, space="Family", fields=["contact"]
    ).text == (
        "files into the space 'Family', which more people see, only with a confirmed contact"
    )


def test_a_reason_names_the_field_it_is_about_and_the_rule_it_comes_from() -> None:
    reason = because(ReasonCode.AMOUNT_NOT_IN_TEXT).about("Amount")
    assert reason.text == "'Amount': the amount does not appear in the text"
    assert written("look at it").by_rule("Check").text == "rule 'Check': look at it"
    assert text_of([reason, because(ReasonCode.QUOTE_MISSING)]) == (
        "'Amount': the amount does not appear in the text; no quoted passage"
    )
    assert text_of([]) is None


def test_a_reason_survives_json() -> None:
    reason = because(ReasonCode.SENDER_ONLY_SIMILAR, sender="Stadtwerk", contact="Stadtwerke")
    for item in (reason, reason.about("Amount"), written("x").by_rule("R")):
        assert Reason.from_json(item.to_json()) == item
    assert reason.to_json() == {
        "code": "sender_only_similar",
        "params": {"sender": "Stadtwerk", "contact": "Stadtwerke"},
    }


def test_reasons_without_codes_or_of_a_newer_version_read_as_written() -> None:
    assert reasons_from_json(None, "old text") == (written("old text"),)
    assert reasons_from_json([{"code": "from_the_future", "params": {}}], "new text") == (
        written("new text"),
    )
    assert reasons_from_json(None, None) == ()
    with pytest.raises(ValidationError, match="unknown reason code"):
        Reason.from_json({"code": "from_the_future", "params": {}})


def test_a_field_check_stores_its_reasons_beside_the_english_text() -> None:
    check = FieldCheck(
        field="contact",
        outcome=Outcome.UNCERTAIN,
        confidence=0.5,
        reasons=(because(ReasonCode.CONTACT_NOT_IN_TEXT, contact="Stadtwerke"),),
    )
    stored = check.to_json()
    assert stored["reason"] == "the contact 'Stadtwerke' does not appear in the text"
    assert stored["reasons"] == [
        {"code": "contact_not_in_text", "params": {"contact": "Stadtwerke"}}
    ]
    assert FieldCheck.from_json(stored) == check
    # A check stored before reasons had codes keeps its text.
    old = FieldCheck.from_json({**stored, "reasons": None, "reason": "'X' is similar"})
    assert old.reasons == (written("'X' is similar"),) and old.reason == "'X' is similar"
