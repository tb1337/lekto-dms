"""Server-sent events: progress of the documents a user may see, the end of a training of the
classifier, and for a searcher that the meaning of their query is ready
(`search.meaning_ready`, from the search of this process, not the event bus: `deliver`).

`EventHub` subscribes to the event bus (subscriber `api.sse`, dispatched by the API process
with `waiting.dispatch_events`)
and hands each document event to the open streams of the users who may read the document at
that moment, and `classifier.trained` to every stream that does not follow one document
(every user sees the classifier on the page "System", Tobi 24.10.2026). Events are pushed only
to connected clients; there is no replay, so a client that reconnects fetches the current
state. One API instance is assumed: several instances would
share the subscription and each would see only part of the events (a broker is the way out).

Admins may read every document, so they get the events of every document (Tobi, 08.10.2026).
`document.deleted` goes to the users who had the document within their reach when it was deleted
(the event carries their ids; a deleted document cannot be checked afterwards) and to the active
admins. The ids are not sent on.
"""

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder

from lekto.core.domain.events import (
    ClassifierTrained,
    DocumentDeleted,
    DocumentEvent,
    DocumentUpdated,
    DomainEvent,
    SearchMeaningReady,
)
from lekto.core.domain.ids import DocumentId, UserId
from lekto.core.ports.event_bus import EventBus
from lekto.core.services.documents import DocumentService

log = logging.getLogger(__name__)

SUBSCRIBER = "api.sse"
QUEUE_SIZE = 100

_CLOSED = object()


@dataclasses.dataclass(eq=False)
class Listener:
    user: UserId
    document: DocumentId | None
    queue: asyncio.Queue[object] = dataclasses.field(
        default_factory=lambda: asyncio.Queue(QUEUE_SIZE)
    )

    async def events(
        self,
        still_allowed: Callable[[], Awaitable[bool]] | None,
        every: timedelta,
    ) -> AsyncIterator[DomainEvent]:
        """The events for this listener until the hub closes or the client falls behind.

        With `still_allowed`, the stream asks it at least every `every` (also while no event
        comes) and ends once it answers False, e.g. when the session was revoked."""
        loop = asyncio.get_running_loop()
        checked = loop.time()
        while True:
            if still_allowed is None:
                item = await self.queue.get()
            else:
                try:
                    wait = max(0.0, checked + every.total_seconds() - loop.time())
                    item = await asyncio.wait_for(self.queue.get(), timeout=wait)
                except TimeoutError:
                    item = None
                if loop.time() - checked >= every.total_seconds():
                    if not await still_allowed():
                        return
                    checked = loop.time()
                if item is None:
                    continue
            if item is _CLOSED:
                return
            assert isinstance(item, DomainEvent)
            yield item

    def offer(self, item: object) -> None:
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            # Too slow: end the stream, the client reconnects and fetches the state.
            log.warning("event stream fell behind, closing it", extra={"user": str(self.user)})
            self._close_now()

    def _close_now(self) -> None:
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queue.put_nowait(_CLOSED)


class EventHub:
    def __init__(self, documents: DocumentService) -> None:
        self._documents = documents
        self._listeners: set[Listener] = set()
        self._closed = False

    def attach(self, bus: EventBus) -> None:
        bus.subscribe(SUBSCRIBER, self.handle)

    async def handle(self, event: DomainEvent) -> None:
        if isinstance(event, ClassifierTrained):
            self._to_all(event)
            return
        if not isinstance(event, DocumentEvent):
            return
        listeners = [
            listener
            for listener in self._listeners
            if listener.document in (None, event.document_id)
        ]
        if not listeners:
            return
        if isinstance(event, DocumentDeleted):
            users = {listener.user for listener in listeners}
            readers = set(event.readers) | await self._documents.active_admins(users)
        else:
            users = {listener.user for listener in listeners}
            readers = await self._documents.filter_readers(event.document_id, users)
            if isinstance(event, DocumentUpdated) and event.related is not None:
                # A relation: only who reads its other document too.
                readers &= await self._documents.filter_readers(event.related, users)
        for listener in listeners:
            if listener.user in readers:
                listener.offer(event)

    def deliver(self, event: SearchMeaningReady) -> None:
        """Hand the event to the streams of its user that do not follow one document."""
        for listener in list(self._listeners):
            if listener.user == event.user_id and listener.document is None:
                listener.offer(event)

    def _to_all(self, event: DomainEvent) -> None:
        for listener in list(self._listeners):
            if listener.document is None:
                listener.offer(event)

    @asynccontextmanager
    async def listen(
        self, user: UserId, document: DocumentId | None = None
    ) -> AsyncIterator[Listener]:
        listener = Listener(user, document)
        if self._closed:
            listener.offer(_CLOSED)
        self._listeners.add(listener)
        try:
            yield listener
        finally:
            self._listeners.discard(listener)

    def close(self) -> None:
        """End all streams, e.g. when the server shuts down."""
        self._closed = True
        for listener in list(self._listeners):
            listener._close_now()


def message(event: DomainEvent) -> dict[str, Any]:
    """The JSON payload of an event."""
    fields = {
        field.name: getattr(event, field.name)
        for field in dataclasses.fields(event)
        if field.name not in ("readers", "user_id", "related")
    }
    payload: dict[str, Any] = jsonable_encoder({"type": event.type, **fields})
    return payload
