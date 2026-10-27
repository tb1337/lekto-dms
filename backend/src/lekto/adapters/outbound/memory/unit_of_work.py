"""In-memory unit of work: changes are buffered and applied to the database on commit.

Behaves like a database transaction with read-committed isolation and optimistic locking:
reads see committed data plus the unit's own changes; commit checks that every row written
still has the version it had when the unit first touched it, and that uniqueness holds.
"""

import asyncio
import copy
import dataclasses
from collections import Counter
from collections.abc import Callable, Collection, Hashable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Self, cast
from uuid import UUID

from lekto.adapters.outbound.memory.classifier_models import MemoryClassifierModelRepository
from lekto.adapters.outbound.memory.database import (
    API_TOKENS,
    CLASSIFIER_MODELS,
    CONTACTS,
    CREDENTIALS,
    DOCUMENT_FACTS,
    DOCUMENT_RELATIONS,
    DOCUMENT_TYPES,
    DOCUMENTS,
    EXTERNAL_IDENTITIES,
    FIELDS,
    LENSES,
    LOGIN_FAILURES,
    PROFILES,
    RULE_APPLICATIONS,
    RULES,
    SESSIONS,
    SPACES,
    TAGS,
    TASKS,
    USERS,
    WEBHOOKS,
    FactsRow,
    MemoryDatabase,
    RelationRow,
    SeenMark,
    Table,
    relation_row_id,
)
from lekto.adapters.outbound.memory.identity import (
    MemoryApiTokenRepository,
    MemoryCredentialRepository,
    MemoryExternalIdentityRepository,
    MemoryLoginFailureRepository,
    MemorySessionRepository,
)
from lekto.adapters.outbound.memory.inbox import MemoryInboxRepository, SeenKey
from lekto.adapters.outbound.memory.lenses import MemoryLensRepository
from lekto.adapters.outbound.memory.ordering import Rank, rank
from lekto.adapters.outbound.memory.processing_facts import MemoryProcessingFacts, VerdictKey
from lekto.adapters.outbound.memory.rows import _REMOVED, MemoryRepository, _copy
from lekto.adapters.outbound.memory.rules import (
    MemoryRuleApplicationRepository,
    MemoryRuleRepository,
)
from lekto.adapters.outbound.memory.tasks import MemoryTaskRepository
from lekto.adapters.outbound.memory.webhooks import MemoryWebhookRepository
from lekto.core.domain.document_facts import (
    DocumentFact,
    FactState,
    check_decided,
    check_found,
    fact_tokens,
    merged,
    reading_order,
    withdrawn,
)
from lekto.core.domain.documents import Document, Sha256
from lekto.core.domain.entity import Entity
from lekto.core.domain.errors import ConcurrencyError, ConflictError, NotFoundError
from lekto.core.domain.events import DomainEvent
from lekto.core.domain.fields import FieldDefinition
from lekto.core.domain.first_runs import FieldVerdict, FirstRun
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import (
    ContactId,
    DocumentId,
    DocumentTypeId,
    FieldId,
    JobId,
    SpaceId,
    TagId,
    UserId,
    new_id,
)
from lekto.core.domain.inbox import Confirmation
from lekto.core.domain.jobs import FinishedJob, Job, JobCount, JobOverview, JobState, JobStatus
from lekto.core.domain.json_value import JsonObject, JsonValue
from lekto.core.domain.master_data import Contact, DocumentType, MasterData, Tag, TagScope
from lekto.core.domain.permissions import Reach
from lekto.core.domain.pipeline import NodeRun
from lekto.core.domain.profiles import Profile
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.relations import Relation
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import User
from lekto.core.domain.validation import name_key, require_utc
from lekto.core.domain.verdict import KnownLabels
from lekto.core.ports.repository import (
    NEWEST_FIRST,
    CountBy,
    DocumentFilter,
    DocumentOrder,
    DocumentPosition,
    FacetRow,
    FilterView,
)
from lekto.core.ports.wakeup import Channel


class MemoryUnitOfWork:
    def __init__(self, database: MemoryDatabase) -> None:
        self._db = database
        self._closed = False
        self._writes: dict[str, dict[UUID, Entity[UUID] | None]] = {}
        self._tables: dict[str, Table[Any]] = {}  # the tables written to, of any kind
        self._base_versions: dict[tuple[str, UUID], int | None] = {}
        self._log: list[NodeRun] = []
        self._events: list[DomainEvent] = []
        self._jobs: dict[JobId, Job] = {}
        self._job_base: dict[JobId, Job | None] = {}
        self._purged_jobs: set[JobId] = set()
        self._signals: set[tuple[Channel, str | None]] = set()  # sent after the commit
        self._held: asyncio.Lock | None = None
        # The inbox's marks this unit wrote; None removes one.
        self._seen: dict[SeenKey, SeenMark | None] = {}
        self._confirmations: dict[DocumentId, Confirmation | None] = {}
        # The processing facts this unit wrote.
        self._first_runs: dict[DocumentId, FirstRun] = {}
        self._verdicts: dict[VerdictKey, FieldVerdict] = {}

        self.users = MemoryUserRepository(self, USERS)
        self.profiles = MemoryRepository[UserId, Profile](self, PROFILES)
        self.spaces = MemorySpaceRepository(self, SPACES)
        self.contacts = MemoryNamedRepository[ContactId, Contact](self, CONTACTS)
        self.document_types = MemoryNamedRepository[DocumentTypeId, DocumentType](
            self, DOCUMENT_TYPES
        )
        self.tags = MemoryTagRepository(self, TAGS)
        self.fields = MemoryNamedRepository[FieldId, FieldDefinition](self, FIELDS)
        self.documents = MemoryDocumentRepository(self, DOCUMENTS)
        self.processing_log = MemoryProcessingLog(self)
        self.processing_facts = MemoryProcessingFacts(self)
        self.document_facts = MemoryDocumentFactRepository(self)
        self.document_relations = MemoryDocumentRelationRepository(self)
        self.inbox = MemoryInboxRepository(self)
        self.rules = MemoryRuleRepository(self, RULES)
        self.rule_applications = MemoryRuleApplicationRepository(self, RULE_APPLICATIONS)
        self.classifier_models = MemoryClassifierModelRepository(self, CLASSIFIER_MODELS)
        self.webhooks = MemoryWebhookRepository(self, WEBHOOKS)
        self.tasks = MemoryTaskRepository(self, TASKS)
        self.lenses = MemoryLensRepository(self, LENSES)
        self.outbox = MemoryOutbox(self)
        self.jobs = MemoryJobQueue(self)
        self.credentials = MemoryCredentialRepository(self, CREDENTIALS)
        self.sessions = MemorySessionRepository(self, SESSIONS)
        self.api_tokens = MemoryApiTokenRepository(self, API_TOKENS)
        self.external_identities = MemoryExternalIdentityRepository(self, EXTERNAL_IDENTITIES)
        self.login_failures = MemoryLoginFailureRepository(self, LOGIN_FAILURES)

    # --- transaction ----------------------------------------------------------------------------

    async def __aenter__(self) -> Self:
        self._check_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if not self._closed:
            await self.rollback()

    async def lock(self, name: str) -> None:
        self._check_open()
        if self._held is not None:
            raise RuntimeError("a unit of work locks at most one name")
        lock = self._db.locks.setdefault(name, asyncio.Lock())
        await lock.acquire()
        self._held = lock

    def _release(self) -> None:
        if self._held is not None:
            self._held.release()
            self._held = None

    async def commit(self) -> None:
        self._check_open()
        try:
            self._commit()
        finally:
            self._release()

    def _commit(self) -> None:
        self._check_versions()
        self._check_uniqueness()
        self._check_jobs()
        for table_name, writes in self._writes.items():
            rows = self._db.tables.setdefault(table_name, {})
            for id, row in writes.items():
                if row is _REMOVED:
                    rows.pop(id, None)
                else:
                    rows[id] = row
        self._db.processing_log.extend(self._log)
        removed = {
            id for id, row in self._writes.get(DOCUMENTS.name, {}).items() if row is _REMOVED
        }
        self._db.processing_log[:] = [
            entry for entry in self._db.processing_log if entry.document_id not in removed
        ]
        self._commit_inbox(removed)
        self._commit_facts(removed)
        self._db.outbox.extend(self._events)
        recorded_at = datetime.now(UTC)
        self._db.recorded_at.update((event.id, recorded_at) for event in self._events)
        self._db.jobs.update(self._jobs)
        for id in self._purged_jobs:
            self._db.jobs.pop(id, None)
        self._closed = True
        for channel, kind in sorted(self._signals, key=lambda signal: (signal[0], signal[1] or "")):
            for listener in self._db.listeners:
                listener(channel, kind)

    def _commit_inbox(self, removed: set[UUID]) -> None:
        """Apply the inbox's marks; those of removed documents go with them."""
        for key, mark in self._seen.items():
            if mark is None:
                self._db.seen.pop(key, None)
            else:
                self._db.seen[key] = mark
        for document, confirmation in self._confirmations.items():
            if confirmation is None:
                self._db.confirmations.pop(document, None)
            else:
                self._db.confirmations[document] = confirmation
        for key in [key for key in self._db.seen if key[1] in removed]:
            del self._db.seen[key]
        for id in removed:
            self._db.confirmations.pop(DocumentId(id), None)

    def _commit_facts(self, removed: set[UUID]) -> None:
        """Add the processing facts, first write winning; those of removed documents go with
        them."""
        for document, run in self._first_runs.items():
            self._db.first_runs.setdefault(document, run)
        for key, verdict in self._verdicts.items():
            self._db.verdicts.setdefault(key, verdict)
        for id in removed:
            self._db.first_runs.pop(DocumentId(id), None)
        for key in [key for key in self._db.verdicts if key[0] in removed]:
            del self._db.verdicts[key]

    async def rollback(self) -> None:
        self._check_open()
        self._closed = True
        self._release()

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("the unit of work is closed")

    def _check_versions(self) -> None:
        for (table_name, id), base in self._base_versions.items():
            committed = self._db.tables.get(table_name, {}).get(id)
            if (None if committed is None else committed.version) != base:
                raise ConcurrencyError(f"{table_name} {id} was changed concurrently")

    def _check_uniqueness(self) -> None:
        for table_name in self._writes:
            self._unique_or_fail(self._tables[table_name], self._rows(self._tables[table_name]))

    def _check_jobs(self) -> None:
        for id, base in self._job_base.items():
            if self._db.jobs.get(id) != base:
                raise ConcurrencyError(f"job {id} was changed concurrently")
        for job in self._jobs.values():
            if job.dedup_key is not None and job.status.is_active:
                for other in self._db.jobs.values():
                    if (
                        other.id not in self._jobs
                        and other.id not in self._purged_jobs
                        and other.dedup_key == job.dedup_key
                        and other.status.is_active
                    ):
                        raise ConflictError(f"an active job with key {job.dedup_key} exists")
            if job.coalesce_key is not None:
                for other in self._db.jobs.values():
                    if (
                        other.id not in self._jobs
                        and other.id not in self._purged_jobs
                        and other.coalesce_key == job.coalesce_key
                    ):
                        raise ConflictError(f"a queued job with key {job.coalesce_key} exists")

    # --- rows -----------------------------------------------------------------------------------
    # A table holds rows of its own kind only: those of `Table[E]` are `E`.

    def _rows[E: Entity[UUID]](self, table: Table[E]) -> list[E]:
        """Committed rows with this unit's changes applied (not copied)."""
        committed = self._db.tables.get(table.name, {})
        writes = self._writes.get(table.name, {})
        rows = [writes.get(id, row) for id, row in committed.items()]
        rows += [row for id, row in writes.items() if id not in committed]
        return cast(list[E], [row for row in rows if row is not _REMOVED])

    def _row[E: Entity[UUID]](self, table: Table[E], id: UUID) -> E | None:
        writes = self._writes.get(table.name, {})
        row = writes[id] if id in writes else self._db.tables.get(table.name, {}).get(id)
        return cast(E | None, row)

    def _write[E: Entity[UUID]](self, table: Table[E], id: UUID, row: E | None) -> None:
        self._check_open()
        key = (table.name, id)
        if key not in self._base_versions:
            committed = self._db.tables.get(table.name, {}).get(id)
            self._base_versions[key] = None if committed is None else committed.version
        self._tables[table.name] = table
        self._writes.setdefault(table.name, {})[id] = row

    def _check_unreferenced[E: Entity[UUID]](self, table: Table[E], id: UUID) -> None:
        """ConflictError if a row refers to the row `id` of `table`: the SQL schema's foreign
        keys without a cascade refuse its removal so."""
        for referring, refers in _REFERRERS.get(table.name, ()):
            if any(refers(row, id) for row in self._rows(referring)):
                raise ConflictError(f"a {referring.name} still refers to {table.name} {id}")

    @staticmethod
    def _unique_or_fail[E: Entity[UUID]](table: Table[E], rows: Iterable[E]) -> None:
        seen: set[Hashable] = set()
        for row in rows:
            for key in table.unique_keys(row):
                if key in seen:
                    raise ConflictError(f"{table.name} already exists: {key}")
                seen.add(key)


# What refers to a row, as the SQL schema's foreign keys without ON DELETE CASCADE do.
_REFERRERS: dict[str, tuple[tuple[Table[Any], Callable[[Any, UUID], bool]], ...]] = {
    USERS.name: ((SPACES, lambda space, id: space.personal_of == id or id in space.members),),
    SPACES.name: ((DOCUMENTS, lambda document, id: document.space_id == id),),
    CONTACTS.name: ((DOCUMENTS, lambda document, id: document.contact_id == id),),
    DOCUMENT_TYPES.name: (
        (DOCUMENTS, lambda document, id: document.document_type_id == id),
        (FIELDS, lambda field, id: id in (field.document_type_ids or ())),
    ),
    TAGS.name: (
        (TAGS, lambda tag, id: tag.parent_id == id),
        (
            CONTACTS,
            lambda contact, id: (
                id in contact.group_ids
                or id in contact.topic_ids
                or any(item.topic_id == id for item in contact.identifiers)
            ),
        ),
        (DOCUMENT_TYPES, lambda kind, id: id in kind.group_ids),
        (DOCUMENTS, lambda document, id: document.topic_id == id or id in document.tag_ids),
    ),
    FIELDS.name: ((DOCUMENTS, lambda document, id: id in document.fields),),
}


class MemoryNamedRepository[K: UUID, E: MasterData](MemoryRepository[K, E]):
    async def find_by_name(self, name: str) -> E | None:
        key = name_key(name)
        return next((_copy(row) for row in self._all() if name_key(row.name) == key), None)


class MemoryTagRepository(MemoryNamedRepository[TagId, Tag]):
    async def find_by_name(self, name: str, scope: TagScope = TagScope.DOCUMENT) -> Tag | None:
        key = name_key(name)
        return next(
            (_copy(row) for row in self._all() if row.scope is scope and name_key(row.name) == key),
            None,
        )


class MemoryUserRepository(MemoryRepository[UserId, User]):
    async def find_by_username(self, username: str) -> User | None:
        key = name_key(username)
        return next((_copy(row) for row in self._all() if name_key(row.username) == key), None)

    async def remove(self, id: UserId) -> None:
        """As the SQL schema's foreign keys: the user's documents keep no uploader (SET NULL),
        the contacts' identifiers that named them and their profile go with them (CASCADE)."""
        await self.get(id)
        self._uow._check_unreferenced(self._table, id)
        for row in self._uow._rows(DOCUMENTS):
            if row.uploaded_by == id:
                changed = _copy(row)
                changed.uploaded_by = None
                self._uow._write(DOCUMENTS, row.id, changed)
        for contact in self._uow._rows(CONTACTS):
            if any(item.user_id == id for item in contact.identifiers):
                updated = _copy(contact)
                updated.identifiers = [item for item in contact.identifiers if item.user_id != id]
                self._uow._write(CONTACTS, contact.id, updated)
        if self._uow._row(PROFILES, id) is not None:
            self._uow._write(PROFILES, id, _REMOVED)
        self._uow._write(self._table, id, _REMOVED)


class MemorySpaceRepository(MemoryRepository[SpaceId, Space]):
    async def get_personal(self, user: UserId) -> Space:
        for row in self._all():
            if row.personal_of == user:
                return _copy(row)
        raise NotFoundError("personal space of user", user)

    async def personal_ids(self) -> dict[UserId, SpaceId]:
        return {row.personal_of: row.id for row in self._all() if row.personal_of is not None}

    async def find_by_name(self, name: str) -> Space | None:
        key = name_key(name)
        return next(
            (
                _copy(row)
                for row in self._all()
                if row.personal_of is None and name_key(row.name) == key
            ),
            None,
        )

    async def list_accessible(self, user: UserId) -> list[Space]:
        return [_copy(row) for row in self._all() if user in row.members]

    async def remove(self, id: SpaceId) -> None:
        """With its rules, as the SQL schema's ON DELETE CASCADE."""
        await self.get(id)
        self._uow._check_unreferenced(self._table, id)
        await self._uow.rules.remove_for_space(id)
        self._uow._write(self._table, id, _REMOVED)


class MemoryDocumentRepository(MemoryRepository[DocumentId, Document]):
    async def find_by_sha256(self, sha256: Sha256) -> Document | None:
        return next((_copy(row) for row in self._all() if row.sha256 == sha256), None)

    async def list_visible_to(self, user: UserId) -> list[Document]:
        reach = Reach.of(user, await self._uow.spaces.list_accessible(user))
        return [_copy(row) for row in self._all() if reach.allows(row)]

    async def field_in_use(
        self,
        field: FieldId,
        *,
        values: Collection[str] | None = None,
        outside_types: Collection[DocumentTypeId] | None = None,
    ) -> bool:
        return any(
            field in row.fields
            and (values is None or row.fields[field] in set(values))
            and (outside_types is None or row.document_type_id not in set(outside_types))
            for row in self._all()
        )

    async def query_visible(
        self,
        user: UserId,
        filter: DocumentFilter,
        *,
        order: DocumentOrder = NEWEST_FIRST,
        after: DocumentPosition | None = None,
        limit: int,
    ) -> list[Document]:
        visible = await self.list_visible_to(user)
        return _query(visible, filter, self._groups(), order=order, after=after, limit=limit)

    async def query(
        self,
        filter: DocumentFilter,
        *,
        order: DocumentOrder = NEWEST_FIRST,
        after: DocumentPosition | None = None,
        limit: int,
    ) -> list[Document]:
        every = [_copy(row) for row in self._all()]
        return _query(every, filter, self._groups(), order=order, after=after, limit=limit)

    async def facet_rows(self, filter: DocumentFilter, user: UserId | None) -> list[FacetRow]:
        documents = (
            [_copy(row) for row in self._all()]
            if user is None
            else await self.list_visible_to(user)
        )
        groups = self._groups()
        return [
            FacetRow(
                contact=document.contact_id,
                document_type=document.document_type_id,
                topic=document.topic_id,
                tags=frozenset(document.tag_ids),
                document_date=document.document_date,
            )
            for document in documents
            if filter.matches(groups.view(document))
        ]

    def _groups(self) -> "_Groups":
        return _Groups(
            {row.id: row.group_ids for row in self._uow._rows(CONTACTS)},
            {row.id: row.group_ids for row in self._uow._rows(DOCUMENT_TYPES)},
            {row.id: fact_tokens(row.facts) for row in self._uow._rows(DOCUMENT_FACTS)},
        )

    async def count_tagged(
        self, sets: Mapping[UUID, Collection[TagId]], user: UserId | None
    ) -> dict[UUID, int]:
        documents = (
            [_copy(row) for row in self._all()]
            if user is None
            else await self.list_visible_to(user)
        )
        counts = {
            key: sum(bool(document.tag_ids & set(tags)) for document in documents)
            for key, tags in sets.items()
        }
        return {key: count for key, count in counts.items() if count}

    async def count_by(self, by: CountBy, user: UserId | None) -> dict[UUID, int]:
        documents = (
            [_copy(row) for row in self._all()]
            if user is None
            else await self.list_visible_to(user)
        )
        counts: dict[UUID, int] = {}
        for document in documents:
            match by:
                case CountBy.CONTACT:
                    keys: Collection[UUID] = [document.contact_id] if document.contact_id else []
                case CountBy.DOCUMENT_TYPE:
                    keys = [document.document_type_id] if document.document_type_id else []
                case CountBy.TOPIC:
                    keys = [document.topic_id] if document.topic_id else []
                case CountBy.TAG:
                    keys = document.tag_ids
                case CountBy.FIELD:
                    keys = document.fields.keys()
            for key in keys:
                counts[key] = counts.get(key, 0) + 1
        return counts

    async def count_all(self) -> int:
        return len(self._all())

    async def count_confirmed(self, *, after: datetime | None = None) -> int:
        def decided(at: datetime | None) -> bool:
            return at is not None and (after is None or at > after)

        return sum(
            decided(row.confirmed_at) or decided(row.space_confirmed_at) for row in self._all()
        )

    async def confirmed_labels(self, reader: UserId) -> KnownLabels:
        readable = await self.list_visible_to(reader)
        confirmed = [row for row in readable if row.confirmed_at is not None]
        spaces = {space.id: space for space in self._uow._rows(SPACES)}
        own = next((space.id for space in spaces.values() if space.personal_of == reader), None)
        decided = frozenset(
            own
            if own is not None and spaces[row.space_id].personal_of == row.uploaded_by
            else row.space_id
            for row in confirmed
            if row.space_confirmed_at is not None and row.space_id in spaces
        )
        return KnownLabels(
            spaces=decided,
            contacts=frozenset(row.contact_id for row in confirmed if row.contact_id is not None),
            document_types=frozenset(
                row.document_type_id for row in confirmed if row.document_type_id is not None
            ),
            tags=frozenset(tag for row in confirmed for tag in row.tag_ids),
            topics=frozenset(row.topic_id for row in confirmed if row.topic_id is not None),
        )

    async def exists(
        self,
        *,
        uploaded_by: UserId | None = None,
        space: SpaceId | None = None,
        contact: ContactId | None = None,
        document_type: DocumentTypeId | None = None,
        tag: TagId | None = None,
        topic: TagId | None = None,
        field: FieldId | None = None,
        sha256: Sha256 | None = None,
    ) -> bool:
        criteria = (uploaded_by, space, contact, document_type, tag, topic, field, sha256)
        if all(value is None for value in criteria):
            raise ValueError("exists needs at least one criterion")
        return any(
            (uploaded_by is None or row.uploaded_by == uploaded_by)
            and (space is None or row.space_id == space)
            and (contact is None or row.contact_id == contact)
            and (document_type is None or row.document_type_id == document_type)
            and (tag is None or tag in row.tag_ids)
            and (topic is None or row.topic_id == topic)
            and (field is None or field in row.fields)
            and (sha256 is None or row.sha256 == sha256)
            for row in self._all()
        )


class MemoryProcessingLog:
    def __init__(self, uow: MemoryUnitOfWork) -> None:
        self._uow = uow

    async def append(self, run: NodeRun) -> None:
        self._uow._check_open()
        self._uow._log.append(run)

    async def list_for(self, document: DocumentId) -> list[NodeRun]:
        self._uow._check_open()
        if self._uow._row(DOCUMENTS, document) is _REMOVED:
            return []
        entries = [*self._uow._db.processing_log, *self._uow._log]
        return [entry for entry in entries if entry.document_id == document]


class MemoryDocumentRelationRepository:
    def __init__(self, uow: MemoryUnitOfWork) -> None:
        self._uow = uow

    def _live(self) -> list[Relation]:
        """The relations whose documents are both there (the database cascades)."""
        return [
            row.relation
            for row in self._uow._rows(DOCUMENT_RELATIONS)
            if self._uow._row(DOCUMENTS, row.relation.newer) is not _REMOVED
            and self._uow._row(DOCUMENTS, row.relation.older) is not _REMOVED
        ]

    async def of_document(self, document: DocumentId) -> list[Relation]:
        return await self.of_documents([document])

    async def of_documents(self, documents: Collection[DocumentId]) -> list[Relation]:
        self._uow._check_open()
        wanted = set(documents)
        found = [item for item in self._live() if item.newer in wanted or item.older in wanted]
        return sorted(found, key=lambda item: (item.created_at, item.key), reverse=True)

    async def find(self, newer: DocumentId, older: DocumentId) -> Relation | None:
        self._uow._check_open()
        return next((item for item in self._live() if item.key == (newer, older)), None)

    async def put(self, relation: Relation) -> None:
        self._uow._check_open()
        id = relation_row_id(relation.newer, relation.older)
        current = self._uow._row(DOCUMENT_RELATIONS, id)
        version = 1 if current is _REMOVED else current.version + 1
        self._uow._write(DOCUMENT_RELATIONS, id, RelationRow(id, relation, version))

    async def remove(self, newer: DocumentId, older: DocumentId) -> None:
        self._uow._check_open()
        id = relation_row_id(newer, older)
        if self._uow._row(DOCUMENT_RELATIONS, id) is not _REMOVED:
            self._uow._write(DOCUMENT_RELATIONS, id, _REMOVED)


class MemoryDocumentFactRepository:
    def __init__(self, uow: MemoryUnitOfWork) -> None:
        self._uow = uow

    async def of_document(self, document: DocumentId) -> list[DocumentFact]:
        self._uow._check_open()
        if self._uow._row(DOCUMENTS, document) is _REMOVED:
            return []  # its facts go with it, as the database cascades
        row = self._uow._row(DOCUMENT_FACTS, document)
        return [] if row is _REMOVED else list(row.facts)

    async def of_documents(
        self, documents: Collection[DocumentId]
    ) -> dict[DocumentId, list[DocumentFact]]:
        found = {id: await self.of_document(id) for id in documents}
        return {id: facts for id, facts in found.items() if facts}

    async def replace_found(self, document: DocumentId, found: Collection[DocumentFact]) -> None:
        self._uow._check_open()
        check_found(found)
        self._keep(document, lambda kept: merged(kept, found))

    async def decide(self, document: DocumentId, fact: DocumentFact) -> None:
        self._uow._check_open()
        check_decided(fact)
        self._keep(
            document,
            lambda kept: sorted(
                [item for item in kept if item.key != fact.key] + [fact], key=reading_order
            ),
        )

    async def withdraw(self, document: DocumentId, key: tuple[IdentifierKind, str]) -> None:
        self._uow._check_open()

        def change(kept: tuple[DocumentFact, ...]) -> list[DocumentFact]:
            facts = []
            for fact in kept:
                if fact.key != key or not fact.state.by_person:
                    facts.append(fact)
                elif (found := withdrawn(fact)) is not None:
                    facts.append(found)
            return facts

        self._keep(document, change)

    def _keep(
        self,
        document: DocumentId,
        change: Callable[[tuple[DocumentFact, ...]], Iterable[DocumentFact]],
    ) -> None:
        current = self._uow._row(DOCUMENT_FACTS, document)
        kept = () if current is _REMOVED else current.facts
        version = 1 if current is _REMOVED else current.version + 1
        facts = tuple(change(kept))
        self._uow._write(
            DOCUMENT_FACTS, document, FactsRow(id=document, facts=facts, version=version)
        )

    async def contacts_of(
        self, identifiers: Collection[tuple[IdentifierKind, str]]
    ) -> dict[tuple[IdentifierKind, str], frozenset[ContactId]]:
        self._uow._check_open()
        wanted = set(identifiers)
        found: dict[tuple[IdentifierKind, str], set[ContactId]] = {}
        for document in self._uow._rows(DOCUMENTS):
            if document.confirmed_at is None or document.contact_id is None:
                continue
            row = self._uow._row(DOCUMENT_FACTS, document.id)
            shown = {
                fact.key
                for fact in (() if row is _REMOVED else row.facts)
                if fact.state is not FactState.REJECTED
            }
            for key in wanted & shown:
                found.setdefault(key, set()).add(document.contact_id)
        return {key: frozenset(contacts) for key, contacts in found.items()}


class MemoryOutbox:
    def __init__(self, uow: MemoryUnitOfWork) -> None:
        self._uow = uow

    async def add(self, events: Iterable[DomainEvent]) -> None:
        self._uow._check_open()
        events = list(events)
        self._uow._events.extend(events)
        if events:
            self._uow._signals.add((Channel.EVENTS, None))


class MemoryJobQueue:
    def __init__(self, uow: MemoryUnitOfWork) -> None:
        self._uow = uow

    async def enqueue(
        self,
        kind: str,
        payload: Mapping[str, JsonValue],
        *,
        run_at: datetime,
        dedup_key: str | None = None,
        coalesce_key: str | None = None,
    ) -> JobId | None:
        if dedup_key is not None and coalesce_key is not None:
            raise ValueError("a job has a dedup key or a coalesce key, not both")
        if dedup_key is not None and any(
            job.dedup_key == dedup_key and job.status.is_active for job in self._all()
        ):
            return None
        if coalesce_key is not None and any(
            job.coalesce_key == coalesce_key for job in self._all()
        ):
            return None
        job = Job(
            id=JobId(new_id()),
            kind=kind,
            payload=copy.deepcopy(dict(payload)),
            dedup_key=dedup_key,
            coalesce_key=coalesce_key,
            status=JobStatus.QUEUED,
            attempts=0,
            run_at=require_utc(run_at, "run_at"),
        )
        self._write(job, queued=True)
        return job.id

    async def claim(
        self, *, now: datetime, lease: timedelta, kinds: Collection[str] | None = None
    ) -> Job | None:
        due = [job for job in self._all() if (at := _due_at(job, kinds)) is not None and at <= now]
        if not due:
            return None
        job = min(due, key=lambda job: (job.run_at, job.id))
        claimed = dataclasses.replace(
            job,
            status=JobStatus.RUNNING,
            attempts=job.attempts + 1,
            locked_until=now + lease,
            coalesce_key=None,
            started_at=now,
        )
        self._write(claimed)
        return copy.deepcopy(claimed)

    async def next_due(self, *, kinds: Collection[str] | None = None) -> datetime | None:
        times = [due for job in self._all() if (due := _due_at(job, kinds)) is not None]
        return min(times, default=None)

    async def extend(self, job: Job, *, until: datetime) -> None:
        current = await self._claimed(job)
        self._write(dataclasses.replace(current, locked_until=require_utc(until, "until")))

    async def complete(self, job: Job, *, now: datetime, result: JsonObject | None = None) -> None:
        current = await self._claimed(job)
        self._write(
            dataclasses.replace(
                current,
                status=JobStatus.DONE,
                locked_until=None,
                finished_at=require_utc(now, "now"),
                result=copy.deepcopy(dict(result)) if result is not None else None,
            )
        )

    async def reschedule(self, job: Job, *, run_at: datetime, error: str) -> None:
        current = await self._claimed(job)
        self._write(
            dataclasses.replace(
                current,
                status=JobStatus.QUEUED,
                run_at=require_utc(run_at, "run_at"),
                locked_until=None,
                last_error=error,
            ),
            queued=True,
        )

    async def release(self, job: Job, *, run_at: datetime, error: str) -> None:
        current = await self._claimed(job)
        self._write(
            dataclasses.replace(
                current,
                status=JobStatus.QUEUED,
                releases=current.releases + 1,
                run_at=require_utc(run_at, "run_at"),
                locked_until=None,
                last_error=error,
            ),
            queued=True,
        )

    async def fail(self, job: Job, *, now: datetime, error: str) -> None:
        current = await self._claimed(job)
        self._write(
            dataclasses.replace(
                current,
                status=JobStatus.FAILED,
                locked_until=None,
                last_error=error,
                finished_at=require_utc(now, "now"),
            )
        )

    async def retry(self, job: JobId, *, now: datetime) -> Job:
        current = await self.get(job)
        if current.status is not JobStatus.FAILED:
            raise ConflictError(because(ReasonCode.JOB_NOT_FAILED))
        if current.dedup_key is not None and any(
            other.dedup_key == current.dedup_key and other.status.is_active for other in self._all()
        ):
            raise ConflictError(because(ReasonCode.JOB_ALREADY_QUEUED))
        queued = dataclasses.replace(
            current,
            status=JobStatus.QUEUED,
            run_at=require_utc(now, "now"),
            attempts=0,
            releases=0,
            locked_until=None,
            started_at=None,
            finished_at=None,
            result=None,
        )
        self._write(queued, queued=True)
        return copy.deepcopy(queued)

    async def overview(self, *, now: datetime) -> JobOverview:
        counts = Counter((job.kind, job.state(now)) for job in self._all())
        started = [job.started_at for job in self._all() if job.started_at is not None]
        return JobOverview(
            counts=tuple(
                JobCount(kind, state, count) for (kind, state), count in sorted(counts.items())
            ),
            last_started=max(started, default=None),
        )

    async def find(
        self,
        *,
        now: datetime,
        states: Collection[JobState],
        kind: str | None = None,
        offset: int = 0,
        limit: int,
    ) -> list[Job]:
        found = [
            job
            for job in self._all()
            if job.state(now) in states and (kind is None or job.kind == kind)
        ]
        found.sort(key=lambda job: _job_order(job, now))
        return copy.deepcopy(found[offset : offset + limit])

    async def finished(
        self, *, since: datetime, kinds: Collection[str] | None = None, limit: int | None = None
    ) -> list[FinishedJob]:
        done = [
            job
            for job in self._all()
            if job.status is JobStatus.DONE
            and job.started_at is not None
            and job.finished_at is not None
            and job.finished_at >= since
            and (kinds is None or job.kind in kinds)
        ]
        done.sort(key=lambda job: (job.finished_at, job.id))
        if limit is not None:
            done = done[max(0, len(done) - limit) :]
        return [
            FinishedJob(
                kind=job.kind,
                run_at=job.run_at,
                started_at=job.started_at,
                finished_at=job.finished_at,
                result=copy.deepcopy(job.result),
            )
            for job in done
            if job.started_at is not None and job.finished_at is not None
        ]

    async def _claimed(self, job: Job) -> Job:
        current = await self.get(job.id)
        if current.status is not JobStatus.RUNNING or current.attempts != job.attempts:
            raise ConcurrencyError(f"job {job.id} is no longer held by this claim")
        return current

    async def get(self, job: JobId) -> Job:
        self._uow._check_open()
        found = self._uow._jobs.get(job) or self._uow._db.jobs.get(job)
        if found is None or job in self._uow._purged_jobs:
            raise NotFoundError("job", job)
        return copy.deepcopy(found)

    async def purge(self, *, before: datetime) -> int:
        finished = [
            job.id
            for job in self._all()
            if job.status in {JobStatus.DONE, JobStatus.FAILED} and job.run_at < before
        ]
        self._uow._purged_jobs.update(finished)
        return len(finished)

    def _all(self) -> list[Job]:
        self._uow._check_open()
        jobs = {**self._uow._db.jobs, **self._uow._jobs}
        return [job for id, job in jobs.items() if id not in self._uow._purged_jobs]

    def _write(self, job: Job, *, queued: bool = False) -> None:
        """`queued`: the job becomes queued, which the commit signals (`Wakeup`)."""
        self._uow._check_open()
        if job.id not in self._uow._job_base:
            self._uow._job_base[job.id] = self._uow._db.jobs.get(job.id)
        self._uow._jobs[job.id] = job
        if queued:
            self._uow._signals.add((Channel.JOBS, job.kind))


def _due_at(job: Job, kinds: Collection[str] | None) -> datetime | None:
    """When `claim` finds the job: a queued job at `run_at`, a running one when its lease
    ends; None for a finished job or one of another kind."""
    if kinds is not None and job.kind not in kinds:
        return None
    if job.status is JobStatus.QUEUED:
        return job.run_at
    if job.status is JobStatus.RUNNING:
        return job.locked_until
    return None


class MemoryUnitOfWorkFactory:
    """Creates units of work on one shared in-memory database."""

    def __init__(self, database: MemoryDatabase) -> None:
        self._database = database

    def __call__(self) -> MemoryUnitOfWork:
        return MemoryUnitOfWork(self._database)


@dataclass(frozen=True)
class _Groups:
    """The groups of each contact and document type."""

    contacts: Mapping[UUID, frozenset[TagId]]
    document_types: Mapping[UUID, frozenset[TagId]]
    facts: Mapping[UUID, frozenset[str]] = field(default_factory=dict)  # `fact_tokens`

    def view(self, document: Document) -> FilterView:
        return FilterView.of(
            document,
            contact_groups=self.contacts.get(document.contact_id or UUID(int=0), frozenset()),
            document_type_groups=self.document_types.get(
                document.document_type_id or UUID(int=0), frozenset()
            ),
            facts=self.facts.get(document.id, frozenset()),
        )


def _query(
    documents: list[Document],
    filter: DocumentFilter,
    groups: _Groups,
    *,
    order: DocumentOrder,
    after: DocumentPosition | None,
    limit: int,
) -> list[Document]:
    matching = [document for document in documents if filter.matches(groups.view(document))]
    ranked = sorted(matching, key=lambda document: _rank(document, order))
    if after is not None:
        # The documents after `after`: its rank is the one it had (the cursor's value).
        mark = _rank_of(after, order)
        ranked = [document for document in ranked if _rank(document, order) > mark]
    return ranked[:limit]


def _rank(document: Document, order: DocumentOrder) -> Rank:
    return _rank_of(DocumentPosition.of(document, order), order)


def _rank_of(position: DocumentPosition, order: DocumentOrder) -> Rank:
    return rank(order, position.id, position.value, ties_by_id=True)


_JOB_RANKS = {
    JobState.RUNNING: 0,
    JobState.DUE: 1,
    JobState.PLANNED: 2,
    JobState.FAILED: 3,
    JobState.DONE: 4,
}


def _job_order(job: Job, now: datetime) -> tuple[Any, ...]:
    """The order of `JobQueue.find`: by state, then by when it started (running), is due
    (queued) or finished, latest first (failed, done); then by id."""
    state = job.state(now)
    if state is JobState.RUNNING:
        when = (job.started_at or datetime.max.replace(tzinfo=UTC)).timestamp()
    elif state in {JobState.DUE, JobState.PLANNED}:
        when = job.run_at.timestamp()
    else:
        when = -(job.finished_at.timestamp()) if job.finished_at is not None else float("inf")
    return (_JOB_RANKS[state], when, job.id)
