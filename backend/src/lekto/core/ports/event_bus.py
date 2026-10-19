from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timedelta
from typing import Protocol

from lekto.core.domain.events import DomainEvent

type EventHandler = Callable[[DomainEvent], Awaitable[None]]


class Outbox(Protocol):
    """Writing side of the event bus, part of the unit of work: events are stored in the same
    transaction as the state change (transactional outbox) and exist only after commit."""

    async def add(self, events: Iterable[DomainEvent]) -> None: ...


DISPATCH_BATCH = 100
"""Events a dispatch delivers to each subscriber at most, new ones and due ones each."""


class EventBus(Protocol):
    """Delivers committed events to subscribers, at least once per subscriber.

    - Subscriptions are durable by name: the first registration of a name receives the events
      committed from then on; a later registration under the same name (e.g. after a restart,
      on a new bus instance) resumes where the previous one stopped.
    - No committed event is skipped, also not one whose transaction started before, but
      committed after, events that were already delivered.
    - Events of one transaction arrive in the order they were added; across transactions the
      order is not guaranteed. Events are thin: receivers fetch the current state.
    - If a handler raises, that event is delivered to it again on a later dispatch, after a
      growing delay (a `RetryPolicy`); it does not hold back later events. After the last
      attempt the event is given up for that subscriber and logged as an error. Receivers
      recognise repetitions by the event id.

    First adapter: outbox table in the database with in-process dispatch (M2).
    Later adapters: Valkey Streams, NATS.
    """

    def subscribe(self, subscriber: str, handler: EventHandler) -> None:
        """Register a handler under a subscriber name, unique per bus instance. Adapters may
        create the durable subscription lazily on the next dispatch."""
        ...

    async def dispatch(self, *, limit: int = DISPATCH_BATCH) -> int:
        """Deliver to each subscriber up to `limit` new events and up to `limit` events that
        failed before and are due again; returns the number of successful deliveries."""
        ...

    async def purge(self, *, before: datetime) -> int:
        """Remove events recorded before `before` that every subscription has handled (delivered
        or given up); returns how many. Without subscriptions, every such event counts as
        handled. Keep `before` well in the past: a subscription is created on its first
        dispatch and only then holds back events."""
        ...


DELIVERY_DELAY = timedelta(seconds=1)
DELIVERY_MAX_DELAY = timedelta(hours=1)
"""Before the next delivery of an event whose handler failed the bus waits `DELIVERY_DELAY`,
doubling, at most `DELIVERY_MAX_DELAY`; the number of attempts is a setting."""
