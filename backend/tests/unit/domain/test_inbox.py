"""The inbox in the domain: when processing makes a document new (Tobi, 17./18.10.2026)."""

from datetime import datetime, timedelta

from papiq.core.domain.documents import Document, DocumentChanges, metadata_digest
from papiq.core.domain.ids import ContactId, TagId, new_id
from papiq.core.domain.pipeline import Lane, Node, NodeResult, ProcessingStatus
from tests import builders
from tests.builders import FAILED, NOW, OK, UNCERTAIN

LATER = NOW + timedelta(hours=1)
LAST = NOW + timedelta(hours=2)
CONTACT = ContactId(new_id())


def finish(
    document: Document,
    now: datetime,
    results: dict[Node, NodeResult] | None = None,
    *,
    change: DocumentChanges | None = None,
) -> Document:
    """Run the due nodes at `now`, one at a time in graph order, until processing stops; the
    judge applies `change` (the metadata it decides)."""
    results = results or {}
    while True:
        run = document.processing.run
        due = [node for node in document.processing.due() if document.is_awaiting(node, run)]
        if not due:
            return document
        if due[0] is Node.JUDGE and change is not None:
            document.apply_changes(change, {}, now)
        document.record_result(due[0], run, results.get(due[0], OK), now)


def green() -> Document:
    """A document its first run made green and new at `NOW`."""
    return finish(builders.received(), NOW, change=DocumentChanges(contact_id=CONTACT))


def test_the_first_run_ending_green_makes_a_document_new() -> None:
    document = green()
    assert document.lane is Lane.GREEN
    assert document.new_at == NOW


def test_a_first_run_ending_yellow_or_red_makes_nothing_new() -> None:
    for result in (UNCERTAIN, FAILED):
        document = finish(builders.received(), NOW, {Node.JUDGE: result})
        assert document.lane is not Lane.GREEN
        assert document.new_at is None


def test_reprocessing_makes_it_new_again_only_if_the_metadata_changed() -> None:
    document = green()
    document.reprocess_from(Node.JUDGE, LATER)
    finish(document, LATER, change=DocumentChanges(contact_id=CONTACT))
    assert document.new_at == NOW  # the same contact: unchanged
    for change in (
        DocumentChanges(tag_ids=frozenset({TagId(new_id())})),
        DocumentChanges(contact_id=None),
    ):
        document.reprocess_from(Node.JUDGE, LAST)
        finish(document, LAST, change=change)
        assert document.new_at == LAST


def test_a_retry_from_red_ending_green_by_itself_compares_with_before() -> None:
    """A retry is a run like a reprocessing: new only if the metadata changed in it."""
    at_filing = finish(builders.received(), NOW, {Node.FILE: FAILED}, change=DocumentChanges())
    assert (at_filing.lane, at_filing.new_at) == (Lane.RED, None)
    at_filing.retry(LATER)
    finish(at_filing, LATER)
    assert (at_filing.lane, at_filing.new_at) == (Lane.GREEN, None)

    at_ocr = finish(builders.received(), NOW, {Node.OCR: FAILED})
    at_ocr.retry(LATER)
    finish(at_ocr, LATER, change=DocumentChanges(contact_id=CONTACT))
    assert (at_ocr.lane, at_ocr.new_at) == (Lane.GREEN, LATER)


def test_a_confirmed_document_is_new_for_no_one() -> None:
    """Confirming out of yellow or red, by the owner or an admin, takes away what is new, and
    the run it starts makes nothing new, whatever the rules change in it."""
    document = green()
    document.reprocess_from(Node.JUDGE, LATER)
    finish(document, LATER, {Node.JUDGE: UNCERTAIN})
    assert (document.lane, document.new_at) == (Lane.YELLOW, NOW)
    document.confirm(Node.APPLY_RULES, LAST)
    assert document.new_at is None
    assert document.processing.decided
    document.apply_changes(DocumentChanges(contact_id=None), {}, LAST)  # as the rules may
    finish(document, LAST)
    assert (document.lane, document.new_at) == (Lane.GREEN, None)


def test_metadata_a_person_sets_during_a_run_is_a_decision_in_it() -> None:
    """Metadata taken over from the source system, or set by a person while processing runs:
    the run ends green without making the document new."""
    document = builders.received()
    document.mark_confirmed(NOW)
    assert document.processing.decided
    finish(document, NOW, change=DocumentChanges(contact_id=CONTACT))
    assert (document.lane, document.new_at) == (Lane.GREEN, None)
    document.reprocess_from(Node.JUDGE, LATER)
    assert not document.processing.decided  # a new run
    finish(document, LATER, change=DocumentChanges(contact_id=None))
    assert document.new_at == LATER


def test_outside_a_run_confirming_metadata_decides_nothing_for_the_next() -> None:
    document = green()
    document.mark_confirmed(LATER)
    assert document.processing.status is ProcessingStatus.COMPLETED
    assert not document.processing.decided


def test_a_run_started_before_the_inbox_makes_nothing_new() -> None:
    """Without a baseline (a run started before 0.4), only a first run makes a document
    new."""
    document = green()
    document.new_at = None
    document.reprocess_from(Node.JUDGE, LATER)
    document.processing.baseline = None
    finish(document, LATER, change=DocumentChanges(contact_id=None))
    assert document.new_at is None


def test_the_digest_covers_what_a_person_confirms() -> None:
    document = green()
    digest = metadata_digest(document)
    assert digest == metadata_digest(green())  # the same values
    document.apply_changes(DocumentChanges(title="Another title"), {}, NOW)
    assert metadata_digest(document) == digest  # the title is not confirmed by itself
    for change in (
        DocumentChanges(contact_id=None),
        DocumentChanges(tag_ids=frozenset({TagId(new_id())})),
        DocumentChanges(document_date=NOW.date()),
    ):
        changed = green()
        changed.apply_changes(change, {}, NOW)
        assert metadata_digest(changed) != digest
