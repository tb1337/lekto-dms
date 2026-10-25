"""Committed state shared by the in-memory unit of work, job queue and event bus."""

import asyncio
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from lekto.core.domain.classifier import ClassifierModel
from lekto.core.domain.documents import Document
from lekto.core.domain.entity import Entity
from lekto.core.domain.events import DomainEvent
from lekto.core.domain.fields import FieldDefinition
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.identity import ApiToken, ExternalIdentity, Session
from lekto.core.domain.ids import DocumentId, EventId, JobId, UserId
from lekto.core.domain.inbox import Confirmation
from lekto.core.domain.jobs import Job
from lekto.core.domain.lenses import Lens
from lekto.core.domain.master_data import Contact, DocumentType, MasterData, Tag
from lekto.core.domain.pipeline import NodeRun
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import User
from lekto.core.domain.validation import name_key


@dataclass(frozen=True)
class Table[E: Entity[UUID]]:
    """A kind of entity: its name in errors and the keys that must be unique across the table."""

    name: str
    unique_keys: Callable[[E], Iterable[Hashable]]


@dataclass
class IdentifiersRow:
    """The identifiers one document shows (a row keyed by the document's id)."""

    id: DocumentId
    identifiers: frozenset[tuple[IdentifierKind, str]]
    version: int


def _user_keys(user: User) -> Iterable[Hashable]:
    keys: list[Hashable] = [("username", name_key(user.username))]
    if user.display_name is not None:
        keys.append(("display name", name_key(user.display_name)))
    return keys


def _space_keys(space: Space) -> Iterable[Hashable]:
    if space.personal_of is not None:
        return [("personal", space.personal_of)]
    return [("name", name_key(space.name))]


def _name_keys(item: MasterData) -> Iterable[Hashable]:
    return [("name", name_key(item.name))]


def _contact_keys(contact: Contact) -> Iterable[Hashable]:
    return [
        *_name_keys(contact),
        *(("alias", name_key(alias)) for alias in contact.aliases),
        *(("identifier", *item.key) for item in contact.identifiers),
    ]


def _tag_keys(tag: Tag) -> Iterable[Hashable]:
    return [("name", tag.scope, name_key(tag.name))]


def _document_keys(document: Document) -> Iterable[Hashable]:
    return [("sha256", document.sha256)]


def _lens_keys(lens: Lens) -> Iterable[Hashable]:
    return [("name", lens.owner_id, name_key(lens.name))]


def _no_keys(item: Entity[UUID]) -> Iterable[Hashable]:
    return []


def _session_keys(session: Session) -> Iterable[Hashable]:
    return [("token", session.token_hash)]


def _token_keys(token: ApiToken) -> Iterable[Hashable]:
    return [("token", token.token_hash)]


def _external_identity_keys(identity: ExternalIdentity) -> Iterable[Hashable]:
    return [("subject", identity.issuer, identity.subject)]


def _classifier_model_keys(model: ClassifierModel) -> Iterable[Hashable]:
    return [("number", model.number)]


USERS = Table("user", _user_keys)
PROFILES = Table("profile", _no_keys)
SPACES = Table("space", _space_keys)
CONTACTS = Table("contact", _contact_keys)
DOCUMENT_TYPES = Table[DocumentType]("document type", _name_keys)
TAGS = Table("tag", _tag_keys)
FIELDS = Table[FieldDefinition]("field", _name_keys)
DOCUMENTS = Table("document", _document_keys)
CREDENTIALS = Table("credential", _no_keys)
SESSIONS = Table("session", _session_keys)
API_TOKENS = Table("API token", _token_keys)
EXTERNAL_IDENTITIES = Table("external identity", _external_identity_keys)
LOGIN_FAILURES = Table("login failures", _no_keys)
RULES = Table("rule", _no_keys)
RULE_VERSIONS = Table("rule version", _no_keys)
RULE_APPLICATIONS = Table("rule application", _no_keys)
DOCUMENT_IDENTIFIERS = Table[IdentifiersRow]("document identifiers", _no_keys)
CLASSIFIER_MODELS = Table("classifier model", _classifier_model_keys)
WEBHOOKS = Table("webhook", _no_keys)
WEBHOOK_DELIVERIES = Table("webhook delivery", _no_keys)
TASKS = Table("task", _no_keys)
LENSES = Table("lens", _lens_keys)


@dataclass
class Retry:
    """A failed delivery, due again at `due`."""

    position: int
    attempts: int
    due: datetime


@dataclass
class SubscriptionState:
    """Delivery state of one subscriber, kept with the outbox so it survives the bus."""

    cursor: int  # outbox position of the next new event
    retries: list[Retry] = field(default_factory=list)  # failed events, in order of failure


@dataclass(frozen=True)
class SeenMark:
    """A user's seen mark on a document: when, and whether a move set it silently (it keeps
    the document from being new but is no seeing, `InboxRepository.mark_seen`)."""

    at: datetime
    silent: bool = False


@dataclass
class MemoryDatabase:
    """What has been committed. Rows are private copies; insertion order is creation order."""

    tables: dict[str, dict[UUID, Entity[UUID]]] = field(default_factory=dict)
    processing_log: list[NodeRun] = field(default_factory=list)
    outbox: list[DomainEvent] = field(default_factory=list)
    recorded_at: dict[EventId, datetime] = field(default_factory=dict)  # when committed
    purged: set[int] = field(default_factory=set)  # outbox positions removed by `purge`
    jobs: dict[JobId, Job] = field(default_factory=dict)
    subscriptions: dict[str, SubscriptionState] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)  # see MemoryUnitOfWork.lock
    # What the inbox keeps: when each user saw a document last, who confirmed it last.
    seen: dict[tuple[UserId, DocumentId], "SeenMark"] = field(default_factory=dict)
    confirmations: dict[DocumentId, Confirmation] = field(default_factory=dict)
