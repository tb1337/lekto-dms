"""Keeping the search index in line with the repository and the object store.

The index is derived data and lags a little behind: a document event creates a job, and the job
reads the current state of the document from the database and the object store and writes it
into the index. A job is idempotent and may be repeated.

- Every event of a document (`received`, `node_completed`, `lane_changed`, `filed`, `updated`,
  `deleted`) leads to a `search.index` job. The jobs of a document coalesce while queued (a
  coalesce key, not a dedup key): a queued job reads the state when it runs and so covers every
  event before, but a running job has read its state already, and a dedup key would lose the
  change that arrives since. A document in the pipeline thus costs one or two index jobs, not
  one per node. Reconciliation and refresh queue with the same key.
- A job that finds the document gone removes it from the index.
- Two jobs for one document may run at the same time, and the older state may be written last.
  So a job checks after writing that the document and the names it carries are still as it read
  them, and writes again if not (`_ROUNDS`). The state written last is then one that matched the
  database after the write.
- Vectors are computed from sections of the text (`LEKTO_SEARCH_CHUNK_SIZE`, at most
  `LEKTO_SEARCH_MAX_CHUNKS`) and only when the sections differ from those of the indexed
  vectors: a change of lane, space or date costs no embedding.
- Failed jobs are repeated with a growing delay (about three hours in all). If only the
  embedding fails, the document is written at once with the vectors it has (the words must not
  wait for the vectors), the job is repeated, and the last attempt writes without vectors; the
  reconciliation adds them.
- `search.refresh` follows the renaming of a contact, document type or tag (a topic is one), a
  tag nested elsewhere and the changed groups of a contact or type: it queues an index job for
  every document concerned (one that carries the tag or a tag below it, or has it or one below
  it as its topic, or whose contact or type is in such a group).
- `search.reconcile` (recurring) compares the index with the database, queues jobs for what
  is missing or stale and removes what no longer exists. `search.rebuild` builds a new index from
  scratch next to the active one and swaps it in without an outage of the search.
- An index job reports how many sections it embedded (`Job.result`, `{"sections": n}`), so the
  page "System" tells the jobs that embedded from those that only wrote the words (`status`).
  `check` compares like the reconciliation but only counts (admins).
"""

import asyncio
import hashlib
import logging
import re
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import (
    ConcurrencyError,
    EmbeddingsError,
    NotFoundError,
    SearchIndexError,
)
from lekto.core.domain.events import (
    DocumentEvent,
    DomainEvent,
    NodeCompleted,
    NodeDeferred,
    NodeStarted,
)
from lekto.core.domain.fields import FieldValue, Money, Url
from lekto.core.domain.ids import ContactId, DocumentId, DocumentTypeId, TagId, UserId
from lekto.core.domain.jobs import OPEN_STATES, FinishedJob, Job, JobState, RetryPolicy
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.periods import MONTH_NAMES, Period, PeriodKind
from lekto.core.domain.pipeline import SIGNALS
from lekto.core.domain.reasons import Action
from lekto.core.domain.search import LAYOUT, EmbeddingStamp, IndexDocument, IndexState
from lekto.core.domain.statistics import median, percentile
from lekto.core.ports.clock import Clock
from lekto.core.ports.embeddings import Embeddings
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.repository import DocumentFilter
from lekto.core.ports.search_index import IndexStats, SearchIndex
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_actor, require_admin
from lekto.core.services._jobs import JobRunner, document_payload, lost, payload_document
from lekto.core.services._kept import Kept
from lekto.core.services._pages import document_pages
from lekto.core.services._tags import tag_tree
from lekto.core.services.objects import load_text

log = logging.getLogger(__name__)

SUBSCRIBER = "search.index"
INDEX_JOB = "search.index"
"""Payload: `document_id`."""
REFRESH_JOB = "search.refresh"
"""Payload (`refresh_payload`): `kind` (`RefreshKind`) and `id` of the changed item."""
RECONCILE_JOB = "search.reconcile"
REBUILD_JOB = "search.rebuild"


class RefreshKind(StrEnum):
    """What a refresh job brings the documents of up to date: a contact, a document type or a
    tag whose name changed."""

    CONTACT = "contact"
    DOCUMENT_TYPE = "document_type"
    TAG = "tag"


def refresh_payload(kind: RefreshKind, id: UUID) -> JsonObject:
    """The payload of a `REFRESH_JOB`."""
    return {"kind": kind.value, "id": str(id)}


def _refreshed(payload: JsonObject) -> tuple[RefreshKind, UUID]:
    """What a `REFRESH_JOB` refreshes (`refresh_payload`)."""
    return RefreshKind(str(payload["kind"])), UUID(str(payload["id"]))


def _index_key(document: DocumentId) -> str:
    """The coalesce key of the index jobs of a document: one of them queued at a time."""
    return f"{INDEX_JOB}:{document}"


_ROUNDS = 3
_RETRY = RetryPolicy(max_attempts=10, delay=timedelta(seconds=30), max_delay=timedelta(hours=1))
_RETRIES = {INDEX_JOB: _RETRY, REFRESH_JOB: _RETRY, REBUILD_JOB: replace(_RETRY, max_attempts=3)}
"""How often a job is tried; the reconciliation runs again at its next interval instead."""
_QUEUE_BATCH = 200


@dataclass(frozen=True, kw_only=True)
class IndexingPolicy:
    """All but `batch_size` are configuration: the composition sets them from the settings,
    whose defaults are the one source."""

    max_text: int  # characters of text per document in the index
    chunk_size: int  # characters per section that gets a vector
    max_chunks: int  # sections per document; 1: one vector per document
    document_prefix: str = ""  # put before each section, for models that ask for it
    dimensions: int | None = None  # the length of the vectors; others are refused
    reconcile_interval: timedelta
    job_lease: timedelta
    rebuild_lease: timedelta
    batch_size: int = 50  # documents per request in a rebuild
    # How far back `status` reads the durations of the index jobs (the jobs' retention).
    durations_window: timedelta = timedelta(days=7)

    def __post_init__(self) -> None:
        if min(self.max_text, self.chunk_size, self.max_chunks, self.batch_size) < 1:
            raise ValueError("limits must be at least 1")


@dataclass(frozen=True)
class Rebuilt:
    documents: int
    queued: int  # documents the reconciliation afterwards queued again
    removed: int


@dataclass(frozen=True)
class Reconciled:
    queued: int  # missing or stale documents, queued for indexing
    removed: int  # documents in the index that no longer exist


@dataclass(frozen=True)
class IndexComparison:
    """The index against the database: documents indexed as they are (`current`), missing,
    stale (another version or an older layout: `outdated`; vectors of no or another model:
    `other_model`), and entries of documents that no longer exist (`extra`)."""

    current: int
    missing: tuple[DocumentId, ...]
    outdated: tuple[DocumentId, ...]
    other_model: tuple[DocumentId, ...]
    extra: tuple[DocumentId, ...]
    asked: tuple[DocumentId, ...] = ()  # current, but asked for (`compare(also)`)

    @property
    def stale(self) -> tuple[DocumentId, ...]:
        """What the reconciliation queues: missing, stale and asked for."""
        return (*self.missing, *self.outdated, *self.other_model, *self.asked)


@dataclass(frozen=True)
class IndexCheck:
    """What `check` counted, and how long it took."""

    comparison: IndexComparison
    took: timedelta


@dataclass(frozen=True)
class JobTimes:
    """How long index jobs ran: their number, the median and the 90th percentile."""

    count: int
    median: timedelta
    p90: timedelta


@dataclass(frozen=True, kw_only=True)
class IndexStatus:
    """The index for the page "System": the documents in the database, what the index says of
    itself, the index jobs running and queued with an estimate of when they are through (from
    the jobs done in the last ten minutes), how long index jobs ran that embedded and that did
    not, the time per embedded section, and the embedding model."""

    documents: int
    stats: IndexStats
    running: int
    queued: int
    remaining: timedelta | None
    embedded: JobTimes | None
    plain: JobTimes | None
    per_section: timedelta | None
    model: str | None
    dimensions: int | None
    since: datetime


@dataclass(frozen=True)
class Indexed:
    """What an index job did: the sections it embedded (0 if the vectors it had stay), and
    whether it wrote without vectors because the embedding failed (its time is no measure of
    either kind of job)."""

    sections: int
    embedding_failed: bool = False

    def to_json(self) -> JsonObject:
        data: JsonObject = {"sections": self.sections}
        if self.embedding_failed:
            data["embedding_failed"] = True
        return data


@dataclass(frozen=True)
class _Durations:
    """How long the latest done index jobs ran (`IndexingService._durations`)."""

    embedded: JobTimes | None
    plain: JobTimes | None
    per_section: timedelta | None
    since: datetime


_RATE_WINDOW = timedelta(minutes=10)
"""The done index jobs of this time say how fast the queued ones go."""
_SAMPLE = 2000
"""The latest done index jobs the durations are read from (a migration leaves far more within
the retention), counted at most once a minute."""


type _Named = tuple[tuple[TagId, str], ...]


@dataclass(frozen=True)
class _Snapshot:
    """A document with the names it is indexed with: `tags` those it carries, `labels` these
    with their ancestors, the groups of its contact and type with theirs, and its topic with
    those above it (`topic` its path, as the first section names it)."""

    document: Document
    contact: str | None
    document_type: str | None
    tags: _Named
    labels: _Named = ()
    contact_groups: _Named = ()
    document_type_groups: _Named = ()
    topics: _Named = ()
    topic: str | None = None

    @property
    def key(self) -> tuple[object, ...]:
        """What the index document depends on besides the text."""
        return (
            self.document.version,
            self.contact,
            self.document_type,
            self.labels,
            self.contact_groups,
            self.document_type_groups,
            self.topics,
            self.topic,
        )


class IndexingService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        object_store: ObjectStore,
        index: SearchIndex,
        policy: IndexingPolicy,
        embeddings: Embeddings | None = None,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._store = object_store
        self._index = index
        self._embeddings = embeddings
        self._policy = policy
        self._jobs = JobRunner(uow, clock)
        self._kept = Kept(clock)

    # --- events and jobs ------------------------------------------------------------------------

    async def on_event(self, event: DomainEvent) -> None:
        """The event bus subscriber: queue an index job for the document of the event. A node
        starting or waiting for its next attempt changes nothing the index holds, nor does a
        signal: they only propose, the judge decides."""
        if not isinstance(event, DocumentEvent) or isinstance(event, NodeStarted | NodeDeferred):
            return
        if isinstance(event, NodeCompleted) and event.node in SIGNALS:
            return
        async with self._uow() as uow:
            await uow.jobs.enqueue(
                INDEX_JOB,
                document_payload(event.document_id),
                run_at=self._clock.now(),
                coalesce_key=_index_key(event.document_id),
            )
            await uow.commit()

    async def schedule(self) -> None:
        """At the start of a worker: make sure the recurring reconciliation is queued, and run
        one now, as the index may have lost documents (or all) while no worker was running."""
        async with self._uow() as uow:
            await uow.jobs.enqueue(
                RECONCILE_JOB, {}, run_at=self._clock.now(), dedup_key=RECONCILE_JOB
            )
            await uow.jobs.enqueue(RECONCILE_JOB, {"once": True}, run_at=self._clock.now())
            await uow.commit()

    async def request_rebuild(self, actor: UserId) -> None:
        """Admins only: queue a rebuild of the index, unless one is queued or running."""
        async with self._uow() as uow:
            await require_admin(uow, actor, Action.REBUILD_INDEX)
            await uow.jobs.enqueue(REBUILD_JOB, {}, run_at=self._clock.now(), dedup_key=REBUILD_JOB)
            await uow.commit()

    async def run_next_job(self) -> bool:
        """Claim and run a due job of this service. Returns False if none was due. The rebuild
        has a lease of its own, as long as a rebuild may take."""
        return await self._jobs.run_next(
            [INDEX_JOB, REFRESH_JOB, RECONCILE_JOB], self._policy.job_lease, self._run_claimed
        ) or await self._jobs.run_next([REBUILD_JOB], self._policy.rebuild_lease, self._run_claimed)

    async def _run_claimed(self, job: Job) -> None:
        try:
            work = self._work(job)
        except (KeyError, TypeError, ValueError) as error:
            await self._jobs.invalid(job, error)
            return
        try:
            outcome = await work()
        except ConcurrencyError:
            lost(job)
            return
        except Exception as error:
            await self._failed(job, error)
            return
        recurring = job.kind == RECONCILE_JOB and job.payload.get("once") is not True
        result = outcome.to_json() if isinstance(outcome, Indexed) else None
        await self._jobs.end(job, also=self._next_reconcile if recurring else None, result=result)

    def _work(self, job: Job) -> Callable[[], Awaitable[object]]:
        if job.kind == INDEX_JOB:
            document_id = payload_document(job.payload)
            final = job.tries >= _RETRIES[INDEX_JOB].max_attempts
            return lambda: self.index_document(document_id, tolerate_embedding_failure=final)
        if job.kind == REFRESH_JOB:
            kind, item = _refreshed(job.payload)
            return lambda: self._refresh(kind, item)
        if job.kind == RECONCILE_JOB:
            return self.reconcile
        return self.rebuild

    async def _failed(self, job: Job, error: Exception) -> None:
        reason = f"{type(error).__name__}: {error}"
        log.warning(
            "search job failed", extra={"job_id": str(job.id), "kind": job.kind}, exc_info=True
        )
        now = self._clock.now()
        if job.kind == RECONCILE_JOB:  # again at the next interval, like the cleanup
            run_at: datetime | None = now + self._policy.reconcile_interval
        else:
            run_at = _RETRIES[job.kind].next_run(job.tries, now)
        await self._jobs.again(job, reason, run_at)

    async def _next_reconcile(self, uow: UnitOfWork) -> None:
        run_at = self._clock.now() + self._policy.reconcile_interval
        await uow.jobs.enqueue(RECONCILE_JOB, {}, run_at=run_at, dedup_key=RECONCILE_JOB)

    # --- one document ---------------------------------------------------------------------------

    async def index_document(
        self, id: DocumentId, *, tolerate_embedding_failure: bool = False
    ) -> Indexed:
        """Bring the index entry of a document to its current state; remove it if the document
        is gone. `tolerate_embedding_failure`: if the embedding fails, write without vectors.
        Returns how many sections it embedded (0 if the vectors it had stay) and whether the
        embedding failed."""
        embedded, failed = 0, False
        for _ in range(_ROUNDS):
            snapshot = await self._snapshot(id)
            if snapshot is None:
                await self._index.remove(id)
                return Indexed(embedded, failed)
            text = await self._read_text(id)
            state = await self._index.state(id)
            try:
                entry = await self._compose(snapshot, text, state)
            except EmbeddingsError as error:
                if not tolerate_embedding_failure:
                    # The words must not wait for the vectors: write what is known now (the
                    # vectors that are there stay), then let the job be repeated.
                    await self._index.upsert(
                        [await self._compose(snapshot, text, state, embed=False, keep=True)]
                    )
                    raise
                log.warning(
                    "indexing without vectors, the embedding failed",
                    extra={"document_id": str(id), "error": str(error)},
                )
                entry = await self._compose(snapshot, text, state, embed=False)
                failed = True
            await self._index.upsert([entry])
            embedded += len(entry.vectors or ())
            after = await self._snapshot(id)
            if after is not None and after.key == snapshot.key:
                return Indexed(embedded, failed)
            if after is None:
                await self._index.remove(id)
                return Indexed(embedded, failed)
        raise SearchIndexError(f"document {id} kept changing while it was indexed")

    async def _snapshot(self, id: DocumentId) -> _Snapshot | None:
        async with self._uow() as uow:
            document = await uow.documents.find(id)
            if document is None:
                return None
            return await _snapshot_of(uow, document)

    async def _read_text(self, id: DocumentId) -> str:
        try:
            data = await load_text(self._store, id)
        except NotFoundError:
            return ""  # not parsed yet
        return data.decode("utf-8", errors="replace")[: self._policy.max_text]

    async def _compose(
        self,
        snapshot: _Snapshot,
        text: str,
        state: IndexState | None,
        *,
        embed: bool = True,
        keep: bool = False,
    ) -> IndexDocument:
        """The index entry; `state` is what the index holds now (None: build for a new index).
        Without `embed` the entry has no vectors, or with `keep` the ones the index holds."""
        document = snapshot.document
        vectors: tuple[tuple[float, ...], ...] | None = ()
        stamp: EmbeddingStamp | None = None
        if not embed and keep and state is not None and state.embedding is not None:
            vectors = None
        if embed and self._embeddings is not None:
            sections = self._sections(snapshot, text)
            stamp = EmbeddingStamp(
                self._embeddings.model, _digest(self._embeddings.model, sections)
            )
            if state is not None and state.embedding == stamp:
                vectors, stamp = None, None  # the text did not change: keep the vectors
            else:
                result = await self._embeddings.embed(sections)
                if len(result.vectors) != len(sections):
                    raise EmbeddingsError(f"expected {len(sections)} vectors")
                wanted = self._policy.dimensions
                if wanted is not None and any(len(vector) != wanted for vector in result.vectors):
                    raise EmbeddingsError(
                        f"the vectors of {self._embeddings.model} do not have the "
                        f"{wanted} dimensions configured"
                    )
                vectors = tuple(tuple(vector) for vector in result.vectors)
        return IndexDocument(
            id=document.id,
            version=document.version,
            space_id=document.space_id,
            lane=document.lane,
            title=document.title,
            filename=document.original_filename,
            text=text,
            contact_id=document.contact_id,
            contact=snapshot.contact,
            document_type_id=document.document_type_id,
            document_type=snapshot.document_type,
            tag_ids=tuple(tag for tag, _ in snapshot.labels),
            tags=tuple(name for _, name in snapshot.labels),
            contact_group_ids=tuple(tag for tag, _ in snapshot.contact_groups),
            contact_groups=tuple(name for _, name in snapshot.contact_groups),
            document_type_group_ids=tuple(tag for tag, _ in snapshot.document_type_groups),
            document_type_groups=tuple(name for _, name in snapshot.document_type_groups),
            topic_ids=tuple(tag for tag, _ in snapshot.topics),
            topics=tuple(name for _, name in snapshot.topics),
            fields=_field_texts(document),
            field_ids=tuple(document.fields),
            document_date=document.document_date,
            created_at=document.created_at,
            confirmed=document.confirmed_at is not None,
            vectors=vectors,
            embedding=stamp,
        )

    def _sections(self, snapshot: _Snapshot, text: str) -> list[str]:
        """The texts that get a vector: the text in sections, the first one headed by what the
        document says about itself (the topic with its path; the tags it carries, without
        their ancestors: nesting a tag elsewhere costs no embedding)."""
        header = "\n".join(
            part
            for part in (
                snapshot.document.title,
                snapshot.contact,
                snapshot.document_type,
                snapshot.topic,
                ", ".join(name for _, name in snapshot.tags),
            )
            if part
        )
        sections = split_sections(text, self._policy.chunk_size, self._policy.max_chunks)
        sections[0:1] = [f"{header}\n\n{sections[0]}" if sections else header]
        prefix = self._policy.document_prefix
        return [prefix + section for section in sections]

    # --- master data renamed --------------------------------------------------------------------

    async def _refresh(self, kind: RefreshKind, item: UUID) -> None:
        """Queue an index job for every document with the contact, type or tag `item`: for a
        tag, also with a tag below it, with it or one below it as its topic, or with a contact
        or type in it or a group below it."""
        match kind:
            case RefreshKind.CONTACT:
                filters = [DocumentFilter(contacts=frozenset({ContactId(item)}))]
            case RefreshKind.DOCUMENT_TYPE:
                filters = [DocumentFilter(document_types=frozenset({DocumentTypeId(item)}))]
            case RefreshKind.TAG:
                async with self._uow() as uow:
                    tags = (await tag_tree(uow)).with_descendants([TagId(item)])
                filters = [
                    DocumentFilter(tags=(tags,)),
                    DocumentFilter(topics=tags),
                    DocumentFilter(contact_groups=(tags,)),
                    DocumentFilter(document_type_groups=(tags,)),
                ]
        carrying: dict[DocumentId, None] = {}
        for filter in filters:
            async for page in document_pages(self._uow, filter):
                carrying |= dict.fromkeys(document.id for document in page)
        await self._queue(list(carrying))

    async def _queue(self, documents: list[DocumentId]) -> None:
        # In order: two batches that share documents wait for each other's coalesce keys in the
        # same order, not crosswise (a deadlock in Postgres).
        documents = sorted(documents)
        for start in range(0, len(documents), _QUEUE_BATCH):
            async with self._uow() as uow:
                for id in documents[start : start + _QUEUE_BATCH]:
                    await uow.jobs.enqueue(
                        INDEX_JOB,
                        document_payload(id),
                        run_at=self._clock.now(),
                        coalesce_key=_index_key(id),
                    )
                await uow.commit()

    # --- the whole index ------------------------------------------------------------------------

    async def reconcile(self, also: Collection[DocumentId] = ()) -> Reconciled:
        """Queue index jobs for documents that are missing or stale in the index and remove
        entries of documents that are gone (`compare`). `also`: documents to queue in any
        case."""
        found = await self.compare(also)
        stale = list(found.stale)
        for id in found.extra:  # not in the database
            await self._index.remove(id)
        await self._queue(stale)
        log.info(
            "search index reconciled", extra={"queued": len(stale), "removed": len(found.extra)}
        )
        return Reconciled(queued=len(stale), removed=len(found.extra))

    async def compare(self, also: Collection[DocumentId] = ()) -> IndexComparison:
        """The index against the database. A stale document has another version than the
        database or an older layout (`LAYOUT`), or (with embeddings) vectors of no or another
        model; a current one in `also` counts as asked for."""
        asking = set(also)
        indexed = {state.id: state async for state in self._index.states()}
        model = None if self._embeddings is None else self._embeddings.model
        current = 0
        missing: list[DocumentId] = []
        outdated: list[DocumentId] = []
        other_model: list[DocumentId] = []
        asked: list[DocumentId] = []
        async for page in document_pages(self._uow):
            for document in page:
                state = indexed.pop(document.id, None)
                if state is None:
                    missing.append(document.id)
                elif state.version != document.version or state.layout != LAYOUT:
                    outdated.append(document.id)
                elif model is not None and (
                    state.embedding is None or state.embedding.model != model
                ):
                    other_model.append(document.id)
                elif document.id in asking:
                    asked.append(document.id)
                else:
                    current += 1
        return IndexComparison(
            current,
            tuple(missing),
            tuple(outdated),
            tuple(other_model),
            tuple(indexed),
            tuple(asked),
        )

    async def check(self, actor: UserId) -> IndexCheck:
        """Admins only: compare the index with the database (`compare`) and count; nothing is
        queued or removed (the next reconciliation does that)."""
        async with self._uow() as uow:
            await require_admin(uow, actor, Action.CHECK_INDEX)
        started = self._clock.now()
        comparison = await self.compare()
        return IndexCheck(comparison, self._clock.now() - started)

    async def status(self, actor: UserId) -> IndexStatus:
        """The state of the index for every user (`IndexStatus`). The durations come from the
        latest done index jobs (`_SAMPLE`), counted at most once a minute; the rate from the
        jobs done in the last ten minutes, every time."""
        now = self._clock.now()
        async with self._uow() as uow:
            await load_actor(uow, actor)
            documents = await uow.documents.count_all()
            overview = await uow.jobs.overview(now=now)
            recent = await uow.jobs.finished(
                since=now - _RATE_WINDOW, kinds=[INDEX_JOB], limit=_SAMPLE
            )
        stats = await self._index.stats()
        counts = {item.state: item.count for item in overview.counts if item.kind == INDEX_JOB}
        running = counts.get(JobState.RUNNING, 0)
        queued = sum(counts.get(state, 0) for state in OPEN_STATES) - running
        remaining: timedelta | None = None
        if queued == 0:
            remaining = timedelta(0)
        elif recent:
            remaining = _RATE_WINDOW * queued / len(recent)
        durations = await self._kept.get("durations", self._durations)
        return IndexStatus(
            documents=documents,
            stats=stats,
            running=running,
            queued=queued,
            remaining=remaining,
            embedded=durations.embedded,
            plain=durations.plain,
            per_section=durations.per_section,
            model=None if self._embeddings is None else self._embeddings.model,
            dimensions=None if self._embeddings is None else self._policy.dimensions,
            since=durations.since,
        )

    async def _durations(self) -> "_Durations":
        """How long the latest done index jobs ran, those that embedded and those that only
        wrote the words; a job whose embedding failed counts as neither."""
        since = self._clock.now() - self._policy.durations_window
        async with self._uow() as uow:
            finished = await uow.jobs.finished(since=since, kinds=[INDEX_JOB], limit=_SAMPLE)
        measured = [job for job in finished if job.result is not None and not _failed(job)]
        embedded = [job for job in measured if _sections(job) > 0]
        plain = [job for job in measured if _sections(job) == 0]
        sections = sum(_sections(job) for job in embedded)
        per_section = (
            sum((job.finished_at - job.started_at for job in embedded), timedelta(0)) / sections
            if sections
            else None
        )
        return _Durations(_times(embedded), _times(plain), per_section, since)

    async def rebuild(self, progress: Callable[[int, int], None] | None = None) -> Rebuilt:
        """Build a new index from the database and the object store while the active one keeps
        serving, swap it in, and reconcile what changed meanwhile. `progress(done, total)`."""
        ids = sorted([document.id async for page in document_pages(self._uow) for document in page])
        build = await self._index.begin_rebuild()
        built: dict[DocumentId, tuple[object, ...]] = {}
        try:
            added = 0
            for start in range(0, len(ids), self._policy.batch_size):
                entries = []
                for id in ids[start : start + self._policy.batch_size]:
                    snapshot = await self._snapshot(id)
                    if snapshot is not None:  # deleted meanwhile
                        built[id] = snapshot.key
                        entries.append(
                            await self._compose(snapshot, await self._read_text(id), None)
                        )
                await build.add(entries)
                added += len(entries)
                if progress is not None:
                    progress(start + len(ids[start : start + self._policy.batch_size]), len(ids))
            await build.finish()
        except BaseException:
            await asyncio.shield(build.abort())
            raise
        # Jobs that ran during the rebuild wrote to the old index. What changed since a document
        # was built, a rename of a contact, type or tag included, is queued again.
        changed = []
        for id, key in built.items():
            current = await self._snapshot(id)
            if current is None or current.key != key:
                changed.append(id)
        reconciled = await self.reconcile(changed)
        log.info("search index rebuilt", extra={"documents": added})
        return Rebuilt(documents=added, queued=reconciled.queued, removed=reconciled.removed)


def _sections(job: FinishedJob) -> int:
    """The sections a done index job embedded; 0 for one that reported none."""
    value = (job.result or {}).get("sections")
    return value if isinstance(value, int) else 0


def _failed(job: FinishedJob) -> bool:
    """Whether a done index job wrote without vectors because the embedding failed."""
    return (job.result or {}).get("embedding_failed") is True


def _times(jobs: Collection[FinishedJob]) -> JobTimes | None:
    runs = [max(timedelta(0), job.finished_at - job.started_at) for job in jobs]
    middle, top = median(runs), percentile(runs, 0.9)
    if middle is None or top is None:
        return None
    return JobTimes(len(runs), middle, top)


async def _snapshot_of(uow: UnitOfWork, document: Document) -> _Snapshot:
    tree = await tag_tree(uow)
    contact, contact_groups = None, frozenset[TagId]()
    if document.contact_id is not None:
        found = await uow.contacts.find(document.contact_id)
        if found is not None:
            contact, contact_groups = found.name, found.group_ids
    document_type, type_groups = None, frozenset[TagId]()
    if document.document_type_id is not None:
        kind = await uow.document_types.find(document.document_type_id)
        if kind is not None:
            document_type, type_groups = kind.name, kind.group_ids

    def named(ids: Collection[TagId]) -> _Named:
        known = sorted((id for id in ids if id in tree), key=str)
        return tuple((id, tree.tags[id].name) for id in known)

    topic = document.topic_id if document.topic_id in tree else None
    return _Snapshot(
        document,
        contact,
        document_type,
        tags=named(document.tag_ids),
        labels=named(tree.with_ancestors(document.tag_ids)),
        contact_groups=named(tree.with_ancestors(contact_groups)),
        document_type_groups=named(tree.with_ancestors(type_groups)),
        topics=named(tree.with_ancestors([topic] if topic else [])),
        topic=None if topic is None else tree.label(topic),
    )


def _digest(model: str, sections: list[str]) -> str:
    return hashlib.sha256("\0".join([model, *sections]).encode()).hexdigest()[:16]


def _field_texts(document: Document) -> tuple[str, ...]:
    texts = []
    for value in document.fields.values():
        text = _field_text(value)
        if text:
            texts.append(text)
    return tuple(texts)


def _field_text(value: FieldValue) -> str:
    """A value as the words a person would search for. Yes/no values say nothing without
    their field's name."""
    match value:
        case bool():
            return ""
        case Money():
            return f"{value.amount:f} {value.currency}"
        case Decimal():
            return f"{value:f}"
        case Url():
            return value.value
        case str():
            return value
        case Period():
            return _period_text(value)
        case date():  # in both notations
            return f"{value.isoformat()} {value:%d.%m.%Y}"


def _period_text(period: Period) -> str:
    """A period as it is searched for: its ends in both notations, what it is in ISO 8601
    (`2026-09`, `2026-W38`, `2026-Q3`, `2026`) and in words (`September 2026` in German and
    English, `KW 38 2026`, `Q3 2026`)."""
    start, end = period.start, period.end
    words = [f"{start.isoformat()} {start:%d.%m.%Y}"]
    if end != start:
        words.append(f"{end.isoformat()} {end:%d.%m.%Y}")
    match period.kind:
        case PeriodKind.WEEK:
            year, week = period.iso_week
            words.append(f"KW {week} {year}")
        case PeriodKind.MONTH:
            names = {names[start.month - 1] for names in MONTH_NAMES.values()}
            words += [f"{name} {start.year}" for name in sorted(names)]
            words.append(f"{start:%m/%Y} {start:%m.%Y}")
        case PeriodKind.QUARTER:
            words.append(f"Q{period.quarter_number} {start.year}")
    if period.kind not in (PeriodKind.DAY, PeriodKind.SPAN):
        words.append(period.notation)
    return " ".join(words)


_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def split_sections(text: str, size: int, limit: int) -> list[str]:
    """The text in at most `limit` sections of about `size` characters, cut at paragraph
    breaks (or at a space, inside a paragraph longer than `size`)."""
    sections: list[str] = []
    current = ""
    for paragraph in (part.strip() for part in _PARAGRAPH_BREAK.split(text)):
        if not paragraph:
            continue
        while len(paragraph) > size:
            cut = paragraph.rfind(" ", size // 2, size)
            cut = size if cut == -1 else cut
            if current:
                sections.append(current)
                current = ""
            sections.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if current and len(current) + 2 + len(paragraph) > size:
            sections.append(current)
            current = ""
        current = f"{current}\n\n{paragraph}" if current else paragraph
        if len(sections) >= limit:
            break
    if current and len(sections) < limit:
        sections.append(current)
    return [section for section in sections[:limit] if section]
