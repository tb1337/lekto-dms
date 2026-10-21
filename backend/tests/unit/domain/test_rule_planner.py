from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from lekto.core.domain.documents import UNSET, Document, DocumentChanges
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import FieldDefinition, FieldType, Money
from lekto.core.domain.ids import ContactId, FieldId, RuleId, SpaceId, TagId, new_id
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.pipeline import Outcome
from lekto.core.domain.rule_conditions import Facts, matches
from lekto.core.domain.rule_planner import (
    Effect,
    Mode,
    Note,
    NoteKind,
    RulePlan,
    RuleReport,
    Situation,
    changed_fields,
    plan,
    reviewing_rules,
)
from lekto.core.domain.rules import (
    AddTags,
    ConditionField,
    ForceReview,
    Operator,
    RemoveTags,
    Rule,
    RuleDefinition,
    RuleScope,
    SetContact,
    SetDocumentType,
    SetField,
    SetSpace,
    SetTitle,
    SetTopic,
)
from tests.builders import NOW
from tests.unit.domain.rules_support import (
    ACME,
    ALWAYS,
    AMOUNT,
    BETA,
    DEFAULT,
    DEFINITIONS,
    EXISTING,
    FROM_ACME,
    INTERVAL,
    INVOICE,
    LETTER,
    NAMES,
    OPEN,
    OWN,
    OWNER,
    PAID,
    PAID_FLAG,
    READ_ONLY,
    SHARED,
    SPACES,
    SPAN,
    STRANGER,
    THEIRS,
    URGENT,
    all_,
    check,
    check_or_none,
    cond,
    doc,
    notes,
    rule,
    run,
    situation,
    tagged,
    topics,
)

# --- combining actions ------------------------------------------------------------------------


def test_conditions_see_the_state_before_rules_act() -> None:
    # A adds PAID; B acts on PAID: B does not act in the same run (loop protection).
    a = rule(AddTags(frozenset({PAID})))
    b = rule(
        AddTags(frozenset({URGENT})),
        when=all_(cond(ConditionField.TAGS, Operator.CONTAINS, str(PAID))),
    )
    document = doc()

    found = matches([a, b], Facts.of(document), {})
    result = plan(found, situation(document))

    assert [item.rule for item in found] == [a]
    assert result.changes.tag_ids == frozenset({PAID})
    assert [report.rule_id for report in result.reports] == [a.id]


def test_a_rule_does_not_undo_its_own_trigger_in_the_same_run() -> None:
    # A removes OPEN when PAID is present, B adds PAID when OPEN is present: one run acts on
    # the state before, so each sees only the original tags.
    a = rule(
        RemoveTags(frozenset({OPEN})),
        when=all_(cond(ConditionField.TAGS, Operator.CONTAINS, str(PAID))),
    )
    b = rule(
        AddTags(frozenset({PAID})),
        when=all_(cond(ConditionField.TAGS, Operator.CONTAINS, str(OPEN))),
    )
    document = doc(tag_ids={OPEN})

    result = run([a, b], situation(document))

    assert result.changes.tag_ids == frozenset({OPEN, PAID})


def test_same_value_from_two_rules_is_set() -> None:
    a, b = rule(SetContact(ACME)), rule(SetContact(ACME), priority=500)

    result = run([a, b], situation(doc()))

    assert result.changes.contact_id == ACME
    assert [report.applied for report in result.reports] == [
        [Effect("contact", None, str(ACME))],
        [Effect("contact", None, str(ACME))],
    ]
    assert check(result, "contact").outcome is Outcome.OK
    assert not result.uncertain


def test_different_values_conflict_whatever_the_priority() -> None:
    high, low = rule(SetContact(ACME), priority=900), rule(SetContact(BETA), priority=10)

    result = run([low, high], situation(doc()))

    assert result.changes.contact_id is UNSET
    assert notes(result) == [("contact", "conflict"), ("contact", "conflict")]
    contact = check(result, "contact")
    assert contact.outcome is Outcome.UNCERTAIN
    assert contact.suggestion == str(ACME)
    assert result.uncertain
    assert result.reasons[0].startswith("contact: rules set different values")


def test_reasons_name_values_not_ids() -> None:
    """Contacts, types, topics, spaces, tags and fields by their names, a field's value as
    written; the ids stay in the suggestion and the effects."""
    names = {**NAMES, PAID: "Paid"}
    contacts = run(
        [rule(SetContact(ACME), name="Nord, Arbeit"), rule(SetContact(BETA), name="Süd")],
        situation(doc(), names=names),
    )
    assert check(contacts, "contact").reason == (
        "rules set different values ('Nord, Arbeit': 'ACME GmbH', 'Süd': 'Beta AG')"
    )
    assert check(contacts, "contact").suggestion == str(ACME)
    amounts = run(
        [
            rule(SetField(AMOUNT.id, {"amount": "12.50", "currency": "EUR"}), name="a"),
            rule(SetField(AMOUNT.id, {"amount": "13", "currency": "EUR"}), name="b"),
            rule(SetField(INTERVAL.id, "monthly"), name="c"),
            rule(SetField(INTERVAL.id, "yearly"), name="d"),
            rule(SetField(SPAN.id, {"start": "2026-09-01", "end": "2026-09-30"}), name="e"),
            rule(SetField(SPAN.id, {"start": "2026-07-01", "end": "2026-09-30"}), name="f"),
        ],
        situation(doc(), definitions=DEFINITIONS),
    )
    assert amounts.reasons == [
        "'amount': rules set different values ('a': 12.50 EUR, 'b': 13 EUR)",
        "'choice': rules set different values ('c': 'monthly', 'd': 'yearly')",
        "'period': rules set different values ('e': 2026-09, 'f': 2026-Q3)",
    ]
    model = run(
        [rule(SetContact(ACME))],
        situation(doc(contact_id=BETA), names=names, model_values={"contact": str(BETA)}),
    )
    assert check(model, "contact").reason == "rules: the model set another value ('Beta AG')"
    tags = run(
        [rule(AddTags(frozenset({PAID}))), rule(RemoveTags(frozenset({PAID})))],
        situation(doc(), names=names),
    )
    assert check(tags, "tags").reason == "tag 'Paid' is added and removed by rules"
    refused = run([rule(SetSpace(READ_ONLY))], situation(doc()))
    assert check(refused, "space").reason.endswith(
        f"no right to file into space '{SPACES[READ_ONLY].name}' (any more)"
    )


def test_person_decided_field_overrules_the_rule() -> None:
    result = run(
        [rule(SetContact(ACME))],
        situation(doc(contact_id=BETA), locked=frozenset({"contact"})),
    )

    assert result.changes.contact_id is UNSET
    assert notes(result) == [("contact", "overruled")]
    assert result.checks == []
    assert not result.uncertain


def test_person_decided_field_is_not_yellow_even_if_rules_disagree() -> None:
    result = run(
        [rule(SetContact(ACME)), rule(SetContact(BETA))],
        situation(doc(contact_id=BETA), locked=frozenset({"contact"})),
    )

    assert notes(result) == [("contact", "conflict"), ("contact", "conflict")]
    assert not result.uncertain


def test_rule_does_not_replace_an_unconfirmed_model_value() -> None:
    result = run(
        [rule(SetDocumentType(LETTER))],
        situation(doc(document_type_id=INVOICE), model_values={"document_type": str(INVOICE)}),
    )

    assert result.changes.document_type_id is UNSET
    assert notes(result) == [("document_type", "conflict")]
    document_type = check(result, "document_type")
    assert document_type.outcome is Outcome.UNCERTAIN
    assert document_type.suggestion == str(LETTER)


def test_rule_agreeing_with_the_model_changes_nothing() -> None:
    result = run(
        [rule(SetDocumentType(INVOICE))],
        situation(doc(document_type_id=INVOICE), model_values={"document_type": str(INVOICE)}),
    )

    assert result.changes == DocumentChanges()
    assert notes(result) == [] and result.checks == []


def test_action_on_deleted_master_data_is_skipped() -> None:
    gone = ContactId(new_id())

    result = run([rule(SetContact(gone), AddTags(frozenset({TagId(new_id())})))], situation(doc()))

    assert result.changes == DocumentChanges()
    assert notes(result) == [("contact", "skipped"), ("tags", "skipped")]


# --- tags -------------------------------------------------------------------------------------


def test_tags_of_several_rules_are_combined() -> None:
    result = run(
        [
            rule(AddTags(frozenset({PAID}))),
            rule(AddTags(frozenset({URGENT})), RemoveTags(frozenset({OPEN}))),
        ],
        situation(doc(tag_ids={OPEN})),
    )

    assert result.changes.tag_ids == frozenset({PAID, URGENT})
    assert not result.uncertain


def test_tag_added_and_removed_is_a_conflict() -> None:
    adds, removes = rule(AddTags(frozenset({PAID, URGENT}))), rule(RemoveTags(frozenset({PAID})))

    result = run([adds, removes], situation(doc()))

    assert result.changes.tag_ids == frozenset({URGENT})
    assert notes(result) == [("tags", "conflict"), ("tags", "conflict")]
    assert check(result, "tags").outcome is Outcome.UNCERTAIN


def test_removing_a_model_tag_is_no_conflict() -> None:
    result = run(
        [rule(RemoveTags(frozenset({PAID})))],
        situation(doc(tag_ids={PAID, OPEN})),
    )

    assert result.changes.tag_ids == frozenset({OPEN})
    assert result.reports[0].applied == [Effect("tags", str(PAID), None)]
    assert not result.uncertain


def test_tags_a_person_set_or_removed_are_kept() -> None:
    result = run(
        [rule(AddTags(frozenset({URGENT})), RemoveTags(frozenset({OPEN})))],
        situation(
            doc(tag_ids={OPEN}),
            person_added_tags=frozenset({OPEN}),
            person_removed_tags=frozenset({URGENT}),
        ),
    )

    assert result.changes.tag_ids is UNSET
    assert notes(result) == [("tags", "overruled"), ("tags", "overruled")]
    assert not result.uncertain


def test_tags_already_as_wanted_change_nothing() -> None:
    result = run(
        [rule(AddTags(frozenset({PAID})), RemoveTags(frozenset({OPEN})))],
        situation(doc(tag_ids={PAID})),
    )

    assert result.changes.tag_ids is UNSET
    assert result.effects == []


# --- spaces and distrust ---------------------------------------------------------------------


def distrusted(document: Document) -> Facts:
    return Facts.of(document, unverified=frozenset({"contact"}))


def test_unconfirmed_contact_does_not_file_into_a_shared_space() -> None:
    document = doc(contact_id=ACME)

    result = run(
        [rule(SetSpace(SHARED), when=FROM_ACME)], situation(document), facts=distrusted(document)
    )

    assert result.space is None
    assert notes(result) == [("space", "refused")]
    assert "only with a confirmed contact" in result.reports[0].notes[0].reason
    contact = check(result, "contact")
    assert contact.outcome is Outcome.UNCERTAIN
    assert contact.suggestion == str(ACME)
    assert result.uncertain


def test_unconfirmed_contact_may_file_into_the_owners_own_space() -> None:
    document = doc(contact_id=ACME)

    result = run(
        [rule(SetSpace(OWN), when=FROM_ACME)], situation(document), facts=distrusted(document)
    )

    assert result.space == OWN
    assert result.reports[0].applied == [Effect("space", str(DEFAULT), str(OWN))]
    assert not result.uncertain


def test_confirmed_contact_files_into_a_shared_space() -> None:
    result = run([rule(SetSpace(SHARED), when=FROM_ACME)], situation(doc(contact_id=ACME)))

    assert result.space == SHARED


def test_unconfirmed_contact_on_change_is_reported_only() -> None:
    document = doc(contact_id=ACME)

    result = run(
        [rule(SetSpace(SHARED), when=FROM_ACME)],
        situation(document, Mode.CHANGE),
        facts=distrusted(document),
    )

    assert result.space is None
    assert notes(result) == [("space", "refused")]
    assert not result.uncertain


def test_retroactive_filing_on_unconfirmed_values_is_a_conflict() -> None:
    """Applied to existing documents, filing into a shared space on an unconfirmed contact is
    a conflict: it acts only where the person accepted it."""
    document = doc(contact_id=ACME)
    rules = [rule(SetSpace(SHARED), when=FROM_ACME)]

    refused = run(rules, situation(document, Mode.RETROACTIVE), facts=distrusted(document))
    accepted = run(
        rules,
        situation(document, Mode.RETROACTIVE, accept_conflicts=True),
        facts=distrusted(document),
    )

    assert refused.space is None
    assert notes(refused) == [("space", "conflict")]
    assert accepted.space == SHARED


def test_no_write_access_to_the_space() -> None:
    ingest = run([rule(SetSpace(READ_ONLY))], situation(doc()))
    change = run([rule(SetSpace(READ_ONLY))], situation(doc(), Mode.CHANGE))

    assert ingest.space is None and change.space is None
    assert notes(ingest) == notes(change) == [("space", "refused")]
    assert check(ingest, "space").outcome is Outcome.UNCERTAIN
    assert not change.uncertain


def test_a_rule_of_another_space_does_not_move_the_document() -> None:
    result = run([rule(SetSpace(OWN), space=SHARED)], situation(doc()))

    assert result.space is None
    assert notes(result) == [("space", "refused")]
    assert result.reports[0].notes[0].reason == "the rule belongs to another space"


def test_whoever_saved_the_rule_must_be_allowed_to_file() -> None:
    """The space is checked for the author of the rule's current version, not the rule's
    space: a rule a stranger saved does not file into OWNER's space."""
    result = run([rule(SetSpace(OWN), by=STRANGER)], situation(doc()))

    assert result.space is None
    assert notes(result) == [("space", "refused")]
    assert check(result, "space").outcome is Outcome.UNCERTAIN


def test_a_rule_hands_a_document_over_into_another_users_personal_space() -> None:
    """Handing over needs no membership; it shows the document to someone new, so only with
    confirmed values."""
    trusted = run([rule(SetSpace(THEIRS))], situation(doc()))
    assert trusted.space == THEIRS
    document = doc(contact_id=ACME)
    distrusting = run(
        [rule(SetSpace(THEIRS), when=FROM_ACME)], situation(document), facts=distrusted(document)
    )
    assert distrusting.space is None
    assert notes(distrusting) == [("space", "refused")]


def test_deleted_space_is_skipped() -> None:
    result = run([rule(SetSpace(SpaceId(new_id())))], situation(doc()))

    assert result.space is None
    assert notes(result) == [("space", "skipped")]
    assert not result.uncertain


def test_rules_filing_into_different_spaces_conflict() -> None:
    result = run([rule(SetSpace(OWN)), rule(SetSpace(SHARED))], situation(doc()))

    assert result.space is None
    assert check(result, "space").outcome is Outcome.UNCERTAIN


# --- global rules -----------------------------------------------------------------------------


def test_a_global_rule_may_set_every_value_and_the_space() -> None:
    """Tobi, 21.10.2026: no limits for global rules; filing into a space follows the same
    checks as any rule (the admin who saved it may file anywhere)."""
    result = run(
        [
            rule(
                SetSpace(OWN),
                SetContact(ACME),
                SetDocumentType(INVOICE),
                SetTitle("{{ contact }}"),
                AddTags(frozenset({PAID})),
                scope=RuleScope.GLOBAL,
            )
        ],
        situation(doc(), names=NAMES),
    )

    assert result.space == OWN
    assert result.changes.contact_id == ACME
    assert result.changes.document_type_id == INVOICE
    assert result.changes.title == "ACME GmbH"
    assert result.changes.tag_ids == frozenset({PAID})
    assert notes(result) == []


def test_global_rule_tags_sets_fields_and_forces_reviews() -> None:
    result = run(
        [
            rule(
                AddTags(frozenset({PAID})),
                SetField(PAID_FLAG.id, True),
                ForceReview("check"),
                scope=RuleScope.GLOBAL,
                name="Paid",
            )
        ],
        situation(doc(), definitions=DEFINITIONS),
    )

    assert result.changes.tag_ids == frozenset({PAID})
    assert result.changes.fields == {PAID_FLAG.id: True}
    assert result.reviews == ["rule 'Paid': check"]


# --- order ------------------------------------------------------------------------------------


def test_reports_in_rule_order() -> None:
    low = rule(ForceReview("x"), priority=50)
    user_older = rule(ForceReview("x"))
    user_newer = rule(ForceReview("x"))
    global_newest = rule(ForceReview("x"), scope=RuleScope.GLOBAL)
    high = rule(ForceReview("x"), priority=900)

    result = run([low, user_newer, global_newest, high, user_older], situation(doc()))

    assert [report.rule_id for report in result.reports] == [
        item.id for item in (high, global_newest, user_older, user_newer, low)
    ]


# --- modes ------------------------------------------------------------------------------------


def test_forced_review_on_arrival() -> None:
    result = run([rule(ForceReview("check the IBAN"), name="Bank")], situation(doc()))

    assert result.reviews == ["rule 'Bank': check the IBAN"]
    assert result.uncertain
    assert result.reasons == ["review: rule 'Bank': check the IBAN", "rule 'Bank': check the IBAN"]


def test_forced_review_after_a_person_confirmed_it() -> None:
    confirmed, other = rule(ForceReview("check")), rule(ForceReview("new"))

    result = run([confirmed, other], situation(doc(), reviewed=frozenset({confirmed.id})))

    assert result.reviews == [f"rule '{other.definition.name}': new"]
    assert notes(result) == [("review", "overruled"), ("review", "review")]
    assert result.uncertain


@pytest.mark.parametrize("mode", [Mode.CHANGE, Mode.RETROACTIVE])
def test_forced_review_only_on_arrival(mode: Mode) -> None:
    result = run([rule(ForceReview("check"))], situation(doc(), mode))

    assert result.reviews == []
    assert notes(result) == [("review", "skipped")]
    assert not result.uncertain


def test_change_turns_nothing_yellow() -> None:
    document = doc(document_type_id=INVOICE)

    result = run(
        [
            rule(SetContact(ACME)),
            rule(SetContact(BETA)),
            rule(SetDocumentType(LETTER)),
            rule(AddTags(frozenset({PAID}))),
            rule(RemoveTags(frozenset({PAID}))),
            rule(SetTitle("{{ contact | default: '' }} letter")),
        ],
        situation(document, Mode.CHANGE, model_values={"document_type": str(INVOICE)}),
    )

    assert result.changes.contact_id is UNSET
    assert result.changes.document_type_id is UNSET
    assert result.changes.tag_ids is UNSET
    assert result.changes.title == "letter"
    assert ("contact", "conflict") in notes(result)
    assert ("document_type", "conflict") in notes(result)
    assert ("tags", "conflict") in notes(result)
    assert result.checks == []
    assert not result.uncertain


def test_retroactive_conflict_with_an_existing_value() -> None:
    accepted = run(
        [rule(SetContact(ACME))],
        situation(doc(contact_id=BETA), Mode.RETROACTIVE, accept_conflicts=True),
    )
    refused = run([rule(SetContact(ACME))], situation(doc(contact_id=BETA), Mode.RETROACTIVE))
    empty = run([rule(SetContact(ACME))], situation(doc(), Mode.RETROACTIVE))

    assert accepted.changes.contact_id == ACME
    assert refused.changes.contact_id is UNSET
    assert notes(refused) == [("contact", "conflict")]
    assert "not accepted" in refused.reports[0].notes[0].reason
    assert empty.changes.contact_id == ACME
    assert not refused.uncertain and refused.checks == []


def test_retroactive_personal_space_and_file_name_title_count_as_empty() -> None:
    actions = (SetSpace(OWN), SetTitle("{{ contact }} invoice"))
    fresh = run([rule(*actions)], situation(doc(contact_id=ACME), Mode.RETROACTIVE))
    filed = run(
        [rule(*actions, space=SHARED)],
        situation(
            doc(contact_id=ACME, space_id=SHARED, title="Mine"),
            Mode.RETROACTIVE,
            in_personal_space=False,
        ),
    )

    assert fresh.space == OWN
    assert fresh.changes.title == "ACME GmbH invoice"
    assert filed.space is None and filed.changes.title is UNSET
    assert notes(filed) == [("space", "conflict"), ("title", "conflict")]


def test_retroactive_the_machines_title_counts_as_empty() -> None:
    titled = doc(contact_id=ACME, title="Stromrechnung März 2026")
    rules = [rule(SetTitle("{{ contact }} invoice"))]
    replaced = run(rules, situation(titled, Mode.RETROACTIVE, machine_title=titled.title))
    kept = run(rules, situation(titled, Mode.RETROACTIVE, machine_title="Another"))
    assert replaced.changes.title == "ACME GmbH invoice"
    assert kept.changes.title is UNSET


# --- titles -----------------------------------------------------------------------------------


def test_title_template() -> None:
    template = (
        "{{ contact }} {{ document_type }} {{ document_date | date: '%Y-%m' }} ({{ filename }})"
    )
    result = run(
        [rule(SetDocumentType(INVOICE)), rule(SetTitle(template))],
        situation(doc(contact_id=ACME, document_date=date(2026, 3, 31))),
    )

    assert result.changes.title == "ACME GmbH Invoice 2026-03 (Rechnung 2026)"
    assert check(result, "title").outcome is Outcome.OK


def test_title_uses_the_contact_a_rule_sets() -> None:
    result = run([rule(SetContact(BETA), SetTitle("Letter {{ contact }}"))], situation(doc()))

    assert result.changes.title == "Letter Beta AG"


def test_a_missing_value_leaves_the_title() -> None:
    """Written without a test or default, a missing value is no title: the one there stays."""
    result = run([rule(SetTitle("Invoice {{ contact }}"))], situation(doc()))

    assert result.changes.title is UNSET
    assert result.reports[0].notes == [Note("title", NoteKind.SKIPPED, "contact has no value")]
    assert check_or_none(result, "title") is None  # nothing to decide: not yellow


def test_optional_parts_and_whitespace() -> None:
    template = (
        "{{ contact | default: '' }}  Invoice   "
        "{% if document_date %}{{ document_date }}{% endif %}"
    )
    result = run([rule(SetTitle(template))], situation(doc()))

    assert result.changes.title == "Invoice"


def test_empty_title_is_skipped() -> None:
    result = run([rule(SetTitle("{% if contact %}{{ contact }}{% endif %}"))], situation(doc()))

    assert result.changes.title is UNSET
    assert notes(result) == [("title", "skipped")]


def test_the_title_sees_fields_tags_space_and_uploader() -> None:
    template = "{{ field.amount }} {{ tags | join: '+' }} {{ space }} {{ uploaded_by }}"
    document = doc(fields={AMOUNT.id: Money(Decimal("99.90"), "EUR")}, tag_ids={PAID})
    names = {**NAMES, PAID: "paid", URGENT: "urgent", DEFAULT: "Inbox"}
    result = run(
        [rule(AddTags(frozenset({URGENT})), SetTitle(template))],
        situation(document, definitions=DEFINITIONS, names=names, uploader_name="tobi"),
    )

    assert result.changes.title == "99,90 EUR paid+urgent Inbox tobi"


def test_a_text_field_from_a_template() -> None:
    number = FieldDefinition.create(name="Reference", data_type=FieldType.TEXT, now=NOW)
    result = run(
        [rule(SetContact(ACME), SetField(number.id, "{{ contact | upcase }}-{{ filename }}"))],
        situation(doc(), definitions={number.id: number}),
    )

    assert result.changes.fields == {number.id: "ACME GMBH-Rechnung 2026"}


def test_a_review_holds_where_its_reason_cannot_be_rendered() -> None:
    result = run(
        [
            rule(ForceReview("check {{ contact }}"), name="a"),
            rule(ForceReview("from {{ filename }}"), name="b"),
        ],
        situation(doc()),
    )

    assert result.reviews == ["rule 'a': check {{ contact }}", "rule 'b': from Rechnung 2026"]


def title_pattern(template: str) -> Rule:
    """The rule of the title pattern of INVOICE."""
    return Rule.create(
        scope=RuleScope.GLOBAL,
        space_id=None,
        definition=RuleDefinition(name="Invoice", conditions=ALWAYS, actions=(SetTitle(template),)),
        by=OWNER,
        now=NOW,
        managed_by=INVOICE,
    )


def test_a_type_s_title_pattern_sets_the_title_as_a_global_rule() -> None:
    result = run(
        [title_pattern("{{ document_type }} {{ filename }}")],
        situation(doc(document_type_id=INVOICE)),
    )

    assert result.changes.title == "Invoice Rechnung 2026"


def test_the_pattern_gives_way_to_another_rule_and_to_a_person() -> None:
    rules = [title_pattern("{{ document_type }}"), rule(SetTitle("Mine"))]
    result = run(rules, situation(doc(document_type_id=INVOICE)))

    assert result.changes.title == "Mine"
    assert ("title", "yielded") in notes(result)
    assert check(result, "title").outcome is Outcome.OK  # no conflict

    person = run(rules[:1], situation(doc(document_type_id=INVOICE), locked=frozenset({"title"})))
    assert person.changes.title is UNSET
    assert notes(person) == [("title", "overruled")]


def test_a_title_pattern_rule_is_global() -> None:
    with pytest.raises(ValidationError, match="global"):
        Rule.create(
            scope=RuleScope.SPACE,
            space_id=DEFAULT,
            definition=RuleDefinition(name="x", conditions=ALWAYS, actions=(SetTitle("x"),)),
            by=OWNER,
            now=NOW,
            managed_by=INVOICE,
        )


def test_titles_of_two_rules_conflict() -> None:
    result = run([rule(SetTitle("A")), rule(SetTitle("B"))], situation(doc()))

    assert result.changes.title is UNSET
    assert check(result, "title").outcome is Outcome.UNCERTAIN


# --- fields -------------------------------------------------------------------------------


def test_set_field() -> None:
    value: JsonValue = {"amount": "99.90", "currency": "EUR"}

    result = run([rule(SetField(AMOUNT.id, value))], situation(doc(), definitions=DEFINITIONS))

    assert result.changes.fields == {AMOUNT.id: Money(Decimal("99.90"), "EUR")}
    assert result.reports[0].applied == [Effect(f"field:{AMOUNT.id}", None, value)]


def test_field_for_another_document_type_is_skipped() -> None:
    bound = FieldDefinition.create(
        name="invoice number",
        data_type=FieldType.TEXT,
        now=NOW,
        document_type_ids=[INVOICE],
    )
    definitions = {bound.id: bound}

    letter = run(
        [rule(SetField(bound.id, "R-1"))],
        situation(doc(document_type_id=LETTER), definitions=definitions),
    )
    becomes_invoice = run(
        [rule(SetDocumentType(INVOICE), SetField(bound.id, "R-1"))],
        situation(doc(document_type_id=LETTER), definitions=definitions),
    )

    assert letter.changes.fields == {}
    assert notes(letter) == [(f"field:{bound.id}", "skipped")]
    assert becomes_invoice.changes.fields == {bound.id: "R-1"}


def test_field_value_that_no_longer_fits_is_skipped() -> None:
    result = run(
        [rule(SetField(INTERVAL.id, "daily")), rule(SetField(FieldId(new_id()), "x"))],
        situation(doc(), definitions=DEFINITIONS),
    )

    assert result.changes.fields == {}
    assert [kind for _, kind in notes(result)] == ["skipped", "skipped"]


# --- helpers ----------------------------------------------------------------------------------


def test_changed_fields() -> None:
    attr = FieldId(new_id())

    changes = DocumentChanges(title="x", contact_id=None, fields={attr: None})

    assert changed_fields(changes) == {"title", "contact", f"field:{attr}"}
    assert changed_fields(DocumentChanges()) == frozenset()


def test_plan_to_json() -> None:
    contact_rule = rule(SetContact(ACME), name="ACME")

    data = run([contact_rule], situation(doc())).to_json()

    assert data["rules"] == [
        {
            "rule_id": str(contact_rule.id),
            "version": 1,
            "scope": "space",
            "applied": [{"field": "contact", "old": None, "new": str(ACME)}],
            "notes": [],
            "name": "ACME",
        }
    ]
    assert data["reviews"] == []
    assert isinstance(data["fields"], list) and len(data["fields"]) == 1


# --- tags in trees and groups -------------------------------------------------------------


def test_rules_add_document_tags_only_and_leave_the_parent_of_a_child() -> None:
    tags, taxonomy = tagged()
    insurance, health, dental = (tags[name].id for name in ("insurance", "health", "dental"))
    existing = EXISTING | {tag.id for tag in tags.values()}
    names: dict[object, str] = {**NAMES, **{tag.id: tag.name for tag in tags.values()}}
    where = situation(doc(tag_ids={health}), existing=existing, names=names, taxonomy=taxonomy)
    parent = rule(AddTags(frozenset({insurance})))
    group = rule(AddTags(frozenset({tags["insurer"].id})))
    result = run([parent, group], where)
    assert result.changes.tag_ids is UNSET  # the document keeps Health: Insurance says less
    assert ("tags", "skipped") in notes(result)
    assert not result.effects
    # A child set by a rule replaces its parent.
    child = rule(AddTags(frozenset({dental, PAID})))
    result = run([child], where)
    assert result.changes.tag_ids == frozenset({dental, PAID})


def test_templates_see_the_groups_of_contact_and_type() -> None:
    tags, taxonomy = tagged()
    names: dict[object, str] = {**NAMES, **{tag.id: tag.name for tag in tags.values()}}
    where = situation(doc(document_type_id=INVOICE), names=names, taxonomy=taxonomy)
    title = SetTitle("{{ contact_groups | join: ', ' }} / {{ document_type_groups | join }}")
    result = run([rule(SetContact(ACME), title)], where)
    assert result.changes.title == "Health insurer / Bills"


# --- topics -------------------------------------------------------------------------------------


def test_a_rule_sets_a_topic_the_contact_enables() -> None:
    tags, taxonomy = topics()
    health, work, insurance = tags["health"].id, tags["work"].id, tags["insurance"].id
    existing = EXISTING | {tag.id for tag in tags.values()}
    names: dict[object, str] = {**NAMES, **{tag.id: tag.name for tag in tags.values()}}

    def where(document: Document, mode: Mode = Mode.INGEST, **fields: Any) -> Situation:
        return situation(
            document, mode, existing=existing, names=names, taxonomy=taxonomy, **fields
        )

    result = run([rule(SetTopic(health), SetTitle("{{ topic }}"))], where(doc(contact_id=ACME)))
    assert (result.changes.topic_id, result.changes.title) == (health, "Health")
    assert check(result, "topic").value == str(health)
    # One the contact does not enable is skipped and noted, also without a contact.
    for document in (doc(contact_id=ACME), doc()):
        result = run([rule(SetTopic(insurance))], where(document))
        assert result.changes.topic_id is UNSET
        assert notes(result) == [("topic", "skipped")]
    skipped = run([rule(SetTopic(insurance))], where(doc(contact_id=ACME)))
    assert skipped.reports[0].notes[0].reason == (
        "its contact does not enable the topic 'Insurance'"
    )
    # Global rules set it too.
    globally = run([rule(SetTopic(work), scope=RuleScope.GLOBAL)], where(doc(contact_id=ACME)))
    assert globally.changes.topic_id == work
    # The contact a rule sets decides; two rules with different topics conflict.
    result = run([rule(SetContact(BETA), SetTopic(work))], where(doc(contact_id=ACME)))
    assert (result.changes.contact_id, result.changes.topic_id) == (BETA, work)
    result = run(
        [rule(SetTopic(work), name="a"), rule(SetTopic(health), name="b")],
        where(doc(contact_id=ACME)),
    )
    assert result.changes.topic_id is UNSET
    assert check(result, "topic").outcome is Outcome.UNCERTAIN
    assert (
        check(result, "topic").reason == "rules set different values ('a': 'Work', 'b': 'Health')"
    )
    # A person's topic wins; the model's is not replaced silently.
    person = run([rule(SetTopic(work))], where(doc(contact_id=ACME), locked=frozenset({"topic"})))
    assert (person.changes.topic_id, notes(person)) == (UNSET, [("topic", "overruled")])
    model = where(doc(contact_id=ACME, topic_id=health), model_values={"topic": str(health)})
    result = run([rule(SetTopic(work))], model)
    assert result.changes.topic_id is UNSET
    assert check(result, "topic").outcome is Outcome.UNCERTAIN


def test_a_contact_a_rule_sets_clears_a_topic_it_does_not_enable() -> None:
    tags, taxonomy = topics()
    health, work = tags["health"].id, tags["work"].id
    where = situation(
        doc(contact_id=ACME, topic_id=health),
        existing=EXISTING | {health, work},
        taxonomy=taxonomy,
    )
    result = run([rule(SetContact(BETA))], where)
    assert (result.changes.contact_id, result.changes.topic_id) == (BETA, None)
    assert Effect("topic", str(health), None) in result.effects
    kept = situation(doc(contact_id=ACME, topic_id=work), existing=EXISTING, taxonomy=taxonomy)
    result = run([rule(SetContact(BETA))], kept)
    assert (result.changes.contact_id, result.changes.topic_id) == (BETA, UNSET)


def test_changed_fields_name_the_topic() -> None:
    assert changed_fields(DocumentChanges(topic_id=None)) == {"topic"}


def test_the_rules_that_forced_a_review_read_back_from_the_log() -> None:
    reviewing, quiet = RuleId(new_id()), RuleId(new_id())
    reports = [
        RuleReport(
            reviewing,
            1,
            "Check",
            RuleScope.SPACE,
            notes=[Note("review", NoteKind.REVIEW, "look at it")],
        ),
        RuleReport(quiet, 1, "Tag", RuleScope.SPACE, notes=[Note("tags", NoteKind.SKIPPED, "x")]),
    ]
    written = RulePlan(DocumentChanges(), None, reports, [], []).to_json()
    assert reviewing_rules(written) == {reviewing}
    assert reviewing_rules(None) == set()
