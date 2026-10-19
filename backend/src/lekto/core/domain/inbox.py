"""The inbox: what stands in whose inbox, under which tab, and how it left it (Tobi,
17./18.10.2026; `architektur.md`, Verarbeitung, "Posteingang").

A document stands in its owner's inbox, and in the inbox of every user of an admin who includes
all users (`all_users`); someone who reaches it through a shared space only never has it there.
It stands open while it is processed (no lane yet), yellow (to review), red (to intervene), or
new (`Document.new_at`) and not seen by the viewer since it became new: seen is per viewer. It
leaves when a person confirms it out of yellow or red, for everyone, or when the viewer sees
it; for `DONE_PERIOD` it is done, with how, when and by whom.

`inbox_state` is the rule. The SQL adapter has it in its query language; the core and the
in-memory adapter use this one.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from lekto.core.domain.documents import Document
from lekto.core.domain.ids import UserId
from lekto.core.domain.pipeline import Lane


class InboxTab(StrEnum):
    NEW = "new"  # green by itself, and not seen by the viewer since it became new
    REVIEW = "review"  # yellow
    INTERVENE = "intervene"  # red
    PROCESSING = "processing"  # no lane yet
    DONE = "done"  # left the viewer's inbox within `DONE_PERIOD`


OPEN_TABS = (InboxTab.NEW, InboxTab.REVIEW, InboxTab.INTERVENE, InboxTab.PROCESSING)
"""The tabs of what is open: every tab but done."""

DONE_PERIOD = timedelta(days=14)
"""How long a document that left the inbox is done; what only that needs goes afterwards."""


class Departure(StrEnum):
    """How a document left the inbox."""

    CONFIRMED = "confirmed"  # a person confirmed it out of yellow or red, for everyone
    SEEN = "seen"  # the viewer saw it


@dataclass(frozen=True)
class Confirmation:
    """A person confirmed the document out of yellow or red: who, and when."""

    by: UserId
    at: datetime


@dataclass(frozen=True)
class Done:
    """How, when and by whom a document left the viewer's inbox."""

    how: Departure
    at: datetime
    by: UserId


@dataclass(frozen=True)
class InboxState:
    """Where a document stands in the viewer's inbox; `done` for the tab done."""

    tab: InboxTab
    done: Done | None = None


def is_unseen(document: Document, seen_at: datetime | None) -> bool:
    """Whether the document is new and the viewer, who saw it last at `seen_at` (None: never),
    has not seen it since it became new."""
    new_at = document.new_at
    return new_at is not None and (seen_at is None or seen_at < new_at)


def open_tab(document: Document, seen_at: datetime | None) -> InboxTab | None:
    """The tab the document stands open under in the inbox of a viewer who saw it last at
    `seen_at`; None if it is not open there. Whose inbox it is in the caller decides."""
    match document.lane:
        case None:
            return InboxTab.PROCESSING
        case Lane.YELLOW:
            return InboxTab.REVIEW
        case Lane.RED:
            return InboxTab.INTERVENE
    return InboxTab.NEW if is_unseen(document, seen_at) else None


def left_at(
    document: Document, seen_at: datetime | None, confirmation: Confirmation | None
) -> datetime | None:
    """When the document last left the inbox of a viewer who saw it last at `seen_at`, however
    long ago: when they saw it since it became new, or, if it is new for no one, when a person
    confirmed it; None if it did not. A confirmation makes a document new for no one, so one
    that is new now was confirmed before it became new, and the viewer's seen is the latest.
    Done is sorted by it, newest first (Tobi, 18.10.2026)."""
    new_at = document.new_at
    if new_at is not None:
        return seen_at if seen_at is not None and seen_at >= new_at else None
    return None if confirmation is None else confirmation.at


def departure(
    document: Document,
    *,
    viewer: UserId,
    seen_at: datetime | None,
    confirmation: Confirmation | None,
    since: datetime,
) -> Done | None:
    """How the green document left `viewer`'s inbox from `since` on (`left_at`), if it did:
    the viewer saw it since it became new, or a person confirmed it."""
    at = left_at(document, seen_at, confirmation)
    if document.lane is not Lane.GREEN or at is None or at < since:
        return None
    if document.new_at is None and confirmation is not None:
        return Done(Departure.CONFIRMED, at, confirmation.by)
    return Done(Departure.SEEN, at, viewer)


def inbox_state(
    document: Document,
    *,
    viewer: UserId,
    seen_at: datetime | None,
    confirmation: Confirmation | None,
    since: datetime,
) -> InboxState | None:
    """Where the document stands in `viewer`'s inbox, who saw it last at `seen_at` (None:
    never); done counts from `since`. None if it stands nowhere there."""
    tab = open_tab(document, seen_at)
    if tab is not None:
        return InboxState(tab)
    done = departure(
        document, viewer=viewer, seen_at=seen_at, confirmation=confirmation, since=since
    )
    return None if done is None else InboxState(InboxTab.DONE, done)


def worst_lane(counts: Mapping[InboxTab, int]) -> Lane | None:
    """The worst lane among the open cases, red before yellow before green; None with nothing
    open but documents in processing, or nothing at all."""
    for tab, lane in (
        (InboxTab.INTERVENE, Lane.RED),
        (InboxTab.REVIEW, Lane.YELLOW),
        (InboxTab.NEW, Lane.GREEN),
    ):
        if counts.get(tab, 0) > 0:
            return lane
    return None
