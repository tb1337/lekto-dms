from datetime import date
from decimal import Decimal

import pytest

from lekto.core.domain.documents import Channel
from lekto.core.domain.evidence import DocumentText
from lekto.core.domain.fields import FieldDefinition, Money, Url
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.periods import Period
from lekto.core.domain.rule_conditions import (
    Facts,
    Match,
    Truth,
    evaluate,
    matches,
    pattern_subjects,
    pattern_text,
)
from lekto.core.domain.rule_planner import plan
from lekto.core.domain.rules import (
    AddTags,
    Condition,
    ConditionField,
    ForceReview,
    Group,
    Operator,
    SetSpace,
)
from tests.unit.domain.rules_support import (
    ACME,
    AMOUNT,
    BETA,
    COUNT,
    DEFINITIONS,
    DUE,
    FROM_ACME,
    INTERVAL,
    INVOICE,
    IS_API,
    IS_WEB,
    OPEN,
    PAID,
    PAID_FLAG,
    PORTAL,
    REFERENCE,
    SHARED,
    SPAN,
    URGENT,
    all_,
    any_,
    cond,
    doc,
    notes,
    rule,
    situation,
    tagged,
    topics,
)

# --- evaluation -------------------------------------------------------------------------------


UNKNOWN_CONTACT = cond(ConditionField.CONTACT, Operator.IS, str(ACME))


@pytest.mark.parametrize(
    ("group", "trusting", "distrusting"),
    [
        (all_(UNKNOWN_CONTACT), True, None),
        (all_(UNKNOWN_CONTACT, IS_API), True, None),
        (all_(UNKNOWN_CONTACT, IS_WEB), False, False),  # unknown and false is false
        (any_(UNKNOWN_CONTACT, IS_API), True, True),  # unknown or true is true
        (any_(UNKNOWN_CONTACT, IS_WEB), True, None),
        (all_(UNKNOWN_CONTACT, negate=True), False, None),  # not unknown is unknown
        (any_(UNKNOWN_CONTACT, IS_WEB, negate=True), False, None),
        (all_(UNKNOWN_CONTACT, IS_WEB, negate=True), True, True),
        (all_(IS_API, any_(UNKNOWN_CONTACT, negate=True)), False, None),
        (any_(IS_WEB, all_(IS_API, all_(UNKNOWN_CONTACT, negate=True))), False, None),
    ],
)
def test_three_valued_logic(group: Group, trusting: Truth, distrusting: Truth) -> None:
    facts = Facts.of(doc(contact_id=ACME), unverified=frozenset({"contact"}))

    assert evaluate(group, facts, {}) is trusting
    assert evaluate(group, facts, {}, distrust=True) is distrusting


def test_confirmed_values_are_trusted() -> None:
    facts = Facts.of(doc(contact_id=ACME, document_type_id=INVOICE))

    assert evaluate(FROM_ACME, facts, {}, distrust=True) is True


def test_unconfirmed_document_type_is_unknown() -> None:
    facts = Facts.of(doc(document_type_id=INVOICE), unverified=frozenset({"document_type"}))
    group = all_(cond(ConditionField.DOCUMENT_TYPE, Operator.PRESENT))

    assert evaluate(group, facts, {}) is True
    assert evaluate(group, facts, {}, distrust=True) is None


@pytest.mark.parametrize(
    ("op", "value", "expected"),
    [
        (Operator.CONTAINS, str(PAID), None),  # only the model set it
        (Operator.CONTAINS, str(OPEN), True),  # a person set it
        (Operator.CONTAINS, str(URGENT), False),
        (Operator.IN, [str(PAID), str(URGENT)], None),
        (Operator.IN, [str(PAID), str(OPEN)], True),
        (Operator.PRESENT, None, True),
        (Operator.MISSING, None, False),
    ],
)
def test_unconfirmed_tags_are_unknown(op: Operator, value: JsonValue, expected: Truth) -> None:
    facts = Facts.of(doc(tag_ids={PAID, OPEN}), unverified_tags=frozenset({PAID}))
    group = all_(cond(ConditionField.TAGS, op, value))

    assert evaluate(group, facts, {}, distrust=True) is expected


@pytest.mark.parametrize("op", [Operator.PRESENT, Operator.MISSING])
def test_only_unconfirmed_tags_make_present_and_missing_unknown(op: Operator) -> None:
    facts = Facts.of(doc(tag_ids={PAID}), unverified_tags=frozenset({PAID}))
    group = all_(cond(ConditionField.TAGS, op))

    assert evaluate(group, facts, {}) is (op is Operator.PRESENT)
    assert evaluate(group, facts, {}, distrust=True) is None


def test_facts_keep_only_unconfirmed_tags_the_document_has() -> None:
    facts = Facts.of(doc(tag_ids={PAID}), unverified_tags=frozenset({PAID, URGENT}))

    assert facts.unverified_tags == frozenset({PAID})


def test_match_says_which_unconfirmed_values_it_relies_on() -> None:
    by_contact = rule(ForceReview("x"), when=FROM_ACME)
    by_contact_or_tag = rule(
        ForceReview("x"),
        when=any_(UNKNOWN_CONTACT, cond(ConditionField.TAGS, Operator.CONTAINS, str(PAID))),
    )
    also_by_channel = rule(ForceReview("x"), when=any_(UNKNOWN_CONTACT, IS_API))
    facts = Facts.of(
        doc(contact_id=ACME, tag_ids={PAID}),
        unverified=frozenset({"contact"}),
        unverified_tags=frozenset({PAID}),
    )

    found = matches([by_contact, by_contact_or_tag, also_by_channel], facts, {})

    assert found == [
        Match(by_contact, trusted=False, distrusted=("contact",)),
        Match(by_contact_or_tag, trusted=False, distrusted=("contact", "tags")),
        Match(also_by_channel, trusted=True),
    ]


def test_change_acts_on_the_edge_only() -> None:
    becomes_true = rule(AddTags(frozenset({PAID})), when=FROM_ACME)
    was_true = rule(AddTags(frozenset({URGENT})))
    before, after = doc(), doc(contact_id=ACME)

    found = matches([becomes_true, was_true], Facts.of(after), {}, before=Facts.of(before))
    again = matches([becomes_true], Facts.of(after), {}, before=Facts.of(after))

    assert [item.rule for item in found] == [becomes_true]
    assert again == []


# --- text -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Invoice", True), ("invoice r-2026", True), ("R-20", False), ("Mahnung", False)],
)
def test_text_contains(value: str, expected: bool) -> None:
    facts = Facts.of(doc(), text=DocumentText("**Invoice** R-2026 from ACME"))
    group = all_(cond(ConditionField.TEXT, Operator.CONTAINS, value))

    assert evaluate(group, facts, {}) is expected


def test_text_conditions_without_text_do_not_hold() -> None:
    facts = Facts.of(doc(), patterns={("text", "R-\\d+", False): True})

    assert evaluate(all_(cond(ConditionField.TEXT, Operator.CONTAINS, "R")), facts, {}) is False
    assert evaluate(all_(cond(ConditionField.TEXT, Operator.MATCHES, "R-\\d+")), facts, {}) is False


def test_text_matches_reads_the_pattern_results() -> None:
    facts = Facts.of(
        doc(),
        text=DocumentText("Invoice R-2026"),
        patterns={("text", "R-\\d+", True): True, ("text", "^X", False): False},
    )

    def holds(pattern: str, case_sensitive: bool = False) -> Truth:
        condition = cond(
            ConditionField.TEXT, Operator.MATCHES, pattern, case_sensitive=case_sensitive
        )
        return evaluate(all_(condition), facts, {})

    assert holds("R-\\d+", case_sensitive=True) is True
    assert holds("R-\\d+") is False  # another case setting: no result, no match (time out)
    assert holds("^X") is False
    assert holds("Invoice") is False  # not computed


# --- fields -------------------------------------------------------------------------------


FIELD_FACTS = Facts.of(
    doc(
        fields={
            AMOUNT.id: Money(Decimal("120.00"), "EUR"),
            DUE.id: date(2026, 3, 31),
            REFERENCE.id: "ACME Contract 7",
            INTERVAL.id: "monthly",
            COUNT.id: Decimal("12.50"),
            PAID_FLAG.id: False,
            PORTAL.id: Url("https://portal.example.org/Invoices"),
            SPAN.id: Period.month(2026, 9),
        }
    ),
    patterns={(str(REFERENCE.id), "^ACME", True): True},
)


@pytest.mark.parametrize(
    ("attr", "op", "value", "expected"),
    [
        (AMOUNT, Operator.GT, {"amount": "100", "currency": "EUR"}, True),
        (AMOUNT, Operator.GT, {"amount": "120", "currency": "EUR"}, False),
        (AMOUNT, Operator.LT, {"amount": "200", "currency": "EUR"}, True),
        (AMOUNT, Operator.IS, {"amount": "120", "currency": "EUR"}, True),
        (AMOUNT, Operator.GT, {"amount": "100", "currency": "USD"}, False),  # other currency
        (AMOUNT, Operator.LT, {"amount": "200", "currency": "USD"}, False),
        (AMOUNT, Operator.IS, {"amount": "120", "currency": "USD"}, False),
        (DUE, Operator.GT, "2026-03-30", True),
        (DUE, Operator.GT, "2026-03-31", False),
        (DUE, Operator.LT, "2026-04-01", True),
        (DUE, Operator.IS, "2026-03-31", True),
        (REFERENCE, Operator.IS, "acme contract 7", True),  # text ignores case
        (REFERENCE, Operator.IS, "ACME Contract", False),
        (REFERENCE, Operator.IN, ["x", "ACME CONTRACT 7"], True),
        (REFERENCE, Operator.CONTAINS, "contract", True),
        (REFERENCE, Operator.MATCHES, "^ACME", False),  # result for case_sensitive only
        (INTERVAL, Operator.IN, ["monthly", "yearly"], True),
        (INTERVAL, Operator.IN, ["weekly", "yearly"], False),
        (INTERVAL, Operator.IS, "monthly", True),
        (COUNT, Operator.IS, "12.5", True),
        (COUNT, Operator.GT, "12", True),
        (COUNT, Operator.LT, "12", False),
        (PAID_FLAG, Operator.IS, False, True),
        (PAID_FLAG, Operator.IS, True, False),
        (PORTAL, Operator.IS, "https://portal.example.org/Invoices", True),
        (PORTAL, Operator.CONTAINS, "invoices", True),
        (AMOUNT, Operator.PRESENT, None, True),
        (AMOUNT, Operator.MISSING, None, False),
        (SPAN, Operator.IS, {"start": "2026-09-01", "end": "2026-09-30"}, True),
        (SPAN, Operator.IS, {"start": "2026-09-01", "end": "2026-09-29"}, False),
        (SPAN, Operator.OVERLAPS, {"start": "2026-09-30", "end": "2026-10-31"}, True),
        (SPAN, Operator.OVERLAPS, {"start": "2026-01-01", "end": "2026-12-31"}, True),
        (SPAN, Operator.OVERLAPS, {"start": "2026-10-01", "end": "2026-10-31"}, False),
        (SPAN, Operator.GT, "2026-08-31", True),  # starts after
        (SPAN, Operator.GT, "2026-09-01", False),
        (SPAN, Operator.LT, "2026-10-01", True),  # ends before
        (SPAN, Operator.LT, "2026-09-30", False),
        (SPAN, Operator.PRESENT, None, True),
    ],
)
def test_field_conditions(
    attr: FieldDefinition, op: Operator, value: JsonValue, expected: bool
) -> None:
    group = all_(cond(ConditionField.FIELD, op, value, field_id=attr.id))

    assert evaluate(group, FIELD_FACTS, DEFINITIONS) is expected


def test_field_matches_reads_the_pattern_results() -> None:
    group = all_(
        cond(
            ConditionField.FIELD,
            Operator.MATCHES,
            "^ACME",
            field_id=REFERENCE.id,
            case_sensitive=True,
        )
    )

    assert evaluate(group, FIELD_FACTS, DEFINITIONS) is True


@pytest.mark.parametrize(
    ("op", "value", "expected"),
    [
        (Operator.GT, {"amount": "1", "currency": "EUR"}, False),
        (Operator.IS, {"amount": "1", "currency": "EUR"}, False),
        (Operator.PRESENT, None, False),
        (Operator.MISSING, None, True),
    ],
)
def test_field_without_value(op: Operator, value: JsonValue, expected: bool) -> None:
    group = all_(cond(ConditionField.FIELD, op, value, field_id=AMOUNT.id))

    assert evaluate(group, Facts.of(doc()), DEFINITIONS) is expected


def test_condition_on_a_deleted_field_does_not_hold() -> None:
    group = all_(cond(ConditionField.FIELD, Operator.MISSING, field_id=AMOUNT.id))

    assert evaluate(group, Facts.of(doc()), {}) is False


def test_field_value_that_no_longer_fits_does_not_hold() -> None:
    # The choice was removed from the definition after the rule was written.
    group = all_(cond(ConditionField.FIELD, Operator.IS, "daily", field_id=INTERVAL.id))

    assert evaluate(group, FIELD_FACTS, DEFINITIONS) is False


@pytest.mark.parametrize(
    ("op", "value", "expected"),
    [
        (Operator.IS, "2026-03-31", True),
        (Operator.GT, "2026-03-31", False),
        (Operator.LT, "2026-04-01", True),
        (Operator.PRESENT, None, True),
    ],
)
def test_document_date(op: Operator, value: JsonValue, expected: bool) -> None:
    group = all_(cond(ConditionField.DOCUMENT_DATE, op, value))

    assert evaluate(group, Facts.of(doc(document_date=date(2026, 3, 31))), {}) is expected
    assert evaluate(group, Facts.of(doc()), {}) is False


def test_contact_and_channel() -> None:
    facts = Facts.of(doc(contact_id=ACME, channel=Channel.WEB))

    def holds(condition: Condition) -> Truth:
        return evaluate(all_(condition), facts, {})

    assert holds(cond(ConditionField.CONTACT, Operator.IN, [str(BETA), str(ACME)])) is True
    assert holds(cond(ConditionField.CONTACT, Operator.IS, str(BETA))) is False
    assert holds(cond(ConditionField.DOCUMENT_TYPE, Operator.MISSING)) is True
    assert holds(cond(ConditionField.CHANNEL, Operator.IS, "web")) is True
    assert holds(cond(ConditionField.CHANNEL, Operator.IN, ["api", "migration"])) is False


def test_contact_ids_compare_as_ids_not_as_text() -> None:
    # `_uuid` accepts any spelling of an id (upper case, without hyphens); the condition must
    # match the contact however the id was written, as tag conditions do.
    facts = Facts.of(doc(contact_id=ACME))

    assert evaluate(all_(cond(ConditionField.CONTACT, Operator.IS, str(ACME).upper())), facts, {})


# --- helpers ----------------------------------------------------------------------------------


def test_pattern_subjects() -> None:
    by_text = rule(
        ForceReview("x"),
        when=all_(cond(ConditionField.TEXT, Operator.MATCHES, "R-\\d+", case_sensitive=True)),
    )
    by_field = rule(
        ForceReview("x"),
        when=any_(
            cond(ConditionField.FIELD, Operator.MATCHES, "^A", field_id=REFERENCE.id),
            cond(ConditionField.FIELD, Operator.MATCHES, "^h", field_id=PORTAL.id),
            cond(ConditionField.FIELD, Operator.MATCHES, "^x", field_id=DUE.id),
        ),
    )
    document = doc(fields={REFERENCE.id: "ACME 7", PORTAL.id: Url("https://example.org")})

    assert pattern_subjects([by_text, by_field], document, "Invoice R-1") == {
        ("text", "R-\\d+", True): "Invoice R-1",
        (str(REFERENCE.id), "^A", False): "ACME 7",
        (str(PORTAL.id), "^h", False): "https://example.org",
    }
    assert ("text", "R-\\d+", True) not in pattern_subjects([by_text], document, None)


def test_pattern_text() -> None:
    assert pattern_text("# **Invoice**\n\n| R-1 | `x` |", 100) == "Invoice R-1 x"
    assert pattern_text("abc def", 5) == "abc d"


# --- tags in trees and groups -------------------------------------------------------------


def test_a_tag_condition_matches_the_tags_below_it() -> None:
    tags, taxonomy = tagged()
    facts = Facts.of(doc(tag_ids={tags["dental"].id}), taxonomy=taxonomy)
    for wanted, expected in (("insurance", True), ("health", True), ("dental", True)):
        condition = cond(ConditionField.TAGS, Operator.CONTAINS, str(tags[wanted].id))
        assert evaluate(all_(condition), facts, {}) is expected
    on_health = cond(ConditionField.TAGS, Operator.CONTAINS, str(tags["health"].id))
    assert (
        evaluate(
            all_(on_health), Facts.of(doc(tag_ids={tags["insurance"].id}), taxonomy=taxonomy), {}
        )
        is False
    )
    one_of = cond(ConditionField.TAGS, Operator.IN, [str(PAID), str(tags["insurance"].id)])
    assert evaluate(all_(one_of), facts, {}) is True


def test_conditions_on_the_groups_of_contact_and_type() -> None:
    tags, taxonomy = tagged()
    facts = Facts.of(doc(contact_id=ACME, document_type_id=INVOICE), taxonomy=taxonomy)
    other = Facts.of(doc(contact_id=BETA), taxonomy=taxonomy)

    def truth(field: ConditionField, op: Operator, value: JsonValue, of: Facts) -> Truth:
        return evaluate(all_(cond(field, op, value)), of, {})

    group, kind = ConditionField.CONTACT_GROUP, ConditionField.DOCUMENT_TYPE_GROUP
    insurer, bills = str(tags["insurer"].id), str(tags["bills"].id)
    assert truth(group, Operator.CONTAINS, insurer, facts) is True  # a group below it
    assert truth(group, Operator.CONTAINS, str(tags["health_insurer"].id), facts) is True
    assert truth(group, Operator.IN, [bills, insurer], facts) is True
    assert truth(group, Operator.CONTAINS, insurer, other) is False
    assert truth(group, Operator.PRESENT, None, facts) is True
    assert truth(group, Operator.MISSING, None, other) is True
    assert truth(kind, Operator.CONTAINS, bills, facts) is True
    assert truth(kind, Operator.PRESENT, None, other) is False


def test_groups_of_an_unconfirmed_contact_are_unknown_under_distrust() -> None:
    tags, taxonomy = tagged()
    document = doc(contact_id=ACME, document_type_id=INVOICE)
    facts = Facts.of(document, unverified=frozenset({"contact"}), taxonomy=taxonomy)
    in_group = all_(cond(ConditionField.CONTACT_GROUP, Operator.CONTAINS, str(tags["insurer"].id)))
    of_type = all_(cond(ConditionField.DOCUMENT_TYPE_GROUP, Operator.PRESENT))
    assert evaluate(in_group, facts, {}) is True
    assert evaluate(in_group, facts, {}, distrust=True) is None
    assert evaluate(of_type, facts, {}, distrust=True) is True  # the type is confirmed
    filing = rule(SetSpace(SHARED), when=in_group)
    (match,) = matches([filing], facts, {})
    assert (match.trusted, match.distrusted) == (False, ("contact",))
    result = plan([match], situation(document))
    assert ("space", "refused") in notes(result)


def test_an_unconfirmed_tag_below_the_wanted_one_is_unknown_under_distrust() -> None:
    tags, taxonomy = tagged()
    facts = Facts.of(
        doc(tag_ids={tags["dental"].id}),
        unverified_tags=frozenset({tags["dental"].id}),
        taxonomy=taxonomy,
    )
    wanted = all_(cond(ConditionField.TAGS, Operator.CONTAINS, str(tags["insurance"].id)))
    assert evaluate(wanted, facts, {}, distrust=True) is None


# --- topics -------------------------------------------------------------------------------------


def test_a_topic_condition_matches_the_topics_below_it_and_is_unknown_unconfirmed() -> None:
    tags, taxonomy = topics()
    document = doc(contact_id=ACME, topic_id=tags["health"].id)
    facts = Facts.of(document, taxonomy=taxonomy)

    def truth(op: Operator, value: JsonValue, of: Facts = facts) -> Truth:
        return evaluate(all_(cond(ConditionField.TOPIC, op, value)), of, {}, distrust=True)

    insurance, health, work = (str(tags[name].id) for name in ("insurance", "health", "work"))
    assert truth(Operator.IS, insurance) is True
    assert truth(Operator.IS, health) is True
    assert truth(Operator.IS, work) is False
    assert truth(Operator.IN, [work, insurance]) is True
    assert truth(Operator.PRESENT, None) is True
    assert truth(Operator.MISSING, None, Facts.of(doc(), taxonomy=taxonomy)) is True
    unconfirmed = Facts.of(document, unverified=frozenset({"topic"}), taxonomy=taxonomy)
    assert truth(Operator.IS, health, unconfirmed) is None
    filing = rule(SetSpace(SHARED), when=all_(cond(ConditionField.TOPIC, Operator.IS, health)))
    (match,) = matches([filing], unconfirmed, {})
    assert (match.trusted, match.distrusted) == (False, ("topic",))
