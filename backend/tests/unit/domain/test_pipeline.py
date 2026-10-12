from datetime import timedelta

import pytest

from papiq.core.domain.documents import Document
from papiq.core.domain.errors import InvalidTransitionError, ValidationError
from papiq.core.domain.events import DocumentFiled, LaneChanged, NodeCompleted
from papiq.core.domain.ids import new_id
from papiq.core.domain.pipeline import (
    PIPELINE,
    Lane,
    Node,
    NodeResult,
    NodeRun,
    Outcome,
    ProcessingStatus,
)
from tests import builders
from tests.builders import FAILED, NOW, OK, UNCERTAIN


def status(document: Document) -> ProcessingStatus:
    return document.processing.status


def test_steps_have_a_fixed_order() -> None:
    assert PIPELINE == (
        Node.RECEIVE,
        Node.OCR,
        Node.PARSE,
        Node.CLASSIFY,
        Node.EXTRACT_FIELDS,
        Node.APPLY_RULES,
        Node.FILE,
    )
    assert Node.RECEIVE.next is Node.OCR
    assert Node.FILE.next is None


@pytest.mark.parametrize(
    ("outcomes", "lane"),
    [
        ([], Lane.GREEN),
        ([Outcome.OK, Outcome.OK], Lane.GREEN),
        ([Outcome.OK, Outcome.UNCERTAIN, Outcome.OK], Lane.YELLOW),
        ([Outcome.UNCERTAIN, Outcome.FAILED], Lane.RED),
        ([Outcome.OK, Outcome.FAILED], Lane.RED),
    ],
)
def test_lane_is_the_worst_outcome(outcomes: list[Outcome], lane: Lane) -> None:
    assert Lane.from_outcomes(outcomes) is lane


def test_step_result_needs_a_reason_unless_ok() -> None:
    NodeResult(outcome=Outcome.OK)
    for outcome in (Outcome.UNCERTAIN, Outcome.FAILED):
        with pytest.raises(ValidationError, match="reason"):
            NodeResult(outcome=outcome)
        with pytest.raises(ValidationError, match="reason"):
            NodeResult(outcome=outcome, reason="  ")


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_is_between_zero_and_one(confidence: float) -> None:
    with pytest.raises(ValidationError, match="confidence"):
        NodeResult(outcome=Outcome.OK, confidence=confidence)


def test_step_run_is_a_log_entry() -> None:
    document = builders.document(builders.user(), builders.drawer(builders.user()))
    run = NodeRun(
        document_id=document.id,
        node=Node.OCR,
        run=1,
        result=UNCERTAIN,
        pipeline_version="0.1.0",
        started_at=NOW,
        duration=timedelta(seconds=3),
    )
    assert run.result.reason == "new contact"
    with pytest.raises(ValidationError):
        NodeRun(
            document_id=document.id,
            node=Node.OCR,
            run=1,
            result=OK,
            pipeline_version="0.1.0",
            started_at=NOW,
            duration=timedelta(seconds=-1),
        )


def test_received_document_waits_for_ocr_without_lane() -> None:
    document = builders.document(builders.user(), builders.drawer(builders.user()))
    assert document.processing.status is ProcessingStatus.PROCESSING
    assert document.processing.current_node is Node.OCR
    assert document.processing.run == 1
    assert document.processing.outcomes == {Node.RECEIVE: Outcome.OK}
    assert document.lane is None
    assert document.title == "scan"


def test_steps_run_in_order_and_end_green() -> None:
    document = builders.document(builders.user(), builders.drawer(builders.user()))
    due = [Node.OCR]
    while (node := due[-1]) is not None:
        following = document.record_result(node, 1, OK, NOW)
        due.append(following)  # type: ignore[arg-type]
    assert due == [*PIPELINE[1:], None]
    assert document.processing.status is ProcessingStatus.COMPLETED
    assert document.processing.current_node is None
    assert document.lane is Lane.GREEN


def test_uncertain_step_continues_and_waits_yellow_before_filing() -> None:
    document = builders.run_pipeline(
        builders.document(builders.user(), builders.drawer(builders.user())),
        {Node.CLASSIFY: UNCERTAIN},
    )
    assert document.processing.status is ProcessingStatus.REVIEW
    assert document.processing.current_node is Node.FILE
    assert Node.APPLY_RULES in document.processing.outcomes
    assert Node.FILE not in document.processing.outcomes
    assert document.lane is Lane.YELLOW
    assert not document.is_awaiting(Node.FILE, document.processing.run)


def test_an_uncertain_filing_step_completes_yellow() -> None:
    document = builders.run_pipeline(
        builders.document(builders.user(), builders.drawer(builders.user())),
        {Node.FILE: UNCERTAIN},
    )
    assert document.processing.status is ProcessingStatus.COMPLETED
    assert document.lane is Lane.YELLOW


@pytest.mark.parametrize("resume_at", [Node.EXTRACT_FIELDS, Node.APPLY_RULES])
def test_confirming_a_yellow_document_resumes_and_files_it_green(resume_at: Node) -> None:
    document = builders.run_pipeline(
        builders.document(builders.user(), builders.drawer(builders.user())),
        {Node.OCR: UNCERTAIN, Node.CLASSIFY: UNCERTAIN},
    )
    run = document.processing.run
    document.pull_events()

    overruled = document.confirm(resume_at, NOW)

    assert overruled == (Node.OCR, Node.CLASSIFY)
    assert document.processing.run == run + 1
    assert document.processing.status is ProcessingStatus.PROCESSING
    assert document.processing.current_node is resume_at
    assert set(document.processing.outcomes) == set(PIPELINE[: resume_at.position])
    assert set(document.processing.outcomes.values()) == {Outcome.OK}
    assert document.lane is None
    (event,) = document.pull_events()
    assert isinstance(event, LaneChanged)
    assert (event.old, event.new) == (Lane.YELLOW, None)

    builders.run_pipeline(document)
    finished = document.processing
    assert finished.status is ProcessingStatus.COMPLETED
    assert document.lane is Lane.GREEN
    assert any(isinstance(event, DocumentFiled) for event in document.pull_events())


def test_confirming_a_red_document_takes_over_the_failed_steps() -> None:
    document = builders.run_pipeline(
        builders.document(builders.user(), builders.drawer(builders.user())),
        {Node.OCR: FAILED},
    )
    assert document.confirm(Node.APPLY_RULES, NOW) == (
        Node.OCR,
        Node.PARSE,
        Node.CLASSIFY,
        Node.EXTRACT_FIELDS,
    )
    builders.run_pipeline(document)
    assert document.lane is Lane.GREEN


def test_fields_are_only_extracted_again_from_a_parsed_text() -> None:
    document = builders.run_pipeline(
        builders.document(builders.user(), builders.drawer(builders.user())),
        {Node.PARSE: FAILED},
    )
    with pytest.raises(InvalidTransitionError, match="no text"):
        document.confirm(Node.EXTRACT_FIELDS, NOW)


@pytest.mark.parametrize("resume_at", [Node.OCR, Node.CLASSIFY, Node.FILE])
def test_confirmation_resumes_only_after_classification(resume_at: Node) -> None:
    document = builders.run_pipeline(
        builders.document(builders.user(), builders.drawer(builders.user())),
        {Node.CLASSIFY: UNCERTAIN},
    )
    with pytest.raises(InvalidTransitionError, match="resumes with"):
        document.confirm(resume_at, NOW)


def test_only_documents_in_the_inbox_are_confirmed() -> None:
    owner = builders.user()
    processing = builders.document(owner, builders.drawer(owner))
    green = builders.run_pipeline(builders.document(owner, builders.drawer(owner)))
    for document in (processing, green):
        with pytest.raises(InvalidTransitionError, match="not waiting for confirmation"):
            document.confirm(Node.APPLY_RULES, NOW)


def test_uncertain_results_are_not_filed_by_reprocessing() -> None:
    document = builders.run_pipeline(
        builders.document(builders.user(), builders.drawer(builders.user())),
        {Node.CLASSIFY: UNCERTAIN},
    )
    with pytest.raises(InvalidTransitionError, match="confirm them before filing"):
        document.reprocess_from(Node.FILE, NOW)
    document.reprocess_from(Node.APPLY_RULES, NOW)
    builders.run_pipeline(document)
    assert document.processing.status is ProcessingStatus.REVIEW


def test_failed_step_stops_processing_red() -> None:
    document = builders.run_pipeline(
        builders.document(builders.user(), builders.drawer(builders.user())),
        {Node.PARSE: FAILED},
    )
    assert document.processing.status is ProcessingStatus.FAILED
    assert document.processing.current_node is Node.PARSE
    assert Node.CLASSIFY not in document.processing.outcomes
    assert document.lane is Lane.RED


@pytest.mark.parametrize(
    ("node", "run"),
    [(Node.PARSE, 1), (Node.RECEIVE, 1), (Node.OCR, 2), (Node.OCR, 0)],
)
def test_only_the_due_step_of_the_current_run_is_accepted(node: Node, run: int) -> None:
    document = builders.document(builders.user(), builders.drawer(builders.user()))
    assert not document.is_awaiting(node, run)
    with pytest.raises(InvalidTransitionError, match="not due"):
        document.record_result(node, run, OK, NOW)


def test_completed_document_accepts_no_more_results() -> None:
    document = builders.run_pipeline(
        builders.document(builders.user(), builders.drawer(builders.user()))
    )
    with pytest.raises(InvalidTransitionError):
        document.record_result(Node.FILE, 1, OK, NOW)


def test_retry_repeats_the_failed_step_and_continues() -> None:
    document = builders.run_pipeline(
        builders.document(builders.user(), builders.drawer(builders.user())),
        {Node.CLASSIFY: FAILED},
    )
    assert document.retry(NOW) is Node.CLASSIFY
    assert document.processing.status is ProcessingStatus.PROCESSING
    assert document.processing.run == 2
    assert document.lane is None
    assert Node.CLASSIFY not in document.processing.outcomes
    assert document.processing.outcomes[Node.PARSE] is Outcome.OK
    assert not document.is_awaiting(Node.CLASSIFY, 1)

    builders.run_pipeline(document)
    assert status(document) is ProcessingStatus.COMPLETED
    assert document.lane is Lane.GREEN


def test_retry_needs_failed_processing() -> None:
    document = builders.document(builders.user(), builders.drawer(builders.user()))
    with pytest.raises(InvalidTransitionError, match="only failed"):
        document.retry(NOW)
    builders.run_pipeline(document)
    with pytest.raises(InvalidTransitionError, match="only failed"):
        document.retry(NOW)


def test_reprocess_from_a_step_discards_later_results() -> None:
    document = builders.run_pipeline(
        builders.document(builders.user(), builders.drawer(builders.user())),
        {Node.EXTRACT_FIELDS: UNCERTAIN},
    )
    assert document.lane is Lane.YELLOW
    assert document.reprocess_from(Node.CLASSIFY, NOW) is Node.CLASSIFY
    assert document.processing.run == 2
    assert set(document.processing.outcomes) == {Node.RECEIVE, Node.OCR, Node.PARSE}
    assert document.lane is None
    builders.run_pipeline(document)
    assert document.lane is Lane.GREEN


def test_reprocess_rules() -> None:
    document = builders.document(builders.user(), builders.drawer(builders.user()))
    with pytest.raises(InvalidTransitionError, match="being processed"):
        document.reprocess_from(Node.OCR, NOW)

    builders.run_pipeline(document, {Node.PARSE: FAILED})
    with pytest.raises(InvalidTransitionError, match="receive"):
        document.reprocess_from(Node.RECEIVE, NOW)
    with pytest.raises(InvalidTransitionError, match="cannot skip"):
        document.reprocess_from(Node.CLASSIFY, NOW)
    assert document.reprocess_from(Node.OCR, NOW) is Node.OCR


def test_events_follow_the_state_changes() -> None:
    document = builders.document(builders.user(), builders.drawer(builders.user()))
    builders.run_pipeline(document, {Node.CLASSIFY: UNCERTAIN})
    events = document.pull_events()
    completed = [event for event in events if isinstance(event, NodeCompleted)]
    assert [event.node for event in completed] == list(PIPELINE[1:-1])
    assert completed[2].outcome is Outcome.UNCERTAIN
    assert not any(isinstance(event, DocumentFiled) for event in events)
    assert [type(event) for event in events[-2:]] == [NodeCompleted, LaneChanged]
    lane_changed = events[-1]
    assert isinstance(lane_changed, LaneChanged)
    assert (lane_changed.old, lane_changed.new) == (None, Lane.YELLOW)
    assert all(event.document_id == document.id for event in events)
    assert document.pull_events() == []

    document.reprocess_from(Node.APPLY_RULES, NOW)
    (event,) = document.pull_events()
    assert isinstance(event, LaneChanged)
    assert (event.old, event.new) == (Lane.YELLOW, None)


def test_failure_records_lane_red_without_filing() -> None:
    document = builders.document(builders.user(), builders.drawer(builders.user()))
    builders.run_pipeline(document, {Node.OCR: FAILED})
    events = document.pull_events()
    assert [type(event) for event in events] == [NodeCompleted, LaneChanged]
    assert not any(isinstance(event, DocumentFiled) for event in events)


def test_event_ids_are_unique() -> None:
    document = builders.document(builders.user(), builders.drawer(builders.user()))
    builders.run_pipeline(document)
    ids = [event.id for event in document.pull_events()]
    assert len(set(ids)) == len(ids)
    assert new_id() not in ids
