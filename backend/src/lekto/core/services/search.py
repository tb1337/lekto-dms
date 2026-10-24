"""Searching documents: full text and, with embeddings, meaning, in one call.

The index is derived data and lags a little behind the database, so it is a pre-selection only:
the rights are in the query to the index (`Visibility`), and every hit is checked against the
database once more before it is returned (`document_access`), together with the filter. A
share that was withdrawn or a lane that changed since the index was written costs a hit, never
a leak. That is why a page can hold fewer items than `limit`; `next_offset` counts index hits,
so paging over the pages still reaches every hit.

A search says how it searched (`SearchPage.mode`): by words and meaning, or by words alone, and
then why (`SearchPage.reason`): no embeddings, the service down, too slow or answering with a
vector of another length. The words are the fallback that always stays. A query whose meaning
was not ready in time goes on being embedded in the background; its vector is kept a while for
the same query, and the searcher learns when it is ready (`SearchMeaningReady`, handed to the
listeners, `listen`). Before a search, `warm` has the model of the embeddings loaded.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import EmbeddingsError, SearchUnavailableError, ValidationError
from lekto.core.domain.events import SearchMeaningReady
from lekto.core.domain.ids import SpaceId, UserId
from lekto.core.domain.permissions import Reach, document_access, reach_access
from lekto.core.domain.reasons import Action, Reason, ReasonCode, because
from lekto.core.domain.search import Segment, Visibility
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.ports.clock import Clock
from lekto.core.ports.embeddings import Embeddings
from lekto.core.ports.repository import DocumentFilter, DocumentOrder, SortKey
from lekto.core.ports.search_index import (
    MAX_HITS,
    SEARCH_PAGE,
    SearchIndex,
    SearchQuery,
    check_search,
)
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from lekto.core.services._access import load_actor, load_lister
from lekto.core.services._tags import expanded, group_lookup, matches
from lekto.core.services.inbox import in_inbox

log = logging.getLogger(__name__)

KEEP_VECTORS = timedelta(minutes=10)
"""How long the vector of a query is kept for the same query again."""
WARM_EVERY = timedelta(minutes=1)
"""At most one embedding to warm the model in this time (`SearchService.warm`)."""
_KEEP_AT_MOST = 200  # vectors of queries kept
_PENDING_AT_MOST = 8  # queries embedded at once; beyond, a slow one is given up
_WARM_TEXT = "Dokument"


@dataclass(frozen=True, kw_only=True)
class SearchPolicy:
    """Configuration: the composition sets it from the settings, whose defaults are the one
    source."""

    semantic_ratio: float  # weight of the meaning against the words, 0 to 1
    embed_timeout: timedelta  # for the query; then plain full text
    query_prefix: str = ""  # put before the query, for models that ask for it
    dimensions: int | None = None  # the length of the vectors; a query of another goes by words

    def __post_init__(self) -> None:
        if not 0 <= self.semantic_ratio <= 1:
            raise ValueError("semantic_ratio must be between 0 and 1")


@dataclass(frozen=True)
class SearchItem:
    document: Document
    access: SpaceRole  # of the caller
    score: float | None
    snippet: tuple[Segment, ...]
    in_inbox: bool = False  # it stands open in the caller's inbox (`inbox.in_inbox`)


class SearchMode(StrEnum):
    HYBRID = "hybrid"  # words and meaning
    WORDS = "words"  # words alone


@dataclass(frozen=True)
class SearchPage:
    items: list[SearchItem]  # best first; may be fewer than asked for
    estimated_total: int  # of the hits, as far as the caller may see them; not exact
    next_offset: int | None  # where the next page starts; None after the last one
    mode: SearchMode
    reason: Reason | None = None  # why by words alone, where the meaning was to take part
    meaning_pending: bool = False  # the meaning is still being made: `SearchMeaningReady` follows

    @property
    def semantic(self) -> bool:
        """Whether the meaning took part."""
        return self.mode is SearchMode.HYBRID


@dataclass(frozen=True)
class _Meaning:
    """The vector of a query, or why there is none, and whether it is still being made."""

    vector: tuple[float, ...] | None
    reason: Reason | None = None
    pending: bool = False


class _OtherLengthError(Exception):
    def __init__(self, got: int, wanted: int) -> None:
        super().__init__(f"the query vector has {got} numbers, not {wanted}")
        self.got, self.wanted = got, wanted


class _UtcNow:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SearchService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        index: SearchIndex,
        policy: SearchPolicy,
        embeddings: Embeddings | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._uow = uow
        self._index = index
        self._embeddings = embeddings
        self._policy = policy
        self._clock: Clock = clock or _UtcNow()
        self._vectors: dict[str, tuple[datetime, tuple[float, ...]]] = {}
        self._pending: dict[str, asyncio.Task[tuple[float, ...]]] = {}
        self._waiting: dict[str, set[tuple[UserId, str]]] = defaultdict(set)
        self._listeners: list[Callable[[SearchMeaningReady], None]] = []
        self._warmed_at: datetime | None = None

    def listen(self, listener: Callable[[SearchMeaningReady], None]) -> None:
        """Hand `SearchMeaningReady` to `listener` (the event streams of the API)."""
        self._listeners.append(listener)

    async def warm(self, actor: UserId) -> bool:
        """Have the model of the embeddings loaded before a search needs it (a person starts
        typing): one embedding in the background, at most once in `WARM_EVERY`. Whether one
        was started. AuthenticationError for a deactivated caller."""
        async with self._uow() as uow:
            await load_actor(uow, actor)
        now = self._clock.now()
        if self._embeddings is None:
            return False
        if self._warmed_at is not None and now - self._warmed_at < WARM_EVERY:
            return False
        self._warmed_at = now
        key = self._policy.query_prefix + _WARM_TEXT
        return key in self._pending or self._embed_later(key) is not None

    async def settled(self) -> None:
        """Wait for the embeddings still running in the background."""
        await asyncio.gather(*self._pending.values(), return_exceptions=True)

    async def search(
        self,
        actor: UserId,
        text: str,
        filter: DocumentFilter | None = None,
        *,
        offset: int = 0,
        limit: int = SEARCH_PAGE,
        semantic_ratio: float | None = None,
        order: DocumentOrder | None = None,
        all_users: bool = False,
    ) -> SearchPage:
        """Documents within the caller's reach that match `text` (and `filter`), by relevance
        or in `order`; with `all_users` (admins only), any document. Each says whether it stands
        open in the caller's inbox (with `all_users`, in every user's).

        ValidationError for an empty text, a paging outside the limits or an order by a field
        (the index holds no field values), AuthenticationError
        for a deactivated caller, PermissionDeniedError for `all_users` without being an admin,
        SearchUnavailableError if the index cannot be reached.
        """
        filter = filter or DocumentFilter()
        ratio = self._policy.semantic_ratio if semantic_ratio is None else semantic_ratio
        check_search(text, ratio, offset, limit)
        if order is not None and order.key is SortKey.FIELD:
            raise ValidationError("sort: the search cannot sort by a field")
        async with self._uow() as uow:
            user = await load_lister(uow, actor, all_users, Action.SEARCH_ALL_DOCUMENTS)
            spaces = await uow.spaces.list_accessible(actor)
            filter = await expanded(uow, filter)
        if offset >= MAX_HITS:
            return SearchPage([], 0, None, SearchMode.WORDS)
        limit = min(limit, MAX_HITS - offset)

        meaning = await self._meaning(actor, text) if ratio > 0 else _Meaning(None)
        try:
            result = await self._index.search(
                SearchQuery(
                    text=text,
                    visibility=replace(
                        Visibility.of(Reach.of(actor, spaces)), everything=all_users
                    ),
                    filter=filter,
                    vector=meaning.vector,
                    semantic_ratio=ratio,
                    order=order,
                    offset=offset,
                    limit=limit,
                )
            )
        except SearchUnavailableError as error:
            log.warning("the search index cannot be reached: %s", error)
            raise SearchUnavailableError(because(ReasonCode.SEARCH_INDEX_UNAVAILABLE)) from error

        items = []
        by_id: dict[SpaceId, Space] = {space.id: space for space in spaces}
        async with self._uow() as uow:
            contacts, types = await group_lookup(uow, filter)
            for hit in result.hits:
                document = await uow.documents.find(hit.id)
                if document is None:
                    continue  # deleted since the index was written
                if document.space_id not in by_id:
                    by_id[document.space_id] = await uow.spaces.get(document.space_id)
                space = by_id[document.space_id]
                allowed = all_users or reach_access(user, document, space) is not None
                access = document_access(user, document, space)
                if not allowed or access is None or not matches(document, filter, contacts, types):
                    continue  # the index is behind: a membership or a lane has changed
                items.append(SearchItem(document, access, hit.score, hit.snippet))
            waiting = await in_inbox(
                uow, actor, [item.document for item in items], all_users=all_users
            )
        items = [replace(item, in_inbox=item.document.id in waiting) for item in items]
        if len(items) < len(result.hits):
            log.info(
                "search hits dropped after the check against the database",
                extra={"user_id": str(actor), "dropped": len(result.hits) - len(items)},
            )

        end = offset + len(result.hits)
        # A search with meaning can reach every document, whatever the estimate of the words.
        reach = MAX_HITS if result.semantic else min(result.estimated_total, MAX_HITS)
        more = len(result.hits) == limit and end < reach
        if result.semantic:
            mode, reason, pending = SearchMode.HYBRID, None, False
        else:
            mode, reason, pending = SearchMode.WORDS, meaning.reason, meaning.pending
        return SearchPage(
            items, result.estimated_total, end if more else None, mode, reason, pending
        )

    async def _meaning(self, actor: UserId, text: str) -> _Meaning:
        """The vector of the query, or why there is none: without embeddings, or with the
        service down, too slow or answering with a vector of another length, the search goes
        by words alone (it should not depend on it). A vector is kept for the same query; one
        too slow goes on being made in the background, and the searcher learns when it is
        ready (`SearchMeaningReady`)."""
        if self._embeddings is None:
            return _Meaning(None, because(ReasonCode.SEARCH_NO_EMBEDDINGS))
        key = self._policy.query_prefix + text
        if (vector := self._kept(key)) is not None:
            return _Meaning(vector)
        seconds = self._policy.embed_timeout.total_seconds()
        task = self._pending.get(key) or self._embed_later(key)
        try:
            if task is None:  # too many in the background already: given up when too slow
                vector = await asyncio.wait_for(self._vector_of(key), seconds)
            else:
                vector = await asyncio.wait_for(asyncio.shield(task), seconds)
        except TimeoutError:
            log.warning("searching without meaning, the query was not embedded in time")
            waited = int(seconds) if seconds.is_integer() else seconds
            reason = because(ReasonCode.SEARCH_EMBED_TIMEOUT, seconds=waited)
            if task is None:
                return _Meaning(None, reason)
            self._waiting[key].add((actor, text))
            return _Meaning(None, reason, pending=True)
        except EmbeddingsError as error:
            log.warning("searching without meaning, the query was not embedded: %s", error)
            return _Meaning(None, because(ReasonCode.SEARCH_EMBED_FAILED))
        except _OtherLengthError as error:
            log.warning("searching without meaning, %s", error)
            reason = because(ReasonCode.SEARCH_EMBED_DIMENSIONS, got=error.got, wanted=error.wanted)
            return _Meaning(None, reason)
        return _Meaning(vector)

    async def _vector_of(self, key: str) -> tuple[float, ...]:
        """The vector of a query (with its prefix). EmbeddingsError if the service fails,
        `_OtherLengthError` for a vector of another length than the index's."""
        assert self._embeddings is not None
        result = await self._embeddings.embed([key])
        if not result.vectors:
            raise EmbeddingsError("no vector for the query")
        vector = tuple(result.vectors[0])
        wanted = self._policy.dimensions
        if wanted is not None and len(vector) != wanted:
            raise _OtherLengthError(len(vector), wanted)
        return vector

    def _embed_later(self, key: str) -> asyncio.Task[tuple[float, ...]] | None:
        """Embed a query in a task of its own, which goes on when a search stops waiting; None
        with too many such tasks running already."""
        if len(self._pending) >= _PENDING_AT_MOST:
            return None
        task = asyncio.create_task(self._vector_of(key))
        self._pending[key] = task
        task.add_done_callback(lambda done: self._embedded(key, done))
        return task

    def _embedded(self, key: str, task: asyncio.Task[tuple[float, ...]]) -> None:
        """A query is embedded: keep its vector, and tell the searchers that gave up waiting."""
        self._pending.pop(key, None)
        waiting = self._waiting.pop(key, set())
        if task.cancelled() or task.exception() is not None:
            return  # they keep the words
        self._keep(key, task.result())
        for user, text in waiting:
            event = SearchMeaningReady(occurred_at=self._clock.now(), user_id=user, query=text)
            for listener in self._listeners:
                try:
                    listener(event)
                except Exception:
                    log.exception("a listener failed on %s", event.type)

    def _kept(self, key: str) -> tuple[float, ...] | None:
        kept = self._vectors.get(key)
        if kept is None:
            return None
        until, vector = kept
        if until <= self._clock.now():
            del self._vectors[key]
            return None
        return vector

    def _keep(self, key: str, vector: tuple[float, ...]) -> None:
        now = self._clock.now()
        self._vectors = {k: kept for k, kept in self._vectors.items() if kept[0] > now}
        while len(self._vectors) >= _KEEP_AT_MOST:
            del self._vectors[next(iter(self._vectors))]
        self._vectors[key] = (now + KEEP_VECTORS, vector)
