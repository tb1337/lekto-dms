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

from papiq.core.domain.documents import Document
from papiq.core.domain.ids import UserId
from papiq.core.domain.pipeline import Lane


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


def departure(
    document: Document,
    *,
    viewer: UserId,
    seen_at: datetime | None,
    confirmation: Confirmation | None,
    since: datetime,
) -> Done | None:
    """How the green document left `viewer`'s inbox from `since` on, if it did: the viewer saw
    it since it became new, or (it is new for no one) a person confirmed it. A confirmation
    makes it new for no one, so one that is new now was confirmed before it became new, and
    the viewer's seen is the latest."""
    if document.lane is not Lane.GREEN:
        return None
    new_at = document.new_at
    if new_at is not None:
        if seen_at is not None and seen_at >= new_at and seen_at >= since:
            return Done(Departure.SEEN, seen_at, viewer)
        return None
    if confirmation is not None and confirmation.at >= since:
        return Done(Departure.CONFIRMED, confirmation.at, confirmation.by)
    return None


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
