"""The first run and the verdicts per field (`domain.first_runs`)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from lekto.core.domain.classification import (
    CONTACT,
    DOCUMENT_DATE,
    DOCUMENT_TYPE,
    SPACE,
    TAGS,
    TITLE,
    TOPIC,
    Candidate,
    CandidateSource,
    FieldCheck,
    field_key,
)
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.first_runs import (
    JUDGED_FIELDS,
    Decision,
    FieldVerdict,
    FirstRun,
    Verdict,
    decided_fields,
    early_verdicts,
    judge_fields,
    values_of,
)
from lekto.core.domain.ids import ContactId, DocumentId, FieldId, TagId, new_id
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.pipeline import (
    PERSON,
    RULES_CHANGE,
    Node,
    NodeResult,
    NodeRun,
    Outcome,
)
from lekto.core.domain.reasons import written
from tests import builders
from tests.builders import NOW

ID = DocumentId(new_id())
A, B, C = (str(new_id()) for _ in range(3))
SECOND = timedelta(seconds=1)


def entry(
    node: Node,
    *,
    run: int = 1,
    at: timedelta = timedelta(0),
    took: timedelta = SECOND,
    model_version: str | None = None,
) -> NodeRun:
    return NodeRun(
        document_id=ID,
        node=node,
        run=run,
        result=NodeResult(outcome=Outcome.OK, model_version=model_version),
        pipeline_version="test",
        started_at=NOW + at,
        duration=took,
    )


def ok(name: str, value: JsonValue, *candidates: Candidate) -> FieldCheck:
    return FieldCheck(
        field=name, outcome=Outcome.OK, confidence=0.9, value=value, candidates=candidates
    )


def uncertain(name: str, suggestion: JsonValue = None, *candidates: Candidate) -> FieldCheck:
    return FieldCheck(
        field=name,
        outcome=Outcome.UNCERTAIN,
        confidence=0.4,
        reasons=(written("unsure"),),
        suggestion=suggestion,
        candidates=candidates,
    )


def named(value: JsonValue, *signals: Node, names: bool = True) -> Candidate:
    return Candidate(
        value=value,
        label="label",
        sources=tuple(CandidateSource(signal=signal.value, names=names) for signal in signals),
    )


def judge(
    name: str,
    before: JsonValue,
    after: JsonValue,
    check: FieldCheck | None = None,
) -> FieldVerdict | None:
    verdicts = judge_fields(
        ID,
        Decision.INBOX,
        fields={name},
        before={name: before},
        after={name: after},
        checks={} if check is None else {name: check},
        decided_at=NOW,
    )
    return verdicts[0] if verdicts else None


# --- the first run ------------------------------------------------------------------------------


def test_the_first_run_spans_from_receiving_to_the_stop_and_sums_its_steps() -> None:
    log = [
        entry(Node.RECEIVE, took=2 * SECOND),
        entry(Node.OCR, at=10 * SECOND, took=30 * SECOND),
        entry(Node.SIGNAL_LLM, at=50 * SECOND, took=20 * SECOND),
        entry(Node.SIGNAL_CLASSIFIER, at=50 * SECOND, took=SECOND),
    ]
    run = FirstRun.of(ID, log, NOW + 90 * SECOND)

    assert (run.started_at, run.stopped_at) == (NOW, NOW + 90 * SECOND)
    assert run.duration == 90 * SECOND
    assert run.work == 53 * SECOND  # side by side, each counted
    assert run.steps == {
        Node.RECEIVE: 2 * SECOND,
        Node.OCR: 30 * SECOND,
        Node.SIGNAL_LLM: 20 * SECOND,
        Node.SIGNAL_CLASSIFIER: SECOND,
    }


def test_the_first_run_leaves_out_later_runs_people_and_changes() -> None:
    log = [
        entry(Node.RECEIVE),
        entry(Node.OCR, took=5 * SECOND),
        entry(Node.APPLY_RULES, model_version=RULES_CHANGE, took=SECOND),
        entry(Node.APPLY_RULES, run=2, model_version=PERSON),
        entry(Node.FILE, run=2, took=4 * SECOND),
    ]
    run = FirstRun.of(ID, log, NOW + 10 * SECOND)

    assert run.steps == {Node.RECEIVE: SECOND, Node.OCR: 5 * SECOND}


def test_a_node_written_twice_in_the_first_run_counts_both_times() -> None:
    log = [entry(Node.RECEIVE), entry(Node.PAGES, took=SECOND), entry(Node.PAGES, took=SECOND)]
    assert FirstRun.of(ID, log, NOW + 5 * SECOND).steps[Node.PAGES] == 2 * SECOND


def test_a_first_run_needs_its_entries_and_stops_after_it_began() -> None:
    with pytest.raises(ValidationError):
        FirstRun.of(ID, [entry(Node.OCR, run=2)], NOW)
    with pytest.raises(ValidationError):
        FirstRun(document_id=ID, started_at=NOW, stopped_at=NOW - SECOND)
    with pytest.raises(ValidationError):
        FirstRun(document_id=ID, started_at=NOW, stopped_at=NOW, steps={Node.OCR: -SECOND})


# --- verdicts -----------------------------------------------------------------------------------


def test_a_value_the_person_keeps_is_taken_over() -> None:
    verdict = judge(CONTACT, A, A, ok(CONTACT, A))
    assert verdict is not None and verdict.verdict is Verdict.TAKEN


def test_a_value_the_person_replaces_or_removes_is_corrected() -> None:
    assert getattr(judge(CONTACT, A, B, ok(CONTACT, A)), "verdict", None) is Verdict.CORRECTED
    assert getattr(judge(CONTACT, A, None, ok(CONTACT, A)), "verdict", None) is Verdict.CORRECTED


def test_a_suggestion_the_person_takes_is_accepted_another_value_corrects_it() -> None:
    check = uncertain(CONTACT, A)
    assert getattr(judge(CONTACT, None, A, check), "verdict", None) is Verdict.ACCEPTED
    assert getattr(judge(CONTACT, None, B, check), "verdict", None) is Verdict.CORRECTED
    assert getattr(judge(CONTACT, None, None, check), "verdict", None) is Verdict.CORRECTED


def test_a_value_where_the_automation_had_none_is_added() -> None:
    assert getattr(judge(TOPIC, None, A, uncertain(TOPIC)), "verdict", None) is Verdict.ADDED
    assert getattr(judge(TOPIC, None, A), "verdict", None) is Verdict.ADDED


def test_a_field_empty_on_every_side_gets_no_verdict() -> None:
    assert judge(TOPIC, None, None, uncertain(TOPIC)) is None
    assert judge(TAGS, [], [], ok(TAGS, [])) is None


def test_a_value_a_rule_set_for_an_uncertain_field_counts_as_the_automations() -> None:
    assert getattr(judge(CONTACT, A, A, uncertain(CONTACT, B)), "verdict", None) is Verdict.TAKEN


def test_the_space_of_an_uncertain_check_is_where_it_landed_not_the_automations() -> None:
    check = uncertain(SPACE, B)
    assert getattr(judge(SPACE, A, A, check), "verdict", None) is Verdict.CORRECTED
    assert getattr(judge(SPACE, A, B, check), "verdict", None) is Verdict.ACCEPTED
    assert getattr(judge(SPACE, A, A, ok(SPACE, A)), "verdict", None) is Verdict.TAKEN


def test_tags_compare_as_a_set() -> None:
    verdict = judge(TAGS, [A, B], [B, A], ok(TAGS, [A, B]))
    assert verdict is not None and verdict.verdict is Verdict.TAKEN
    assert getattr(judge(TAGS, [A, B], [A], ok(TAGS, [A, B])), "verdict", None) is (
        Verdict.CORRECTED
    )


def test_each_signal_tells_whether_it_named_the_persons_value() -> None:
    check = uncertain(
        CONTACT,
        A,
        named(A, Node.SIGNAL_LLM, Node.SIGNAL_FACTS),
        named(B, Node.SIGNAL_CLASSIFIER, Node.SIGNAL_LLM),
        named(C, Node.SIGNAL_NEIGHBOURS, names=False),
    )
    verdict = judge(CONTACT, None, A, check)

    assert verdict is not None
    assert verdict.signals == {
        Node.SIGNAL_LLM: True,  # its best: A
        Node.SIGNAL_FACTS: True,
        Node.SIGNAL_CLASSIFIER: False,
    }


def test_a_name_that_does_not_exist_is_no_value_named() -> None:
    check = uncertain(CONTACT, None, named(None, Node.SIGNAL_LLM))
    verdict = judge(CONTACT, None, A, check)
    assert verdict is not None and verdict.signals == {}


def test_only_fields_with_one_value_carry_signals() -> None:
    check = ok(TAGS, [A], named(A, Node.SIGNAL_LLM))
    verdict = judge(TAGS, [A], [A], check)
    assert verdict is not None and verdict.signals == {}
    with pytest.raises(ValidationError):
        FieldVerdict(
            document_id=ID,
            field=TAGS,
            verdict=Verdict.TAKEN,
            decided_at=NOW,
            decision=Decision.INBOX,
            signals={Node.SIGNAL_LLM: True},
        )


def test_a_verdict_is_on_a_judged_field() -> None:
    with pytest.raises(ValidationError):
        FieldVerdict(
            document_id=ID,
            field=TITLE,
            verdict=Verdict.TAKEN,
            decided_at=NOW,
            decision=Decision.CHANGE,
        )
    custom = field_key(FieldId(new_id()))
    verdict = FieldVerdict(
        document_id=ID,
        field=custom,
        verdict=Verdict.ADDED,
        decided_at=NOW,
        decision=Decision.CHANGE,
    )
    assert verdict.field == custom


def test_early_verdicts_name_each_field_decided_before_the_stop() -> None:
    verdicts = early_verdicts(ID, Decision.CHANGE, {DOCUMENT_DATE, CONTACT}, NOW)
    assert [(item.field, item.verdict) for item in verdicts] == [
        (CONTACT, Verdict.EARLY),
        (DOCUMENT_DATE, Verdict.EARLY),
    ]


# --- what a decision covers ---------------------------------------------------------------------

CUSTOM = field_key(FieldId(new_id()))
LAPSED = field_key(FieldId(new_id()))


def test_confirming_in_the_inbox_decides_every_field_that_applies() -> None:
    fields = decided_fields(Decision.INBOX, before={LAPSED: 3}, given=(), applying={CUSTOM})
    assert fields == frozenset({*JUDGED_FIELDS, CUSTOM})


def test_a_change_decides_what_it_sets_and_what_the_automation_set_not_the_space() -> None:
    before: dict[str, JsonValue] = {
        CONTACT: A,
        DOCUMENT_TYPE: None,
        TOPIC: None,
        DOCUMENT_DATE: "2026-10-01",
        SPACE: B,
        TAGS: [],
        LAPSED: 3,
    }
    fields = decided_fields(
        Decision.CHANGE, before=before, given={TOPIC, TITLE, CUSTOM}, applying={CUSTOM}
    )
    assert fields == frozenset({CONTACT, DOCUMENT_DATE, TOPIC, CUSTOM})


def test_a_move_decides_the_space() -> None:
    assert decided_fields(Decision.MOVE, before={CONTACT: A}, given=(), applying=()) == {SPACE}


def test_the_values_are_the_checks_json_without_tags_set_by_hand() -> None:
    owner = builders.user()
    document = builders.processed(owner, builders.personal_space(owner))
    contact, automatic, manual = ContactId(new_id()), TagId(new_id()), TagId(new_id())
    field = FieldId(new_id())
    document.contact_id = contact
    document.document_date = date(2026, 10, 1)
    document.tag_ids = {automatic, manual}
    document.fields = {field: Decimal("12.50")}

    values = values_of(document, manual={manual})

    assert values == {
        CONTACT: str(contact),
        DOCUMENT_TYPE: None,
        TOPIC: None,
        DOCUMENT_DATE: "2026-10-01",
        SPACE: str(document.space_id),
        TAGS: [str(automatic)],
        field_key(field): "12.50",
    }
