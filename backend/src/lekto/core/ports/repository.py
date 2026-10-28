"""Metadata persistence: one repository per aggregate, all reached through the unit of work.

First adapter: SQLAlchemy on SQLite or Postgres (M2).

Common rules for every adapter:
- Reads return copies; changing an entity has no effect until `update` and commit.
- `add` keeps the entity's version; `update` succeeds only if the stored version equals the
  entity's version, then increments both. Otherwise it raises ConcurrencyError (at the latest on
  commit).
- Uniqueness (raises ConflictError at the latest on commit): usernames; display names of
  users (that none is another user's username the services check under a lock); names of the
  spaces that are nobody's personal one; one personal space per user; names of contacts,
  document types and field definitions, and of tags per scope; the original (SHA-256).
  Names compare regardless of case. The services look a name up before they write, for a
  message that names it ("'X' already exists"); the adapter's rule is the net for two
  requests at once, which the look-up cannot see.
- `get` raises NotFoundError, `find` returns None.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from lekto.core.domain.bulk import BulkOperation
from lekto.core.domain.classifier import ClassifierModel
from lekto.core.domain.document_facts import DocumentFact, FactCriterion
from lekto.core.domain.documents import Channel, Document, Sha256
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import FieldDefinition, sort_value
from lekto.core.domain.first_runs import FieldVerdict, FirstRun, Verdict
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import (
    BulkOperationId,
    ClassifierModelId,
    ContactId,
    DocumentId,
    DocumentTypeId,
    FieldId,
    LensId,
    RuleApplicationId,
    RuleId,
    SpaceId,
    TagId,
    TaskId,
    UserId,
    WebhookId,
)
from lekto.core.domain.inbox import Confirmation, InboxTab
from lekto.core.domain.lenses import Lens
from lekto.core.domain.master_data import Contact, DocumentType, Tag, TagScope
from lekto.core.domain.open_identifiers import Sighting
from lekto.core.domain.periods import Period
from lekto.core.domain.pipeline import Lane, Node, NodeRun
from lekto.core.domain.profiles import Profile
from lekto.core.domain.relations import Relation
from lekto.core.domain.rules import Rule, RuleApplication, RuleVersion
from lekto.core.domain.sorting import sort_key
from lekto.core.domain.spaces import Space
from lekto.core.domain.tasks import Task
from lekto.core.domain.users import User
from lekto.core.domain.verdict import KnownLabels
from lekto.core.domain.webhooks import DeliveryOutcome, Webhook, WebhookDelivery


class Repository[K, E](Protocol):
    async def get(self, id: K) -> E: ...

    async def find(self, id: K) -> E | None: ...

    async def add(self, entity: E) -> None: ...

    async def update(self, entity: E) -> None: ...

    async def list_all(self) -> list[E]:
        """All entities, in no particular order."""
        ...


class NamedRepository[K, E](Repository[K, E], Protocol):
    async def find_by_name(self, name: str) -> E | None:
        """Case-insensitive lookup."""
        ...

    async def remove(self, id: K) -> None:
        """Delete it; NotFoundError if missing. No document may refer to it."""
        ...


class UserRepository(Repository[UserId, User], Protocol):
    async def find_by_username(self, username: str) -> User | None:
        """Case-insensitive lookup."""
        ...

    async def remove(self, id: UserId) -> None:
        """Delete the user; NotFoundError if missing. Their personal space, their memberships
        of other spaces and their identity data must be removed first; the documents they
        uploaded keep no uploader (`Document.uploaded_by` becomes None)."""
        ...


class ProfileRepository(Repository[UserId, Profile], Protocol):
    """The users' private profiles, by user id; a user without one has none (`find` returns
    None). A profile goes with its user."""


class SpaceRepository(Repository[SpaceId, Space], Protocol):
    async def get_personal(self, user: UserId) -> Space:
        """The user's personal space; NotFoundError if there is none."""
        ...

    async def personal_ids(self) -> dict[UserId, SpaceId]:
        """The id of every user's personal space, by user."""
        ...

    async def find_by_name(self, name: str) -> Space | None:
        """Case-insensitive lookup among the spaces that are nobody's personal one."""
        ...

    async def list_accessible(self, user: UserId) -> list[Space]:
        """Spaces the user is a member of, in any role."""
        ...

    async def remove(self, id: SpaceId) -> None:
        """Delete the space with its members and rules; NotFoundError if missing. It must hold
        no documents."""
        ...


class ContactRepository(NamedRepository[ContactId, Contact], Protocol): ...


class DocumentTypeRepository(NamedRepository[DocumentTypeId, DocumentType], Protocol): ...


class TagRepository(NamedRepository[TagId, Tag], Protocol):
    async def find_by_name(self, name: str, scope: TagScope = TagScope.DOCUMENT) -> Tag | None:
        """Case-insensitive lookup among the tags of `scope` (names are unique per scope)."""
        ...

    async def remove(self, id: TagId) -> None:
        """Delete it; NotFoundError if missing. No document, contact, identifier, type or tag
        may refer to it."""
        ...


class FieldDefinitionRepository(NamedRepository[FieldId, FieldDefinition], Protocol): ...


type TagSets = tuple[frozenset[TagId], ...]


@dataclass(frozen=True, kw_only=True)
class DocumentFilter:
    """Criteria for listing documents; all given ones must match.

    `contacts`, `document_types`, `spaces`: the document's is one of them. `tags`: sets of
    tags; the document carries one tag of each set. The core gives a tag with its descendants
    as one set (`TagTree.with_descendants`), so no adapter walks the tree.
    `contact_groups`, `document_type_groups` likewise: the document's contact (type) is in one
    group of each set. `topics`: the document's topic is one of them (a topic with its
    descendants). `lanes`: one of them, where None stands for documents still in processing.
    `confirmed`: whether a person set or confirmed the metadata (`Document.confirmed_at`).
    `labelled`: whether a person confirmed the metadata or decided the space (the classifier's
    examples; not in the search index).
    `field`: a value for it is set. `document_dates`: the document date lies in the period (a
    document without one does not match). `facts`: the document has a fact that matches each
    (`FactCriterion`; none a person rejected)."""

    contacts: frozenset[ContactId] | None = None
    document_types: frozenset[DocumentTypeId] | None = None
    tags: TagSets = ()
    contact_groups: TagSets = ()
    document_type_groups: TagSets = ()
    topics: frozenset[TagId] | None = None
    spaces: frozenset[SpaceId] | None = None
    lanes: frozenset[Lane | None] | None = None
    confirmed: bool | None = None
    labelled: bool | None = None
    field: FieldId | None = None
    document_dates: Period | None = None
    facts: tuple[FactCriterion, ...] = ()

    def __post_init__(self) -> None:
        for sets in (self.tags, self.contact_groups, self.document_type_groups):
            if any(not tags for tags in sets):
                raise ValueError("a set of tags in a filter is never empty")
        for name, chosen in (
            ("topics", self.topics),
            ("contacts", self.contacts),
            ("document types", self.document_types),
            ("spaces", self.spaces),
        ):
            if chosen is not None and not chosen:
                raise ValueError(f"a set of {name} in a filter is never empty")

    def matches(self, view: "FilterView") -> bool:
        """Whether a document (as `view` shows it) matches; for the core and the in-memory
        adapters, where SQL and the search index have their query languages."""
        return (
            (self.contacts is None or view.contact in self.contacts)
            and (self.document_types is None or view.document_type in self.document_types)
            and (self.topics is None or bool(self.topics & view.topics))
            and all(tags & view.tags for tags in self.tags)
            and all(groups & view.contact_groups for groups in self.contact_groups)
            and all(groups & view.document_type_groups for groups in self.document_type_groups)
            and (self.spaces is None or view.space in self.spaces)
            and (self.lanes is None or view.lane in self.lanes)
            and (self.confirmed is None or view.confirmed is self.confirmed)
            and (self.labelled is None or view.labelled is self.labelled)
            and (self.field is None or self.field in view.fields)
            and all(criterion.token in view.facts for criterion in self.facts)
            and (
                self.document_dates is None
                or (
                    view.document_date is not None
                    and self.document_dates.start <= view.document_date <= self.document_dates.end
                )
            )
        )


@dataclass(frozen=True, kw_only=True)
class FacetRow:
    """What counts of the documents of a filter look at of one of them (`facet_rows`)."""

    contact: ContactId | None
    document_type: DocumentTypeId | None
    topic: TagId | None
    tags: frozenset[TagId]
    document_date: date | None


@dataclass(frozen=True, kw_only=True)
class FilterView:
    """What a `DocumentFilter` looks at of a document: from a `Document` and the groups of its
    contact and type (`of`), or from what the search index holds of it."""

    contact: ContactId | None
    document_type: DocumentTypeId | None
    topics: frozenset[TagId]  # the topic (the index: with those above it)
    tags: frozenset[TagId]
    contact_groups: frozenset[TagId]
    document_type_groups: frozenset[TagId]
    space: SpaceId
    lane: Lane | None
    confirmed: bool
    fields: frozenset[FieldId]
    document_date: date | None = None
    labelled: bool = False  # not in the search index
    facts: frozenset[str] = frozenset()  # `document_facts.fact_tokens`

    @classmethod
    def of(
        cls,
        document: Document,
        *,
        contact_groups: frozenset[TagId] = frozenset(),
        document_type_groups: frozenset[TagId] = frozenset(),
        facts: frozenset[str] = frozenset(),
    ) -> "FilterView":
        return cls(
            contact=document.contact_id,
            document_type=document.document_type_id,
            topics=frozenset() if document.topic_id is None else frozenset({document.topic_id}),
            tags=frozenset(document.tag_ids),
            contact_groups=contact_groups,
            document_type_groups=document_type_groups,
            space=document.space_id,
            lane=document.lane,
            confirmed=document.confirmed_at is not None,
            fields=frozenset(document.fields),
            document_date=document.document_date,
            labelled=document.confirmed_at is not None or document.space_confirmed_at is not None,
            facts=facts,
        )


class SortKey(StrEnum):
    ARRIVAL = "arrival"  # the order documents reached Lekto, which is their ids'
    CREATED = "created_at"  # by when they came in (`Document.created_at`, which may be set)
    DOCUMENT_DATE = "document_date"
    TITLE = "title"  # by `sort_key` of the title
    FIELD = "field"  # by the value of a field (`DocumentOrder.field`, `fields.sort_value`)


@dataclass(frozen=True)
class DocumentOrder:
    """How a list of documents is sorted: by `key`, descending unless `ascending`, ties by id
    the same way. Documents without a document date come last either way, as do those without
    a value when sorted by the field `field` (only then given; one of `SORTABLE_TYPES`)."""

    key: SortKey = SortKey.ARRIVAL
    ascending: bool = False
    field: FieldId | None = None

    def __post_init__(self) -> None:
        if (self.key is SortKey.FIELD) != (self.field is not None):
            raise ValidationError("sort_field_id: needed to sort by a field, and only then")


NEWEST_FIRST = DocumentOrder()


class CountBy(StrEnum):
    """What documents are counted by: their contact, type, topic, each tag, each field with a
    value."""

    CONTACT = "contact"
    DOCUMENT_TYPE = "document_type"
    TOPIC = "topic"
    TAG = "tag"
    FIELD = "field"


PAGE_SIZE = 50
"""Items of a page of a list when the caller names no size."""
PAGE_LIMIT = 200
"""Items a page may hold at most; the services clamp to it, the REST parameters declare it."""


@dataclass(frozen=True)
class DocumentPosition:
    """Where a page of a sorted list ended: its last document, and that document's value of
    the sort key (none for `ARRIVAL`, which sorts by id)."""

    id: DocumentId
    value: datetime | date | str | Decimal | None = None

    @classmethod
    def after(cls, id: DocumentId | None) -> "DocumentPosition | None":
        """The position after the document `id` in a list sorted by `ARRIVAL`; None: from the
        start."""
        return None if id is None else cls(id)

    @classmethod
    def of(cls, document: Document, order: DocumentOrder) -> "DocumentPosition":
        match order.key:
            case SortKey.ARRIVAL:
                return cls(document.id)
            case SortKey.CREATED:
                return cls(document.id, document.created_at)
            case SortKey.DOCUMENT_DATE:
                return cls(document.id, document.document_date)
            case SortKey.TITLE:
                return cls(document.id, sort_key(document.title))
            case SortKey.FIELD:
                value = None if order.field is None else document.fields.get(order.field)
                return cls(document.id, sort_value(value))


class DocumentRepository(Repository[DocumentId, Document], Protocol):
    async def find_by_sha256(self, sha256: Sha256) -> Document | None:
        """The document with that original: every file exists once per installation."""
        ...

    async def list_visible_to(self, user: UserId) -> list[Document]:
        """Documents within the user's reach (`lekto.core.domain.permissions.within_reach`):
        every document in the spaces they edit, the green ones in the spaces they read.
        Whether the user is active the services check."""
        ...

    async def field_in_use(
        self,
        field: FieldId,
        *,
        values: Collection[str] | None = None,
        outside_types: Collection[DocumentTypeId] | None = None,
    ) -> bool:
        """Whether any document has a value for `field`; with `values`, a text value that
        is one of them; with `outside_types`, on a document whose type is none of them (a
        document without type counts as outside)."""
        ...

    async def query_visible(
        self,
        user: UserId,
        filter: DocumentFilter,
        *,
        order: DocumentOrder = NEWEST_FIRST,
        after: DocumentPosition | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[Document]:
        """Documents the user may read (as `list_visible_to`) that match `filter`, in `order`,
        only those after `after` in it, skipping the first `offset` of them, at most `limit`."""
        ...

    async def query(
        self,
        filter: DocumentFilter,
        *,
        order: DocumentOrder = NEWEST_FIRST,
        after: DocumentPosition | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[Document]:
        """As `query_visible`, over every document (for admins)."""
        ...

    async def facet_rows(self, filter: DocumentFilter, user: UserId | None) -> list[FacetRow]:
        """Of each document that matches `filter` and the user may read (as
        `list_visible_to`; None: every document), what its counts look at: contact, type,
        topic, tags, document date. In no order."""
        ...

    async def count(self, filter: DocumentFilter, user: UserId | None) -> int:
        """How many documents match `filter` that the user may read (as `list_visible_to`;
        None: every document): what `facet_rows` would return, counted alone."""
        ...

    async def count_by(self, by: CountBy, user: UserId | None) -> dict[UUID, int]:
        """How many documents the user may read (as `list_visible_to`; None: every document)
        have each contact, type, topic or tag, or a value for each field. Only ids with
        documents."""
        ...

    async def count_tagged(
        self, sets: Mapping[UUID, Collection[TagId]], user: UserId | None
    ) -> dict[UUID, int]:
        """For each key, how many documents the user may read (as `count_by`) carry a tag of
        its set, each document once (the core gives a tag with its descendants). Only keys with
        documents."""
        ...

    async def remove(self, id: DocumentId) -> None:
        """Delete the document, its processing log and what the inbox keeps of it (`inbox`);
        NotFoundError if it does not exist."""
        ...

    async def count_all(self) -> int:
        """How many documents there are."""
        ...

    async def count_confirmed(self, *, after: datetime | None = None) -> int:
        """Documents a person set or confirmed the metadata or decided the space of, after
        `after` if given (the decisions since the classifier was trained)."""
        ...

    async def confirmed_labels(self, reader: UserId) -> KnownLabels:
        """The contacts, document types, topics and tags the confirmed documents `reader` may
        read carry: what a document similar to one of theirs can name. `spaces`: the decided
        spaces of those confirmed documents (the ones that vote, `NeighboursSignal`), as the
        reader's candidates: one in its uploader's personal space counts as the reader's
        personal space."""
        ...

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
        """Whether any document matches all given criteria, regardless of who may read it
        (for checks before deleting what documents refer to). At least one is required."""
        ...


class DocumentRelationRepository(Protocol):
    """The relations between documents (`domain.relations`)."""

    async def of_document(self, document: DocumentId) -> list[Relation]:
        """The relations of `document` in both directions, rejected ones included; the newest
        first by when they were made."""
        ...

    async def of_documents(self, documents: Collection[DocumentId]) -> list[Relation]:
        """The relations of any of `documents`, in both directions, rejected ones included."""
        ...

    async def find(self, newer: DocumentId, older: DocumentId) -> Relation | None: ...

    async def put(self, relation: Relation) -> None:
        """Keep `relation`, in place of one between the same documents."""
        ...

    async def remove(self, newer: DocumentId, older: DocumentId) -> None:
        """Forget the relation; nothing if there is none."""
        ...


class DocumentFactRepository(Protocol):
    """The facts of each document (`domain.document_facts`): what its sources found, as the
    facts signal last ran, and what a person decided. They tell on how many contacts' documents
    a value stands (the IBAN of the owner's own account stands on many)."""

    async def of_document(self, document: DocumentId) -> list[DocumentFact]:
        """The facts of `document` as the text reads (`reading_order`), those a person rejected
        included."""
        ...

    async def of_documents(
        self, documents: Collection[DocumentId]
    ) -> dict[DocumentId, list[DocumentFact]]:
        """`of_document` for each of `documents` at once; one without facts is left out."""
        ...

    async def replace_found(self, document: DocumentId, found: Collection[DocumentFact]) -> None:
        """Make `found` (each `FactState.FOUND`, a kind and value once) the facts the sources
        found for `document`: those found before go, what a person decided stays and is not
        replaced by a fact found of its kind and value (`document_facts.merged`).
        ValidationError for a fact of another state or a key twice."""
        ...

    async def decide(self, document: DocumentId, fact: DocumentFact) -> None:
        """Keep a person's decision about a fact of `document` (a state by a person: added,
        corrected, rejected): it takes the place of the fact of its kind and value.
        ValidationError for a fact as found."""
        ...

    async def withdraw(self, document: DocumentId, key: tuple[IdentifierKind, str]) -> None:
        """A person's decision about the fact of `key` no longer stands (`withdrawn`): a fact a
        source found is as found again, one only a person gave goes. Nothing where no person
        decided the fact of `key`."""
        ...

    async def contacts_of(
        self, identifiers: Collection[tuple[IdentifierKind, str]]
    ) -> dict[tuple[IdentifierKind, str], frozenset[ContactId]]:
        """For each of `identifiers`, the contacts of the confirmed documents that show it (a
        fact not rejected); one that no confirmed document with a contact shows is left out."""
        ...

    async def sightings(self, kinds: Collection[IdentifierKind]) -> list[Sighting]:
        """Every fact of one of `kinds` that a confirmed document with a contact shows (not
        rejected), in no particular order."""
        ...


@dataclass(frozen=True)
class InboxEntry:
    """A document in a viewer's inbox, with what `domain.inbox.inbox_state` decides by: when
    the viewer saw it last (None: never), and who confirmed it out of yellow or red last.
    `silent`: the viewer's mark is a move's (`InboxRepository.mark_seen`)."""

    document: Document
    seen_at: datetime | None
    confirmation: Confirmation | None
    silent: bool = False


@dataclass(frozen=True)
class InboxPosition:
    """Where a page of an inbox ended: its last document, and under done when that document
    left the inbox (`domain.inbox.left_at`), which done is sorted by; the other tabs go by
    arrival, the id."""

    id: DocumentId
    left_at: datetime | None = None


class InboxRepository(Protocol):
    """What the inbox keeps beside the documents (`domain.inbox`): when each user saw a
    document last, and who confirmed a document out of yellow or red last; and the inbox's
    queries over both and the documents.

    `editor`: whose inbox, a user's (the documents in the spaces they edit) or, None, every
    user's (an admin with `all_users`); `viewer`: whose seen counts. `since`: from when done
    counts (`DONE_PERIOD` back). Marks go with their document and their user; the seen marks
    of a user who is deleted are removed first (`remove_for_user`)."""

    async def query(
        self,
        viewer: UserId,
        *,
        editor: UserId | None,
        tab: InboxTab | None,
        since: datetime,
        after: InboxPosition | None = None,
        limit: int,
    ) -> list[InboxEntry]:
        """The documents of `editor` that stand under `tab` in the inbox (`inbox_state`; None:
        under any open tab), newest first: by id, and under done by when they left
        (`domain.inbox.left_at`), ties by id; those after `after` in that order, at most
        `limit`."""
        ...

    async def entry(self, viewer: UserId, document: DocumentId) -> InboxEntry | None:
        """The document with `viewer`'s seen mark and its confirmation, wherever it lies and
        stands; None if it does not exist."""
        ...

    async def count(
        self, viewer: UserId, *, editor: UserId | None, since: datetime
    ) -> dict[InboxTab, int]:
        """How many documents of `editor` stand under each tab of the inbox (as `query`)."""
        ...

    async def seen(
        self, viewer: UserId, documents: Collection[DocumentId]
    ) -> dict[DocumentId, datetime]:
        """When `viewer` saw each of `documents` last; those never seen are left out."""
        ...

    async def mark_seen(
        self, viewer: UserId, document: DocumentId, at: datetime, *, silent: bool = False
    ) -> None:
        """`viewer` saw `document` at `at`, which replaces when they saw it before. A `silent`
        mark, which a move sets for someone who knew the document, keeps it from being new for
        them but does not make it done (`domain.inbox.departure`); the next mark replaces it."""
        ...

    async def mark_all_seen(self, viewer: UserId, *, editor: UserId | None, at: datetime) -> int:
        """Mark every document of `editor` that is new and unseen in the inbox as seen by
        `viewer` at `at` (`domain.inbox.is_unseen`); returns how many."""
        ...

    async def unmark_seen(self, viewer: UserId, document: DocumentId) -> None:
        """Forget that `viewer` saw `document` (it is new for them again while it is new); no
        error if they never did."""
        ...

    async def record_confirmation(self, document: DocumentId, confirmation: Confirmation) -> None:
        """A person confirmed `document` out of yellow or red; it replaces the confirmation
        before."""
        ...

    async def purge(self, *, before: datetime) -> int:
        """Remove what only done needs, from before `before`: the confirmations, and the seen
        marks that tell nothing any more (their document became new again since, or it is new
        for no one); returns how many."""
        ...

    async def remove_for_user(self, user: UserId) -> int:
        """Remove the user's seen marks; returns how many. Confirmations stay with their
        document (they name who confirmed, also once the account is gone)."""
        ...


class ProcessingLog(Protocol):
    """Append-only log of node executions."""

    async def append(self, run: NodeRun) -> None: ...

    async def list_for(self, document: DocumentId) -> list[NodeRun]:
        """All entries of the document in the order they were appended."""
        ...


@dataclass(frozen=True)
class FactsScope:
    """The documents statistics count: those that came in through `channels` (None: through
    any), and since `since` (None: ever): whose first run stopped then or later, or, for the
    verdicts, whose field a person decided then or later."""

    channels: frozenset[Channel] | None = None
    since: datetime | None = None


@dataclass(frozen=True)
class LaneCount:
    """How many documents whose first run stopped in `first_lane` lie in `lane` now (None:
    being processed), and whether a person decided a field of them (`decided`, any verdict)."""

    first_lane: Lane
    lane: Lane | None
    decided: bool
    count: int


@dataclass(frozen=True)
class RunTimes:
    """The times of the first runs in microseconds, one value per document, in no particular
    order: how long each took (`durations`) and worked (`work`); per node, how long it worked in
    each first run it ran in (`steps`). Plain numbers: a page reads them by the hundred
    thousand."""

    durations: list[int]
    work: list[int]
    steps: dict[Node, list[int]]


@dataclass(frozen=True)
class SignalCount:
    """How often a signal named the value a person decided for a field (`hits`), and how often
    another (`misses`)."""

    hits: int
    misses: int


class ProcessingFacts(Protocol):
    """What Lekto keeps of each document's processing for the page "System"
    (`domain.first_runs`): its first run and the verdicts per field, written once, as they
    happen; and the statistics over them, counted live. Rows go with their document. The lanes
    are the documents' (`Document.first_lane`, `Document.lane`); a document whose first lane is
    unknown is not counted."""

    async def add_first_run(self, run: FirstRun) -> None:
        """Keep the document's first run; one kept already stays."""
        ...

    async def add_verdicts(self, verdicts: Collection[FieldVerdict]) -> None:
        """Keep the verdicts; a field of a document that has a verdict keeps it."""
        ...

    async def first_run(self, document: DocumentId) -> FirstRun | None: ...

    async def verdicts(self, document: DocumentId) -> list[FieldVerdict]:
        """The verdicts on the document's fields, by field."""
        ...

    async def lane_counts(self, scope: FactsScope) -> list[LaneCount]:
        """The documents of `scope` by first lane, lane now and whether decided; combinations
        without documents are left out."""
        ...

    async def lanes_by_period(
        self, scope: FactsScope, starts: Sequence[datetime]
    ) -> list[dict[Lane, int]]:
        """The documents of `scope` by first lane, per period: from each of `starts` (ascending)
        to the next, the last one open. Documents whose first run stopped before the first are
        left out."""
        ...

    async def run_times(self, scope: FactsScope) -> RunTimes:
        """The times of the first runs of `scope`."""
        ...

    async def verdict_counts(self, scope: FactsScope) -> dict[tuple[str, Verdict], int]:
        """How many verdicts of each kind each field got in `scope`, by when they were decided;
        combinations without any are left out."""
        ...

    async def signal_counts(self, scope: FactsScope) -> dict[tuple[str, Node], SignalCount]:
        """Per field and signal, how often the signal named the person's value or another, in
        the verdicts of `scope`; combinations in which the signal named nothing are left out."""
        ...


class RuleRepository(Protocol):
    """Rules with their versions. A rule is stored with its current version; `update` stores a
    new current version as well and keeps the earlier ones. Deleted rules (`deleted_at`) stay
    stored for their versions; `get` and `find` return them, the lists leave them out."""

    async def get(self, id: RuleId) -> Rule: ...

    async def find(self, id: RuleId) -> Rule | None: ...

    async def add(self, rule: Rule) -> None: ...

    async def update(self, rule: Rule) -> None:
        """Version check as for every repository. If `rule.current` is a version that is not
        stored yet, it is added."""
        ...

    async def list_for(
        self, *, spaces: Collection[SpaceId] | None, include_global: bool
    ) -> list[Rule]:
        """Rules that are not deleted: the rules of `spaces` (None: of every space), and
        global rules if `include_global`."""
        ...

    async def versions(self, id: RuleId) -> list[RuleVersion]:
        """All versions of the rule, oldest first; NotFoundError if the rule does not exist."""
        ...

    async def get_version(self, id: RuleId, number: int) -> RuleVersion:
        """NotFoundError if the rule or the version does not exist."""
        ...

    async def remove_for_space(self, space: SpaceId) -> int:
        """Delete the rules of the space with their versions and applications, for good;
        returns how many rules."""
        ...

    async def remove_applications_by(self, user: UserId) -> int:
        """Delete every application of a rule the user asked for, for good; returns how
        many."""
        ...


class RuleApplicationRepository(Protocol):
    """Applications of a rule to existing documents (`RuleApplication`)."""

    async def get(self, id: RuleApplicationId) -> RuleApplication: ...

    async def find(self, id: RuleApplicationId) -> RuleApplication | None: ...

    async def add(self, application: RuleApplication) -> None: ...

    async def update(self, application: RuleApplication) -> None: ...


class BulkOperationRepository(Protocol):
    """Actions on many documents at once (`BulkOperation`)."""

    async def get(self, id: BulkOperationId) -> BulkOperation: ...

    async def find(self, id: BulkOperationId) -> BulkOperation | None: ...

    async def add(self, operation: BulkOperation) -> None: ...

    async def update(self, operation: BulkOperation) -> None: ...


class ClassifierModelRepository(Protocol):
    """The trained classifiers (their files are in the object store)."""

    async def add(self, model: ClassifierModel) -> None: ...

    async def latest(self) -> ClassifierModel | None:
        """The model with the highest number."""
        ...

    async def list_all(self) -> list[ClassifierModel]:
        """Newest first."""
        ...

    async def remove(self, id: ClassifierModelId) -> None: ...


class LensRepository(Protocol):
    """A user's lenses (`domain.lenses`)."""

    async def get(self, id: LensId) -> Lens: ...

    async def find(self, id: LensId) -> Lens | None: ...

    async def add(self, lens: Lens) -> None:
        """ConflictError if the owner has a lens of that name (regardless of case)."""
        ...

    async def update(self, lens: Lens) -> None:
        """As `add` for the name; ConcurrencyError if it was changed meanwhile."""
        ...

    async def remove(self, id: LensId) -> None:
        """NotFoundError if it does not exist."""
        ...

    async def remove_for_owner(self, owner: UserId) -> int:
        """Delete the user's lenses; returns how many."""
        ...

    async def list_for_owner(self, owner: UserId) -> list[Lens]:
        """The user's lenses by `position`, ties oldest first."""
        ...


class WebhookRepository(Protocol):
    """Webhooks with the log of their deliveries."""

    async def get(self, id: WebhookId) -> Webhook: ...

    async def find(self, id: WebhookId) -> Webhook | None: ...

    async def add(self, webhook: Webhook) -> None: ...

    async def update(self, webhook: Webhook) -> None: ...

    async def remove(self, id: WebhookId) -> None:
        """Delete the webhook with its deliveries; no-op if it does not exist."""
        ...

    async def remove_for_owner(self, owner: UserId) -> int:
        """Delete the user's webhooks with their deliveries; returns how many webhooks."""
        ...

    async def list_for_owner(self, owner: UserId) -> list[Webhook]:
        """The user's webhooks, oldest first."""
        ...

    async def list_all(self) -> list[Webhook]:
        """Everybody's webhooks, oldest first."""
        ...

    async def count_for_owner(self, owner: UserId) -> int: ...

    async def list_active_for(self, event_type: str) -> list[Webhook]:
        """The active webhooks that want the event type (it is listed, or they want all)."""
        ...

    async def list_model_calls(self) -> list[Webhook]:
        """The webhooks that serve as a model call (`Webhook.model_call`), active or not, oldest
        first."""
        ...

    async def add_delivery(self, delivery: WebhookDelivery) -> None:
        """Log an attempt. The webhook must exist (NotFoundError otherwise): one that was
        deleted meanwhile has nothing to log for."""
        ...

    async def deliveries(
        self,
        webhook: WebhookId,
        *,
        outcomes: Collection[DeliveryOutcome] | None = None,
        event_type: str | None = None,
        offset: int = 0,
        limit: int = PAGE_SIZE,
    ) -> list[WebhookDelivery]:
        """The log of a webhook, newest first (by id), `offset` entries in; only `outcomes`
        and `event_type` where given."""
        ...

    async def delivery_counts(
        self, webhook: WebhookId, *, event_type: str | None = None
    ) -> dict[DeliveryOutcome, int]:
        """How many entries the log of a webhook holds by outcome (of `event_type` where
        given); an outcome without any is missing."""
        ...

    async def delivery_event_types(self, webhook: WebhookId) -> list[str]:
        """The event types the log of a webhook holds, in order of their names."""
        ...

    async def purge_deliveries(self, *, before: datetime) -> int:
        """Remove deliveries that started before `before`; returns how many."""
        ...


class TaskRepository(Protocol):
    """Tasks (`domain.tasks`). They outlive their webhook (an open one runs to its deadline)
    and their document (a late answer is refused as stale)."""

    async def get(self, id: TaskId) -> Task:
        """NotFoundError if it does not exist."""
        ...

    async def find(self, id: TaskId) -> Task | None: ...

    async def add(self, task: Task) -> None: ...

    async def update(self, task: Task) -> None: ...

    async def list_for_run(self, document: DocumentId, node: Node, run: int) -> list[Task]:
        """The tasks of `node` of the document in processing run `run`, oldest first."""
        ...

    async def list_unsettled_for(self, document: DocumentId) -> list[Task]:
        """The document's queued and open tasks, of any run, oldest first."""
        ...

    async def count_open(self, webhook: WebhookId) -> int:
        """How many tasks through the webhook are open (sent, not ended)."""
        ...

    async def queued(self, webhook: WebhookId, *, limit: int) -> list[Task]:
        """The tasks through the webhook that wait to be sent, oldest first, at most
        `limit`."""
        ...

    async def purge(self, *, before: datetime) -> int:
        """Remove the tasks that ended before `before`; returns how many."""
        ...
