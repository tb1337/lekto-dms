"""The inbox in the domain: when processing makes a document new, and where a document stands
in whose inbox (Tobi, 17./18.10.2026)."""

from datetime import datetime, timedelta

import pytest

from lekto.core.domain.documents import Document, DocumentChanges, metadata_digest
from lekto.core.domain.ids import ContactId, TagId, UserId, new_id
from lekto.core.domain.inbox import (
    DONE_PERIOD,
    Confirmation,
    Departure,
    Done,
    InboxState,
    InboxTab,
    inbox_state,
    open_tab,
    worst_lane,
)
from lekto.core.domain.pipeline import Lane, Node, NodeResult, ProcessingStatus
from tests import builders
from tests.builders import FAILED, NOW, UNCERTAIN

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
    """Process the document at `now`; the judge applies `change` (the metadata it decides)."""

    def judge(node: Node) -> None:
        if node is Node.JUDGE and change is not None:
            document.apply_changes(change, {}, now)

    return builders.run_pipeline(document, results, now=now, before=judge)


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


def test_reprocessing_a_green_document_makes_it_new_only_if_the_metadata_changed() -> None:
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


def test_a_document_that_was_not_green_is_new_whatever_changed() -> None:
    """A retry from red, a reprocessing of a yellow document (Tobi, 18.10.2026): ending green
    by itself, it is new, also with its metadata unchanged."""
    red = finish(builders.received(), NOW, {Node.FILE: FAILED}, change=DocumentChanges())
    assert (red.lane, red.new_at) == (Lane.RED, None)
    red.retry(LATER)
    finish(red, LATER)
    assert (red.lane, red.new_at) == (Lane.GREEN, LATER)

    yellow = finish(builders.received(), NOW, {Node.JUDGE: UNCERTAIN})
    yellow.reprocess_from(Node.JUDGE, LATER)
    finish(yellow, LATER)
    assert (yellow.lane, yellow.new_at) == (Lane.GREEN, LATER)

    once_green = green()  # new since its first run, then yellow after a reprocessing
    once_green.reprocess_from(Node.JUDGE, LATER)
    finish(once_green, LATER, {Node.JUDGE: UNCERTAIN})
    once_green.reprocess_from(Node.JUDGE, LAST)
    finish(once_green, LAST, change=DocumentChanges(contact_id=CONTACT))  # unchanged
    assert (once_green.lane, once_green.new_at) == (Lane.GREEN, LAST)


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


# --- where a document stands ---------------------------------------------------------------------

VIEWER = UserId(new_id())
ADMIN = UserId(new_id())
SINCE = LAST - DONE_PERIOD


def state(
    document: Document, seen_at: datetime | None = None, confirmation: Confirmation | None = None
) -> InboxState | None:
    return inbox_state(
        document, viewer=VIEWER, seen_at=seen_at, confirmation=confirmation, since=SINCE
    )


def test_processing_yellow_and_red_stand_open_whatever_was_seen() -> None:
    cases = {
        InboxTab.PROCESSING: builders.received(),
        InboxTab.REVIEW: finish(builders.received(), NOW, {Node.JUDGE: UNCERTAIN}),
        InboxTab.INTERVENE: finish(builders.received(), NOW, {Node.OCR: FAILED}),
    }
    for tab, document in cases.items():
        for seen_at in (None, LATER):
            assert open_tab(document, seen_at) is tab
            assert state(document, seen_at, Confirmation(ADMIN, LATER)) == InboxState(tab)


def test_a_new_document_stands_until_the_viewer_sees_it() -> None:
    document = green()
    assert state(document) == InboxState(InboxTab.NEW)
    assert state(document, NOW - timedelta(minutes=1)) == InboxState(InboxTab.NEW)
    assert state(document, LATER) == InboxState(InboxTab.DONE, Done(Departure.SEEN, LATER, VIEWER))
    document.new_at = LAST  # new again since
    assert state(document, LATER) == InboxState(InboxTab.NEW)


def test_done_lasts_the_period() -> None:
    document = green()
    seen_long_ago = SINCE - timedelta(seconds=1)
    document.new_at = seen_long_ago - timedelta(days=1)
    assert state(document, seen_long_ago) is None  # seen, but long ago
    assert state(document, SINCE) == InboxState(InboxTab.DONE, Done(Departure.SEEN, SINCE, VIEWER))


def test_a_confirmed_document_is_done_for_everyone_with_who_confirmed_it() -> None:
    document = green()
    document.new_at = None  # confirming takes it away
    confirmed = Confirmation(ADMIN, LATER)
    assert state(document, None, confirmed) == InboxState(
        InboxTab.DONE, Done(Departure.CONFIRMED, LATER, ADMIN)
    )
    assert state(document, LAST, confirmed) == InboxState(
        InboxTab.DONE, Done(Departure.CONFIRMED, LATER, ADMIN)
    )  # seen counts while it is new only
    assert state(document, None, Confirmation(ADMIN, SINCE - timedelta(seconds=1))) is None
    assert state(document) is None  # never in the inbox


def test_a_document_confirmed_before_it_became_new_counts_as_new() -> None:
    document = green()
    earlier = Confirmation(ADMIN, NOW - timedelta(minutes=5))
    assert state(document, None, earlier) == InboxState(InboxTab.NEW)
    assert state(document, LATER, earlier) == InboxState(
        InboxTab.DONE, Done(Departure.SEEN, LATER, VIEWER)
    )


@pytest.mark.parametrize(
    ("counts", "lane"),
    [
        ({InboxTab.INTERVENE: 1, InboxTab.REVIEW: 2, InboxTab.NEW: 3}, Lane.RED),
        ({InboxTab.REVIEW: 2, InboxTab.NEW: 3, InboxTab.PROCESSING: 1}, Lane.YELLOW),
        ({InboxTab.NEW: 3, InboxTab.PROCESSING: 1, InboxTab.DONE: 4}, Lane.GREEN),
        ({InboxTab.PROCESSING: 1, InboxTab.DONE: 4}, None),
        ({tab: 0 for tab in InboxTab}, None),
        ({}, None),
    ],
)
def test_the_worst_lane_among_the_open_cases(counts: dict[InboxTab, int], lane: Lane) -> None:
    assert worst_lane(counts) is lane
