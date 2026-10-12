from datetime import timedelta

import pytest

from papiq.core.domain.documents import Document
from papiq.core.domain.errors import InvalidTransitionError, ValidationError
from papiq.core.domain.events import DocumentFiled, LaneChanged, NodeCompleted, NodeStarted
from papiq.core.domain.ids import new_id
from papiq.core.domain.pipeline import (
    GRAPH,
    NODES,
    Lane,
    Node,
    NodeResult,
    NodeRun,
    NodeState,
    NodeStatus,
    Outcome,
    Processing,
    ProcessingStatus,
)
from tests import builders
from tests.builders import FAILED, NOW, OK, UNCERTAIN

LATER = NOW + timedelta(seconds=5)


def status(document: Document) -> ProcessingStatus:
    return document.processing.status


def received() -> Document:
    return builders.document(builders.user(), builders.drawer(builders.user()))


def test_the_graph_is_in_topological_order_with_one_source_and_one_sink() -> None:
    assert tuple(Node) == NODES
    assert set(GRAPH) == set(NODES)
    for position, node in enumerate(NODES):
        assert all(NODES.index(needed) < position for needed in node.requires)
    assert Node.RECEIVE.requires == frozenset()
    assert Node.FILE.successors == frozenset()
    assert Node.FILE.ancestors == frozenset(NODES) - {Node.FILE}
    assert Node.RECEIVE.descendants == frozenset(NODES) - {Node.RECEIVE}


def test_ocr_and_pages_run_side_by_side_and_filing_waits_for_both() -> None:
    assert Node.RECEIVE.successors == {Node.OCR, Node.PAGES}
    assert Node.PAGES.requires == {Node.RECEIVE}
    assert Node.PAGES.descendants == {Node.FILE}
    assert Node.FILE.requires == {Node.APPLY_RULES, Node.PAGES}
    assert Node.OCR.descendants == {
        Node.PARSE,
        Node.CLASSIFY,
        Node.EXTRACT_FIELDS,
        Node.APPLY_RULES,
        Node.FILE,
    }
    assert Node.APPLY_RULES.ancestors == {
        Node.RECEIVE,
        Node.OCR,
        Node.PARSE,
        Node.CLASSIFY,
        Node.EXTRACT_FIELDS,
    }


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


def test_node_result_needs_a_reason_unless_ok() -> None:
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


def test_node_run_is_a_log_entry() -> None:
    document = received()
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


def test_node_state_invariants() -> None:
    NodeState()
    NodeState(status=NodeStatus.SKIPPED)
    NodeState(status=NodeStatus.RUNNING, started_at=NOW)
    done = NodeState(status=NodeStatus.DONE, outcome=Outcome.OK, finished_at=NOW)
    assert done.satisfied and not done.open
    assert NodeState(status=NodeStatus.SKIPPED).satisfied
    assert not NodeState().satisfied and NodeState().open
    failed = NodeState(status=NodeStatus.DONE, outcome=Outcome.FAILED, finished_at=NOW)
    assert not failed.satisfied and not failed.open
    with pytest.raises(ValidationError, match="outcome"):
        NodeState(status=NodeStatus.DONE, finished_at=NOW)
    with pytest.raises(ValidationError, match="outcome"):
        NodeState(outcome=Outcome.OK)
    with pytest.raises(ValidationError, match="start"):
        NodeState(status=NodeStatus.RUNNING)
    with pytest.raises(ValidationError, match="end"):
        NodeState(status=NodeStatus.DONE, outcome=Outcome.OK)


def test_processing_state_invariants() -> None:
    fresh = Processing.new()
    assert fresh.due() == (Node.RECEIVE,)
    assert fresh.outcomes == {}
    nodes = dict(fresh.nodes)
    without_pages: dict[Node, NodeState] = {
        node: state for node, state in nodes.items() if node is not Node.PAGES
    }
    with pytest.raises(ValidationError, match="without nodes: pages"):
        Processing(status=ProcessingStatus.PROCESSING, run=1, nodes=without_pages)
    with pytest.raises(ValidationError, match="completed"):
        Processing(status=ProcessingStatus.COMPLETED, run=1, nodes=nodes)
    with pytest.raises(ValidationError, match="failed"):
        Processing(status=ProcessingStatus.FAILED, run=1, nodes=nodes)
    with pytest.raises(ValidationError, match="run"):
        Processing(status=ProcessingStatus.PROCESSING, run=0, nodes=nodes)
    done = {node: NodeState(status=NodeStatus.SKIPPED) for node in NODES}
    with pytest.raises(ValidationError, match="completed"):
        Processing(status=ProcessingStatus.PROCESSING, run=1, nodes=done)
    with pytest.raises(ValidationError, match="review"):
        Processing(status=ProcessingStatus.REVIEW, run=1, nodes={**done, Node.OCR: NodeState()})


def test_received_document_has_ocr_and_pages_due_without_lane() -> None:
    document = received()
    processing = document.processing
    assert processing.status is ProcessingStatus.PROCESSING
    assert processing.run == 1
    assert processing.outcomes == {Node.RECEIVE: Outcome.OK}
    assert processing.nodes[Node.RECEIVE] == NodeState(
        status=NodeStatus.DONE, outcome=Outcome.OK, started_at=NOW, finished_at=NOW
    )
    assert processing.due() == (Node.OCR, Node.PAGES)
    assert document.is_awaiting(Node.OCR, 1) and document.is_awaiting(Node.PAGES, 1)
    assert not document.is_awaiting(Node.PARSE, 1)
    assert document.lane is None
    assert document.title == "scan"


def test_nodes_run_in_graph_order_and_end_green() -> None:
    document = received()
    done = [Node.RECEIVE]
    while due := [node for node in document.processing.due() if document.is_awaiting(node, 1)]:
        document.record_result(due[0], 1, OK, NOW)
        done.append(due[0])
    assert done == list(NODES)
    assert document.processing.status is ProcessingStatus.COMPLETED
    assert document.processing.due() == ()
    assert all(state.status is NodeStatus.DONE for state in document.processing.nodes.values())
    assert document.lane is Lane.GREEN


def test_a_result_names_the_nodes_that_became_due_with_it() -> None:
    document = received()
    assert document.record_result(Node.OCR, 1, OK, NOW) == (Node.PARSE,)
    assert document.record_result(Node.PAGES, 1, OK, NOW) == ()
    assert document.record_result(Node.PARSE, 1, OK, NOW) == (Node.CLASSIFY,)
    document.record_result(Node.CLASSIFY, 1, OK, NOW)
    document.record_result(Node.EXTRACT_FIELDS, 1, OK, NOW)
    assert document.record_result(Node.APPLY_RULES, 1, OK, NOW) == (Node.FILE,)
    assert document.record_result(Node.FILE, 1, OK, NOW) == ()
    assert status(document) is ProcessingStatus.COMPLETED


def test_filing_waits_for_the_pages() -> None:
    document = received()
    for node in (Node.OCR, Node.PARSE, Node.CLASSIFY, Node.EXTRACT_FIELDS):
        document.record_result(node, 1, OK, NOW)
    assert document.record_result(Node.APPLY_RULES, 1, OK, NOW) == ()
    assert status(document) is ProcessingStatus.PROCESSING
    assert document.processing.due() == (Node.PAGES,)
    assert not document.is_awaiting(Node.FILE, 1)
    assert document.record_result(Node.PAGES, 1, OK, NOW) == (Node.FILE,)
    assert document.is_awaiting(Node.FILE, 1)


def test_a_worker_starts_a_due_node() -> None:
    document = received()
    document.start_node(Node.OCR, 1, NOW)
    state = document.processing.nodes[Node.OCR]
    assert state == NodeState(status=NodeStatus.RUNNING, started_at=NOW)
    assert document.processing.running() == (Node.OCR,)
    assert document.processing.due() == (Node.PAGES,)
    assert document.is_awaiting(Node.OCR, 1)
    (event,) = document.pull_events()
    assert isinstance(event, NodeStarted)
    assert (event.node, event.run) == (Node.OCR, 1)

    # Started again after a lost lease; the result keeps the start.
    document.start_node(Node.OCR, 1, LATER)
    assert document.processing.nodes[Node.OCR].started_at == LATER
    document.record_result(Node.OCR, 1, OK, LATER + timedelta(seconds=1))
    assert document.processing.nodes[Node.OCR] == NodeState(
        status=NodeStatus.DONE,
        outcome=Outcome.OK,
        started_at=LATER,
        finished_at=LATER + timedelta(seconds=1),
    )
    with pytest.raises(InvalidTransitionError, match="not due"):
        document.start_node(Node.CLASSIFY, 1, NOW)
    with pytest.raises(InvalidTransitionError, match="not due"):
        document.start_node(Node.OCR, 1, NOW)


def test_uncertain_node_continues_and_waits_yellow_before_filing() -> None:
    document = builders.run_pipeline(received(), {Node.CLASSIFY: UNCERTAIN})
    assert document.processing.status is ProcessingStatus.REVIEW
    assert Node.APPLY_RULES in document.processing.outcomes
    assert Node.FILE not in document.processing.outcomes
    assert document.processing.due() == (Node.FILE,)
    assert document.lane is Lane.YELLOW
    assert not document.is_awaiting(Node.FILE, document.processing.run)


def test_an_uncertain_filing_node_completes_yellow() -> None:
    document = builders.run_pipeline(received(), {Node.FILE: UNCERTAIN})
    assert document.processing.status is ProcessingStatus.COMPLETED
    assert document.lane is Lane.YELLOW


@pytest.mark.parametrize("resume_at", [Node.EXTRACT_FIELDS, Node.APPLY_RULES])
def test_confirming_a_yellow_document_resumes_and_files_it_green(resume_at: Node) -> None:
    document = builders.run_pipeline(received(), {Node.OCR: UNCERTAIN, Node.CLASSIFY: UNCERTAIN})
    run = document.processing.run
    document.pull_events()

    overruled = document.confirm(resume_at, NOW)

    assert overruled == (Node.OCR, Node.CLASSIFY)
    assert document.processing.run == run + 1
    assert document.processing.status is ProcessingStatus.PROCESSING
    assert document.processing.due() == (resume_at,)
    again = {resume_at, *resume_at.descendants}
    assert set(document.processing.outcomes) == set(NODES) - again
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


def test_confirming_a_red_document_takes_over_the_failed_and_unrun_nodes() -> None:
    document = builders.run_pipeline(received(), {Node.OCR: FAILED})
    assert document.processing.nodes[Node.PAGES] == NodeState()  # dropped after the failure
    assert document.confirm(Node.APPLY_RULES, NOW) == (
        Node.OCR,
        Node.PARSE,
        Node.CLASSIFY,
        Node.EXTRACT_FIELDS,
    )
    taken_over = document.processing.nodes[Node.PARSE]
    assert (taken_over.status, taken_over.outcome) == (NodeStatus.DONE, Outcome.OK)
    assert (taken_over.started_at, taken_over.finished_at) == (NOW, NOW)
    # The pages are not needed to resume: they are rendered now instead of taken over.
    assert document.processing.due() == (Node.PAGES, Node.APPLY_RULES)
    builders.run_pipeline(document)
    assert document.lane is Lane.GREEN
    assert document.processing.outcome(Node.PAGES) is Outcome.OK


def test_confirming_repeats_a_node_still_running() -> None:
    document = received()
    document.start_node(Node.PAGES, 1, NOW)
    builders.run_pipeline(document, {Node.OCR: FAILED})
    assert status(document) is ProcessingStatus.FAILED
    assert document.confirm(Node.APPLY_RULES, NOW) == (
        Node.OCR,
        Node.PARSE,
        Node.CLASSIFY,
        Node.EXTRACT_FIELDS,
    )
    assert document.processing.nodes[Node.PAGES] == NodeState()
    assert document.processing.due() == (Node.PAGES, Node.APPLY_RULES)


def test_fields_are_only_extracted_again_from_a_parsed_text() -> None:
    document = builders.run_pipeline(received(), {Node.PARSE: FAILED})
    with pytest.raises(InvalidTransitionError, match="no text"):
        document.confirm(Node.EXTRACT_FIELDS, NOW)


@pytest.mark.parametrize("resume_at", [Node.OCR, Node.CLASSIFY, Node.FILE])
def test_confirmation_resumes_only_after_classification(resume_at: Node) -> None:
    document = builders.run_pipeline(received(), {Node.CLASSIFY: UNCERTAIN})
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
    document = builders.run_pipeline(received(), {Node.CLASSIFY: UNCERTAIN})
    with pytest.raises(InvalidTransitionError, match="confirm them before filing"):
        document.reprocess_from(Node.FILE, NOW)
    document.reprocess_from(Node.APPLY_RULES, NOW)
    builders.run_pipeline(document)
    assert document.processing.status is ProcessingStatus.REVIEW


def test_failed_node_stops_processing_red() -> None:
    document = builders.run_pipeline(received(), {Node.PARSE: FAILED})
    assert document.processing.status is ProcessingStatus.FAILED
    assert document.processing.failed() == (Node.PARSE,)
    assert document.processing.nodes[Node.CLASSIFY] == NodeState()
    assert Node.CLASSIFY not in document.processing.outcomes
    assert document.lane is Lane.RED


def test_a_node_still_running_after_a_failure_finishes_but_nothing_new_starts() -> None:
    document = received()
    document.start_node(Node.PAGES, 1, NOW)
    assert document.record_result(Node.OCR, 1, FAILED, NOW) == ()
    assert status(document) is ProcessingStatus.FAILED
    assert document.is_awaiting(Node.PAGES, 1)
    assert not document.is_awaiting(Node.PARSE, 1)
    assert document.record_result(Node.PAGES, 1, OK, NOW) == ()
    assert status(document) is ProcessingStatus.FAILED
    assert document.lane is Lane.RED
    assert document.processing.outcome(Node.PAGES) is Outcome.OK

    waiting = received()
    waiting.record_result(Node.OCR, 1, FAILED, NOW)
    assert not waiting.is_awaiting(Node.PAGES, 1)
    with pytest.raises(InvalidTransitionError, match="not due"):
        waiting.record_result(Node.PAGES, 1, OK, NOW)


@pytest.mark.parametrize(
    ("node", "run"),
    [(Node.PARSE, 1), (Node.RECEIVE, 1), (Node.OCR, 2), (Node.OCR, 0)],
)
def test_only_a_due_node_of_the_current_run_is_accepted(node: Node, run: int) -> None:
    document = received()
    assert not document.is_awaiting(node, run)
    with pytest.raises(InvalidTransitionError, match="not due"):
        document.record_result(node, run, OK, NOW)


def test_completed_document_accepts_no_more_results() -> None:
    document = builders.run_pipeline(received())
    with pytest.raises(InvalidTransitionError):
        document.record_result(Node.FILE, 1, OK, NOW)


def test_retry_repeats_the_failed_node_and_continues() -> None:
    document = builders.run_pipeline(received(), {Node.CLASSIFY: FAILED})
    assert document.retry(NOW) == (Node.CLASSIFY,)
    assert document.processing.status is ProcessingStatus.PROCESSING
    assert document.processing.run == 2
    assert document.lane is None
    assert Node.CLASSIFY not in document.processing.outcomes
    assert document.processing.outcomes[Node.PARSE] is Outcome.OK
    assert document.processing.outcomes[Node.PAGES] is Outcome.OK
    assert not document.is_awaiting(Node.CLASSIFY, 1)

    builders.run_pipeline(document)
    assert status(document) is ProcessingStatus.COMPLETED
    assert document.lane is Lane.GREEN


def test_retry_repeats_every_failed_node() -> None:
    document = received()
    document.start_node(Node.PAGES, 1, NOW)
    document.record_result(Node.OCR, 1, FAILED, NOW)
    document.record_result(Node.PAGES, 1, FAILED, NOW)
    assert document.processing.failed() == (Node.OCR, Node.PAGES)
    assert document.retry(NOW) == (Node.OCR, Node.PAGES)
    builders.run_pipeline(document)
    assert document.lane is Lane.GREEN


def test_retry_repeats_a_node_still_running() -> None:
    document = received()
    document.start_node(Node.PAGES, 1, NOW)
    document.record_result(Node.OCR, 1, FAILED, NOW)
    assert document.retry(NOW) == (Node.OCR, Node.PAGES)
    assert document.processing.nodes[Node.PAGES] == NodeState()
    assert not document.is_awaiting(Node.PAGES, 1)


def test_retry_needs_failed_processing() -> None:
    document = received()
    with pytest.raises(InvalidTransitionError, match="only failed"):
        document.retry(NOW)
    builders.run_pipeline(document)
    with pytest.raises(InvalidTransitionError, match="only failed"):
        document.retry(NOW)


def test_reprocess_from_a_node_discards_the_results_after_it() -> None:
    document = builders.run_pipeline(received(), {Node.EXTRACT_FIELDS: UNCERTAIN})
    assert document.lane is Lane.YELLOW
    assert document.reprocess_from(Node.CLASSIFY, NOW) == (Node.CLASSIFY,)
    assert document.processing.run == 2
    assert set(document.processing.outcomes) == {Node.RECEIVE, Node.OCR, Node.PAGES, Node.PARSE}
    assert document.lane is None
    builders.run_pipeline(document)
    assert document.lane is Lane.GREEN


def test_reprocessing_the_pages_leaves_the_text_branch_alone() -> None:
    document = builders.run_pipeline(received())
    assert document.reprocess_from(Node.PAGES, NOW) == (Node.PAGES,)
    assert set(document.processing.outcomes) == set(NODES) - {Node.PAGES, Node.FILE}
    assert document.record_result(Node.PAGES, 2, OK, NOW) == (Node.FILE,)


def test_reprocess_rules() -> None:
    document = received()
    with pytest.raises(InvalidTransitionError, match="being processed"):
        document.reprocess_from(Node.OCR, NOW)

    builders.run_pipeline(document, {Node.PARSE: FAILED})
    with pytest.raises(InvalidTransitionError, match="receive"):
        document.reprocess_from(Node.RECEIVE, NOW)
    with pytest.raises(InvalidTransitionError, match="stopped at parse; cannot skip"):
        document.reprocess_from(Node.CLASSIFY, NOW)
    with pytest.raises(InvalidTransitionError, match="stopped at parse; cannot skip"):
        document.reprocess_from(Node.PAGES, NOW)
    assert document.reprocess_from(Node.OCR, NOW) == (Node.OCR,)


def test_a_skipped_node_counts_as_done_for_the_nodes_after_it() -> None:
    document = received()
    document.processing.nodes[Node.PAGES] = NodeState(status=NodeStatus.SKIPPED)
    assert document.processing.due() == (Node.OCR,)
    builders.run_pipeline(document)
    assert status(document) is ProcessingStatus.COMPLETED
    assert document.lane is Lane.GREEN
    assert Node.PAGES not in document.processing.outcomes
    assert document.processing.nodes[Node.PAGES].status is NodeStatus.SKIPPED

    # Reprocessing from the skipped node runs it.
    assert document.reprocess_from(Node.PAGES, NOW) == (Node.PAGES,)


def test_events_follow_the_state_changes() -> None:
    document = received()
    builders.run_pipeline(document, {Node.CLASSIFY: UNCERTAIN})
    events = document.pull_events()
    completed = [event for event in events if isinstance(event, NodeCompleted)]
    assert [event.node for event in completed] == list(NODES[1:-1])
    assert completed[3].outcome is Outcome.UNCERTAIN
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
    document = received()
    builders.run_pipeline(document, {Node.OCR: FAILED})
    events = document.pull_events()
    assert [type(event) for event in events] == [NodeCompleted, LaneChanged]
    assert not any(isinstance(event, DocumentFiled) for event in events)


def test_event_ids_are_unique() -> None:
    document = received()
    document.start_node(Node.OCR, 1, NOW)
    builders.run_pipeline(document)
    ids = [event.id for event in document.pull_events()]
    assert len(set(ids)) == len(ids)
    assert new_id() not in ids
