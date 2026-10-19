"""Metadata persistence: one repository per aggregate, all reached through the unit of work.

First adapter: SQLAlchemy on SQLite or Postgres (M2).

Common rules for every adapter:
- Reads return copies; changing an entity has no effect until `update` and commit.
- `add` keeps the entity's version; `update` succeeds only if the stored version equals the
  entity's version, then increments both. Otherwise it raises ConcurrencyError (at the latest on
  commit).
- Uniqueness (raises ConflictError at the latest on commit): usernames; space names per owner;
  one default space per owner; names of contacts, document types and field definitions, and
  of tags per scope; the original (SHA-256) per document owner. Names compare regardless of
  case. The services look a name up before they write, for a message that names it ("'X'
  already exists"); the adapter's rule is the net for two requests at once, which the look-up
  cannot see.
- `get` raises NotFoundError, `find` returns None.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from lekto.core.domain.classifier import ClassifierModel
from lekto.core.domain.documents import Document, Sha256
from lekto.core.domain.fields import FieldDefinition
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import (
    ClassifierModelId,
    ContactId,
    DeliveryId,
    DocumentId,
    DocumentTypeId,
    FieldId,
    RuleApplicationId,
    RuleId,
    SpaceId,
    TagId,
    UserId,
    WebhookId,
)
from lekto.core.domain.inbox import Confirmation, InboxTab
from lekto.core.domain.master_data import Contact, DocumentType, Tag, TagScope
from lekto.core.domain.periods import Period
from lekto.core.domain.pipeline import Lane, NodeRun
from lekto.core.domain.rules import Rule, RuleApplication, RuleVersion
from lekto.core.domain.sorting import sort_key
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import User
from lekto.core.domain.verdict import KnownLabels
from lekto.core.domain.webhooks import Webhook, WebhookDelivery


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
        """Delete the user; NotFoundError if missing. Documents, spaces, shares and identity
        data that refer to the user must be removed first."""
        ...


class SpaceRepository(Repository[SpaceId, Space], Protocol):
    async def get_default(self, owner: UserId) -> Space:
        """The owner's default space; NotFoundError if there is none."""
        ...

    async def list_accessible(self, user: UserId) -> list[Space]:
        """Spaces the user owns or that are shared with them."""
        ...

    async def remove(self, id: SpaceId) -> None:
        """Delete the space and its shares; NotFoundError if missing. It must hold no
        documents."""
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
    `field`: a value for it is set. `document_dates`: the document date lies in the period (a
    document without one does not match)."""

    contacts: frozenset[ContactId] | None = None
    document_types: frozenset[DocumentTypeId] | None = None
    tags: TagSets = ()
    contact_groups: TagSets = ()
    document_type_groups: TagSets = ()
    topics: frozenset[TagId] | None = None
    spaces: frozenset[SpaceId] | None = None
    lanes: frozenset[Lane | None] | None = None
    confirmed: bool | None = None
    field: FieldId | None = None
    document_dates: Period | None = None

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
            and (self.field is None or self.field in view.fields)
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

    @classmethod
    def of(
        cls,
        document: Document,
        *,
        contact_groups: frozenset[TagId] = frozenset(),
        document_type_groups: frozenset[TagId] = frozenset(),
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
        )


class SortKey(StrEnum):
    CREATED = "created_at"  # the order documents came in, which is their ids'
    DOCUMENT_DATE = "document_date"
    TITLE = "title"  # by `sort_key` of the title


@dataclass(frozen=True)
class DocumentOrder:
    """How a list of documents is sorted: by `key`, descending unless `ascending`, ties by id
    the same way. Documents without a document date come last either way."""

    key: SortKey = SortKey.CREATED
    ascending: bool = False


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
    the sort key (none for `CREATED`, which sorts by id)."""

    id: DocumentId
    value: date | str | None = None

    @classmethod
    def after(cls, id: DocumentId | None) -> "DocumentPosition | None":
        """The position after the document `id` in a list sorted by `CREATED`; None: from the
        start."""
        return None if id is None else cls(id)

    @classmethod
    def of(cls, document: Document, order: DocumentOrder) -> "DocumentPosition":
        match order.key:
            case SortKey.CREATED:
                return cls(document.id)
            case SortKey.DOCUMENT_DATE:
                return cls(document.id, document.document_date)
            case SortKey.TITLE:
                return cls(document.id, sort_key(document.title))


class DocumentRepository(Repository[DocumentId, Document], Protocol):
    async def find_by_sha256(self, owner: UserId, sha256: Sha256) -> Document | None: ...

    async def list_visible_to(self, user: UserId) -> list[Document]:
        """Documents within the user's reach (`lekto.core.domain.permissions.within_reach`): own
        documents, and green documents in spaces the user owns or that are shared with them.
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
    ) -> list[Document]:
        """Documents the user may read (as `list_visible_to`) that match `filter`, in `order`,
        only those after `after` in it, at most `limit`."""
        ...

    async def query(
        self,
        filter: DocumentFilter,
        *,
        order: DocumentOrder = NEWEST_FIRST,
        after: DocumentPosition | None = None,
        limit: int,
    ) -> list[Document]:
        """As `query_visible`, over every document (for admins)."""
        ...

    async def facet_rows(self, filter: DocumentFilter, user: UserId | None) -> list[FacetRow]:
        """Of each document that matches `filter` and the user may read (as
        `list_visible_to`; None: every document), what its counts look at: contact, type,
        topic, tags, document date. In no order."""
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

    async def count_confirmed(self, *, after: datetime | None = None) -> int:
        """Documents a person set or confirmed the metadata of, after `after` if given (the
        confirmations since the classifier was trained)."""
        ...

    async def confirmed_labels(self, reader: UserId) -> KnownLabels:
        """The contacts, document types, topics and tags the confirmed documents `reader` may
        read carry: what a document similar to one of theirs can name."""
        ...

    async def exists(
        self,
        *,
        owner: UserId | None = None,
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


class DocumentIdentifierRepository(Protocol):
    """The identifiers each document shows, in its text or its codes, as the facts signal last
    found them: for telling on how many contacts' documents a value stands (the IBAN of the
    owner's own account stands on many)."""

    async def replace(
        self, document: DocumentId, identifiers: Collection[tuple[IdentifierKind, str]]
    ) -> None:
        """Make `identifiers` (kind and normalised value) those of `document`."""
        ...

    async def contacts_of(
        self, identifiers: Collection[tuple[IdentifierKind, str]]
    ) -> dict[tuple[IdentifierKind, str], frozenset[ContactId]]:
        """For each of `identifiers`, the contacts of the confirmed documents that show it;
        one that no confirmed document with a contact shows is left out."""
        ...


@dataclass(frozen=True)
class InboxEntry:
    """A document in a viewer's inbox, with what `domain.inbox.inbox_state` decides by: when
    the viewer saw it last (None: never), and who confirmed it out of yellow or red last."""

    document: Document
    seen_at: datetime | None
    confirmation: Confirmation | None


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

    `owner`: whose inbox, a user's or, None, every user's (an admin with `all_users`); `viewer`:
    whose seen counts. `since`: from when done counts (`DONE_PERIOD` back). Marks go with their
    document and their user; the seen marks of a user who is deleted are removed first
    (`remove_for_user`)."""

    async def query(
        self,
        viewer: UserId,
        *,
        owner: UserId | None,
        tab: InboxTab | None,
        since: datetime,
        after: InboxPosition | None = None,
        limit: int,
    ) -> list[InboxEntry]:
        """The documents of `owner` that stand under `tab` in the inbox (`inbox_state`; None:
        under any open tab), newest first: by id, and under done by when they left
        (`domain.inbox.left_at`), ties by id; those after `after` in that order, at most
        `limit`."""
        ...

    async def entry(self, viewer: UserId, document: DocumentId) -> InboxEntry | None:
        """The document with `viewer`'s seen mark and its confirmation, whoever owns it and
        wherever it stands; None if it does not exist."""
        ...

    async def count(
        self, viewer: UserId, *, owner: UserId | None, since: datetime
    ) -> dict[InboxTab, int]:
        """How many documents of `owner` stand under each tab of the inbox (as `query`)."""
        ...

    async def seen(
        self, viewer: UserId, documents: Collection[DocumentId]
    ) -> dict[DocumentId, datetime]:
        """When `viewer` saw each of `documents` last; those never seen are left out."""
        ...

    async def mark_seen(self, viewer: UserId, document: DocumentId, at: datetime) -> None:
        """`viewer` saw `document` at `at`, which replaces when they saw it before."""
        ...

    async def mark_all_seen(self, viewer: UserId, *, owner: UserId | None, at: datetime) -> int:
        """Mark every document of `owner` that is new and unseen in the inbox as seen by
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
        self, *, owners: Collection[UserId] | None, include_global: bool
    ) -> list[Rule]:
        """Rules that are not deleted: user rules of `owners` (None: of every user), and global
        rules if `include_global`."""
        ...

    async def versions(self, id: RuleId) -> list[RuleVersion]:
        """All versions of the rule, oldest first; NotFoundError if the rule does not exist."""
        ...

    async def get_version(self, id: RuleId, number: int) -> RuleVersion:
        """NotFoundError if the rule or the version does not exist."""
        ...

    async def remove_for_owner(self, owner: UserId) -> int:
        """Delete the user's rules with their versions, and all applications of these rules or
        by this user, for good; returns how many rules."""
        ...


class RuleApplicationRepository(Protocol):
    """Applications of a rule to existing documents (`RuleApplication`)."""

    async def get(self, id: RuleApplicationId) -> RuleApplication: ...

    async def find(self, id: RuleApplicationId) -> RuleApplication | None: ...

    async def add(self, application: RuleApplication) -> None: ...

    async def update(self, application: RuleApplication) -> None: ...


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

    async def add_delivery(self, delivery: WebhookDelivery) -> None:
        """Log an attempt. The webhook must exist (NotFoundError otherwise): one that was
        deleted meanwhile has nothing to log for."""
        ...

    async def deliveries(
        self, webhook: WebhookId, *, before: DeliveryId | None = None, limit: int = PAGE_SIZE
    ) -> list[WebhookDelivery]:
        """The log of a webhook, newest first (by id), the page after `before`."""
        ...

    async def purge_deliveries(self, *, before: datetime) -> int:
        """Remove deliveries that started before `before`; returns how many."""
        ...
