import asyncio
import copy
import hashlib
import json
import logging
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from lekto.core.domain import media_types
from lekto.core.domain.classification import CONFIRMING, SPACE
from lekto.core.domain.codes import Code, GiroCode, code_identifiers, codes_from_json, giro_code
from lekto.core.domain.documents import Channel, Document, DocumentChanges, confirms
from lekto.core.domain.errors import (
    ConflictError,
    NotFoundError,
    SpaceWriteDeniedError,
    UnprocessableDocumentError,
    ValidationError,
)
from lekto.core.domain.exchanges import RunExchange, exchanges_from_json
from lekto.core.domain.facts import Facts, facts_in, on_pages
from lekto.core.domain.fields import SORTABLE_TYPES, FieldType, FieldValue
from lekto.core.domain.first_runs import Decision
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import (
    ContactId,
    DocumentId,
    DocumentTypeId,
    FieldId,
    SpaceId,
    TagId,
    UserId,
)
from lekto.core.domain.locations import Box, Location
from lekto.core.domain.master_data import Assignment
from lekto.core.domain.permissions import (
    can_hand_over,
    can_move_document,
    can_read_document,
    document_access,
    in_reach,
    space_role,
)
from lekto.core.domain.pipeline import Node, NodeRun
from lekto.core.domain.reasons import Action, ReasonCode, because
from lekto.core.domain.rule_planner import changed_fields
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.text_places import TextPlaces
from lekto.core.domain.users import User
from lekto.core.ports.clock import Clock
from lekto.core.ports.metadata import FileMetadata, MetadataReader
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.pages import PAGE_MEDIA_TYPE
from lekto.core.ports.repository import (
    NEWEST_FIRST,
    PAGE_LIMIT,
    PAGE_SIZE,
    CountBy,
    DocumentFilter,
    DocumentOrder,
    DocumentPosition,
    FacetRow,
    SortKey,
)
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import (
    access_to,
    admin_only,
    checked_changes,
    controllable_document,
    field_definitions,
    load_actor,
    load_lister,
    readable_document,
    readable_log,
    writable_document,
)
from lekto.core.services._first_runs import keep_verdicts
from lekto.core.services._moves import move_by_person
from lekto.core.services._tags import expand, expanded, tag_counts, tag_tree
from lekto.core.services.inbox import Review, in_inbox, node_reviews, open_nodes
from lekto.core.services.maintenance import REMOVE_FILES_JOB, RemoveFiles
from lekto.core.services.objects import (
    EXCHANGE_NODES,
    archive_key,
    codes_key,
    exchanges_key,
    legacy_exchanges_key,
    load_layout,
    load_text,
    original_key,
    page_key,
    preview_key,
    structure_key,
)
from lekto.core.services.profiles import matching_persons
from lekto.core.services.rules.changes import ChangeRules
from lekto.core.services.rules.running import Prepared, RuleRun
from lekto.core.services.tasks.settling import cancel_tasks

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetadataChange:
    """A changed document; the caller's access afterwards (None if the rules filed it where
    the caller cannot see it); its space; the rules' run, for its editors and admins; the state
    before the change."""

    document: Document
    access: SpaceRole | None
    space: Space
    rules: RuleRun | None = None
    before: Document | None = None


@dataclass(frozen=True)
class DocumentView:
    """A document with the caller's access to it."""

    document: Document
    access: SpaceRole


@dataclass(frozen=True)
class DocumentFacets:
    """How many documents of a filter have each value (`DocumentService.facets`). `contacts`
    and `document_types` count those without one under None; `months` by `2026-09`, those
    without a document date in `undated`."""

    total: int
    contacts: dict[ContactId | None, int]
    document_types: dict[DocumentTypeId | None, int]
    contact_groups: dict[TagId, int]
    document_type_groups: dict[TagId, int]
    topics: dict[TagId, int]
    tags: dict[TagId, int]
    months: dict[str, int]
    undated: int


@dataclass(frozen=True)
class ListedDocument:
    """A document of a list with the caller's access to it, and whether it stands open in the
    caller's inbox (`inbox.in_inbox`)."""

    document: Document
    access: SpaceRole
    in_inbox: bool


@dataclass(frozen=True, kw_only=True)
class CodeFacts:
    """A code on the document's pages, once for its format and text however often it is
    printed: where it stands (page by page, a box per copy), a GiroCode read as its credit
    transfer, the identifiers it holds, and the amount fields of the document with the
    GiroCode's amount."""

    format: str
    text: str
    places: tuple[Location, ...]
    giro: GiroCode | None
    identifiers: tuple[tuple[IdentifierKind, str], ...]
    fields: tuple[FieldId, ...]


@dataclass(frozen=True, kw_only=True)
class DocumentFacts:
    """What the document shows of its contact (`domain.facts`, with spans of the text), the
    codes on its pages (None while they are not read), and, for admins, on the confirmed
    documents of which contacts besides the document's an identifier stands."""

    contact_id: ContactId | None
    facts: Facts
    codes: tuple[CodeFacts, ...] | None
    other_contacts: dict[tuple[IdentifierKind, str], frozenset[ContactId]] | None
    # The names of the persons found, for the editors of the document's space and admins; None
    # for readers, whose facts then hold no persons.
    person_names: dict[UserId, str] | None = None


async def _check_sortable(uow: UnitOfWork, order: DocumentOrder) -> None:
    """ValidationError if `order` sorts by a field that is missing or of another type than
    `SORTABLE_TYPES`."""
    if order.field is None:
        return
    definition = await uow.fields.find(order.field)
    if definition is None or definition.data_type not in SORTABLE_TYPES:
        raise ValidationError(because(ReasonCode.SORT_FIELD_INVALID))


async def _position(
    uow: UnitOfWork, user: User, order: DocumentOrder, after: DocumentId | None, *, everyone: bool
) -> DocumentPosition | None:
    """Where a page ended: by the last document's id, and its value of the sort key. That
    document is looked up within the caller's reach (`everyone`: all documents): one they may
    not read counts as gone, so that a cursor tells nothing about others' documents (#74)."""
    if after is None:
        return None
    if order.key is SortKey.ARRIVAL:
        return DocumentPosition(after)
    last = await uow.documents.find(after)
    if last is not None and not everyone:
        space = await uow.spaces.find(last.space_id)
        if space is None or document_access(user, last, space) is None:
            last = None
    if last is None:
        raise ValidationError("cursor: its document is gone; start from the first page")
    return DocumentPosition.of(last, order)


def _code_facts(codes: Sequence[Code], amounts: dict[FieldId, FieldValue]) -> tuple[CodeFacts, ...]:
    """The codes once for each format and text, in the order they first stand."""
    copies: dict[tuple[str, str], list[Code]] = {}
    for code in codes:
        copies.setdefault((code.format, code.text), []).append(code)
    return tuple(_one_code(found, amounts) for found in copies.values())


def _one_code(copies: Sequence[Code], amounts: dict[FieldId, FieldValue]) -> CodeFacts:
    code = copies[0]
    boxes: dict[int, list[Box]] = {}
    for item in copies:
        boxes.setdefault(item.page, []).append(item.box)
    giro = giro_code(code.text)
    fields: tuple[FieldId, ...] = ()
    if giro is not None and giro.amount is not None:
        fields = tuple(field for field, value in amounts.items() if value == giro.amount)
    return CodeFacts(
        format=code.format,
        text=code.text,
        places=tuple(Location(page, tuple(found)) for page, found in sorted(boxes.items())),
        giro=giro,
        identifiers=tuple(sorted(code_identifiers(code), key=lambda key: (key[0].value, key[1]))),
        fields=fields,
    )


@dataclass(frozen=True, kw_only=True)
class StoredFile:
    """A file of a document as it is stored: its size in bytes, its SHA-256, and what it says
    about itself (None if it cannot be read for that)."""

    size: int
    sha256: str
    metadata: FileMetadata | None


@dataclass(frozen=True, kw_only=True)
class DocumentFiles:
    """A document's files: the original, and the archive once there is one."""

    document: Document
    original: StoredFile
    archive: StoredFile | None


@dataclass(frozen=True)
class DocumentText:
    """A piece of the text read from the archive: `offset` and lengths count characters."""

    text: str
    offset: int
    total_length: int
    next_offset: int | None  # where the next piece starts; None at the end


class DocumentFile(StrEnum):
    ORIGINAL = "original"
    ARCHIVE = "archive"
    PREVIEW = "preview"
    PAGE = "page"  # the image of one page; `download` takes its number


@dataclass(frozen=True)
class FileInfo:
    """A downloaded file: its media type and a filename to offer."""

    media_type: str
    filename: str


class DocumentService:
    """Reading and changing documents. Ingest and processing live in PipelineService."""

    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        object_store: ObjectStore | None = None,
        *,
        rules: ChangeRules | None = None,
        metadata: MetadataReader | None = None,
    ) -> None:
        """`rules`: run the change rules when a person changes a document's metadata;
        `metadata` reads what its files say about themselves."""
        self._uow = uow
        self._clock = clock
        self._store = object_store
        self._rules = rules
        self._metadata = metadata

    @property
    def _object_store(self) -> ObjectStore:
        """Reading a document's files and what was read from them needs the object store."""
        assert self._store is not None, "DocumentService needs an object store to read files"
        return self._store

    async def get(self, actor: UserId, id: DocumentId) -> Document:
        async with self._uow() as uow:
            document, _ = await readable_document(uow, await load_actor(uow, actor), id)
            return document

    async def view(self, actor: UserId, id: DocumentId) -> DocumentView:
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document, space = await readable_document(uow, user, id)
            access = document_access(user, document, space)
        assert access is not None  # readable
        return DocumentView(document, access)

    async def read_text(
        self, actor: UserId, id: DocumentId, *, offset: int = 0, limit: int
    ) -> DocumentText:
        """`limit` characters of the document's text from `offset`. NotFoundError if the
        caller may not read the document; ValidationError for a negative offset or a limit
        below 1; ConflictError while the document has no text yet (it is not parsed)."""
        if offset < 0 or limit < 1:
            raise ValidationError("offset must be 0 or more and limit 1 or more")
        store = self._object_store
        async with self._uow() as uow:
            await readable_document(uow, await load_actor(uow, actor), id)
        try:
            data = await load_text(store, id)
        except NotFoundError:
            raise ConflictError(because(ReasonCode.NO_TEXT_YET)) from None
        text = data.decode("utf-8", errors="replace")
        end = offset + limit
        return DocumentText(
            text=text[offset:end],
            offset=offset,
            total_length=len(text),
            next_offset=end if end < len(text) else None,
        )

    async def facts(self, actor: UserId, id: DocumentId) -> DocumentFacts:
        """The facts of the document's text and codes, as the facts signal finds them now:
        a contact named or an identifier attached since counts at once; the persons it names
        only for the editors of its space and admins, and what is private about a person
        (aliases, birth date, identifiers, a contact's number that names them) only for admins
        and that person: anyone else sees another user named by their display name alone, and
        their numbers as unknown (`matching_persons`). NotFoundError if the caller may not read
        the document; ConflictError while it has no text yet."""
        store = self._object_store
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document, space = await readable_document(uow, user, id)
            contacts = await uow.contacts.list_all()
            definitions = await field_definitions(uow)
            editor = document_access(user, document, space) is SpaceRole.EDIT
            persons = await matching_persons(uow, user)
            labels = {item.id: item.label for item in await uow.users.list_all()}
        try:
            text = (await load_text(store, id)).decode("utf-8", errors="replace")
        except NotFoundError:
            raise ConflictError(because(ReasonCode.NO_TEXT_YET)) from None
        codes = await self._codes(id)
        pages = await load_layout(store, id)

        def found() -> Facts:
            facts = facts_in(text, contacts, codes or (), persons=persons, places=True)
            return on_pages(facts, TextPlaces(text, pages)) if pages else facts

        # Matching every contact's names against a long text takes a while: not in the loop.
        facts = await asyncio.to_thread(found)
        amounts = {
            field: value
            for field, value in document.fields.items()
            if field in definitions and definitions[field].data_type is FieldType.AMOUNT
        }
        views = None
        if codes is not None:
            views = _code_facts(codes, amounts)
        others = None
        if user.is_active_admin:
            async with self._uow() as uow:
                carrying = await uow.document_identifiers.contacts_of(
                    [item.key for item in facts.identifiers]
                )
            others = {key: contacts_ - {document.contact_id} for key, contacts_ in carrying.items()}
        return DocumentFacts(
            contact_id=document.contact_id,
            facts=facts,
            codes=views,
            other_contacts=others,
            person_names=(
                {
                    item.user_id: labels.get(item.user_id, str(item.user_id))
                    for item in facts.persons
                }
                if editor
                else None
            ),
        )

    async def _codes(self, id: DocumentId) -> tuple[Code, ...] | None:
        """The codes read from the archive's pages, None while they are not (or of an earlier
        version)."""
        try:
            return codes_from_json(json.loads(await self._object_store.get(codes_key(id))))
        except NotFoundError:
            return None
        except (ValueError, ValidationError):
            log.warning("an unreadable file of codes", extra={"document_id": str(id)})
            return None

    async def read_structure(self, actor: UserId, id: DocumentId) -> bytes:
        """The structure of the text as JSON: its pages, lines and words with their boxes
        (`structure_key`; a document parsed before 0.2 has Docling's until it is read again).
        NotFoundError if the caller may not read the document; ConflictError while it is not
        parsed."""
        store = self._object_store
        async with self._uow() as uow:
            await readable_document(uow, await load_actor(uow, actor), id)
        try:
            return await store.get(structure_key(id))
        except NotFoundError:
            raise ConflictError(because(ReasonCode.NO_STRUCTURE_YET)) from None

    async def query(
        self,
        actor: UserId,
        filter: DocumentFilter,
        *,
        order: DocumentOrder = NEWEST_FIRST,
        after: DocumentId | None = None,
        limit: int = PAGE_SIZE,
        all_users: bool = False,
    ) -> list[ListedDocument]:
        """Documents within the caller's reach matching `filter`, in `order` (newest first),
        after the page ending at the document `after`; with `all_users` (admins only), every
        document. Each is checked against the permission rules once more, and says whether it
        stands open in the caller's inbox (with `all_users`, in every user's). ValidationError
        if `after` is gone or out of reach while the list sorts by another key than the order of
        arrival, or if the order is by a field that is missing or of a type no list sorts by."""
        limit = max(1, min(limit, PAGE_LIMIT))
        async with self._uow() as uow:
            user = await load_lister(uow, actor, all_users, Action.LIST_ALL_DOCUMENTS)
            await _check_sortable(uow, order)
            position = await _position(uow, user, order, after, everyone=all_users)
            filter = await expanded(uow, filter)
            if all_users:
                documents = await uow.documents.query(
                    filter, order=order, after=position, limit=limit
                )
            else:
                documents = await uow.documents.query_visible(
                    actor, filter, order=order, after=position, limit=limit
                )
            spaces: dict[SpaceId, Space] = {}
            readable = []
            for document in documents:
                if document.space_id not in spaces:
                    spaces[document.space_id] = await uow.spaces.get(document.space_id)
                access = document_access(user, document, spaces[document.space_id])
                if access is None:
                    log.error(
                        "the repository listed a document the user may not read",
                        extra={"document_id": str(document.id), "user_id": str(actor)},
                    )
                    continue
                readable.append((document, access))
            waiting = await in_inbox(
                uow, actor, [document for document, _ in readable], all_users=all_users
            )
        return [
            ListedDocument(document, access, document.id in waiting)
            for document, access in readable
        ]

    async def download(
        self, actor: UserId, id: DocumentId, file: DocumentFile, target: Path, *, page: int = 1
    ) -> FileInfo:
        """Write a file of a readable document to the local path `target`. NotFoundError if
        the caller may not read the document or the file does not exist (yet); for a page,
        also if the document has fewer pages."""
        store = self._object_store
        async with self._uow() as uow:
            document, _ = await readable_document(uow, await load_actor(uow, actor), id)
        stem = document.file_title
        match file:
            case DocumentFile.ORIGINAL:
                key = original_key(document.sha256)
                info = FileInfo(document.media_type, document.original_filename)
            case DocumentFile.ARCHIVE:
                key, info = archive_key(id), FileInfo(media_types.PDF, f"{stem}.pdf")
            case DocumentFile.PREVIEW:
                key, info = preview_key(id), FileInfo(PAGE_MEDIA_TYPE, f"{stem}.webp")
            case DocumentFile.PAGE:
                if document.page_count is None or not 1 <= page <= document.page_count:
                    raise NotFoundError(
                        "page", id, because(ReasonCode.PAGE_NOT_FOUND, page=page, id=str(id))
                    )
                key, info = page_key(id, page), FileInfo(PAGE_MEDIA_TYPE, f"{stem}-{page}.webp")
        if not await store.exists(key):
            raise NotFoundError(
                file.value, id, because(ReasonCode.FILE_NOT_FOUND, file=file.value, id=str(id))
            )
        await store.download(key, target)
        return info

    async def files(self, actor: UserId, id: DocumentId) -> DocumentFiles:
        """The files of a readable document as they are stored: size, SHA-256 and their
        metadata (a PDF's document information and XMP, an image's EXIF). NotFoundError if
        the caller may not read the document."""
        store = self._object_store
        async with self._uow() as uow:
            document, _ = await readable_document(uow, await load_actor(uow, actor), id)
        original = await self._stored(original_key(document.sha256))
        archive = None
        if await store.exists(archive_key(id)):
            archive = await self._stored(archive_key(id))
        return DocumentFiles(document=document, original=original, archive=archive)

    async def _stored(self, key: str) -> StoredFile:
        data = await self._object_store.get(key)
        digest = await asyncio.to_thread(lambda: hashlib.sha256(data).hexdigest())
        metadata = None
        if self._metadata is not None:
            try:
                metadata = await self._metadata.read_metadata(data)
            except UnprocessableDocumentError as error:
                log.warning(
                    "a file's metadata cannot be read", extra={"key": key, "reason": str(error)}
                )
        return StoredFile(size=len(data), sha256=digest, metadata=metadata)

    async def document_counts(
        self, actor: UserId, by: CountBy, *, all_users: bool = False
    ) -> dict[UUID, int]:
        """How many documents within the caller's reach (with `all_users`, admins only: every
        document) have each contact, type or tag, or a value for each field. A tag counts what
        its filter finds: the documents with it or a tag below it (each once), a group those
        whose contact or type is in it or a group below it (`_tags.tag_counts`)."""
        async with self._uow() as uow:
            await load_lister(uow, actor, all_users, Action.COUNT_ALL_DOCUMENTS)
            user = None if all_users else actor
            if by is CountBy.TAG:
                return await tag_counts(uow, user)
            return await uow.documents.count_by(by, user)

    async def facets(
        self, actor: UserId, filter: DocumentFilter, *, all_users: bool = False
    ) -> DocumentFacets:
        """How many documents within the caller's reach (with `all_users`, admins only: every
        document) that match `filter` have each contact, type, group of contacts and types,
        topic, tag and month of their document date. What combines as either-or (contacts,
        types, groups, topics, the period) counts without its own choice, so that it tells
        what one more would add; tags combine as all-of and count with the whole filter. A
        tag, topic or group counts the documents with it or one below it, each once, as its
        filter finds them."""
        async with self._uow() as uow:
            await load_lister(uow, actor, all_users, Action.COUNT_ALL_DOCUMENTS)
            user = None if all_users else actor
            tree = await tag_tree(uow)
            found: dict[DocumentFilter, list[FacetRow]] = {}

            async def rows(criteria: DocumentFilter) -> list[FacetRow]:
                criteria = expand(criteria, tree)
                if criteria not in found:
                    found[criteria] = await uow.documents.facet_rows(criteria, user)
                return found[criteria]

            whole = await rows(filter)
            by_contact = await rows(replace(filter, contacts=None))
            by_type = await rows(replace(filter, document_types=None))
            by_topic = await rows(replace(filter, topics=None))
            by_date = await rows(replace(filter, document_dates=None))
            by_contact_group = await rows(replace(filter, contact_groups=()))
            by_type_group = await rows(replace(filter, document_type_groups=()))
            contact_groups = {item.id: item.group_ids for item in await uow.contacts.list_all()}
            type_groups = {item.id: item.group_ids for item in await uow.document_types.list_all()}
        dates = [row.document_date for row in by_date]
        return DocumentFacets(
            total=len(whole),
            contacts=dict(Counter(row.contact for row in by_contact)),
            document_types=dict(Counter(row.document_type for row in by_type)),
            contact_groups=tree.holders(
                contact_groups.get(row.contact, frozenset())
                for row in by_contact_group
                if row.contact is not None
            ),
            document_type_groups=tree.holders(
                type_groups.get(row.document_type, frozenset())
                for row in by_type_group
                if row.document_type is not None
            ),
            topics=tree.holders([row.topic] for row in by_topic if row.topic is not None),
            tags=tree.holders(row.tags for row in whole),
            months=dict(Counter(f"{day.year:04d}-{day.month:02d}" for day in dates if day)),
            undated=sum(1 for day in dates if day is None),
        )

    async def list_visible(self, actor: UserId) -> list[Document]:
        async with self._uow() as uow:
            await load_actor(uow, actor)
            return await uow.documents.list_visible_to(actor)

    async def filter_readers(self, id: DocumentId, candidates: Collection[UserId]) -> set[UserId]:
        """Those of `candidates` who may read the document now (admins: always); none if it does
        not exist. For pushing events to users (SSE), so it reads the current state."""
        if not candidates:
            return set()
        async with self._uow() as uow:
            document = await uow.documents.find(id)
            if document is None:
                return set()
            space = await uow.spaces.get(document.space_id)
            readers: set[UserId] = set()
            for candidate in set(candidates):
                user = await uow.users.find(candidate)
                if user is not None and can_read_document(user, document, space):
                    readers.add(candidate)
            return readers

    async def active_admins(self, candidates: Collection[UserId]) -> set[UserId]:
        """Those of `candidates` who are active admins: they hear of every document event (SSE),
        also of a deletion, whose stored readers name only those who had it within reach, and of
        a training of the classifier."""
        if not candidates:
            return set()
        async with self._uow() as uow:
            admins: set[UserId] = set()
            for candidate in set(candidates):
                user = await uow.users.find(candidate)
                if user is not None and user.is_active_admin:
                    admins.add(candidate)
            return admins

    async def processing_log(self, actor: UserId, id: DocumentId) -> list[NodeRun]:
        """Editors and admins: the log may hold technical details of failed runs. Similar
        documents the caller may not read are left out (`_access.readable_log`)."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            await controllable_document(uow, user, id, Action.READ_PROCESSING_LOG)
            return await readable_log(uow, user, await uow.processing_log.list_for(id))

    async def exchanges(self, actor: UserId, id: DocumentId, node: Node) -> list[RunExchange]:
        """Editors and admins, as the log: what `node` sent to the language model and got back,
        every run, oldest first; none if it never asked one. ValidationError for a node that
        does not ask the model."""
        if node not in EXCHANGE_NODES:
            raise ValidationError(f"node {node.value} does not ask a language model")
        store = self._object_store
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            await controllable_document(uow, user, id, Action.READ_EXCHANGES)
        for key in (exchanges_key(id, node), legacy_exchanges_key(id, node)):
            if key is None:
                continue
            try:
                data = await store.get(key)
            except NotFoundError:
                continue
            return exchanges_from_json(json.loads(data))
        return []

    async def review(self, actor: UserId, id: DocumentId) -> Review:
        """Editors and admins: what is open, and what the model proposed and how it was
        checked."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document, _ = await controllable_document(uow, user, id, Action.REVIEW_DOCUMENT)
            access = await access_to(uow, user, document)
            log = await readable_log(uow, user, await uow.processing_log.list_for(id))
        return Review(document, access, open_nodes(document, log), node_reviews(log))

    async def update_metadata(
        self, actor: UserId, id: DocumentId, changes: DocumentChanges
    ) -> Document:
        """Needs write access. Referenced contact, type, topic, tags and fields must exist; the
        topic is one the contact enables, or an admin's choice enables it there
        (`_access.checked_changes`). A change of confirming metadata confirms the document,
        unless it only adds or removes tags set by hand (`documents.confirms`)."""
        return (await self.change_metadata(actor, id, changes)).document

    async def change_metadata(
        self,
        actor: UserId,
        id: DocumentId,
        changes: DocumentChanges,
        *,
        dry_run: bool = False,
        confirm: bool = True,
    ) -> MetadataChange:
        """As `update_metadata`, and the change rules of the document's space and the global
        ones run (see `rules.changes`). The rules' report is for its editors and admins. With
        `dry_run`, nothing is stored: what would happen. Without `confirm` (an admin, on a
        document taken over from another system: the migration aligns it with its source), the
        change neither confirms the document nor counts as a person's decision; the checks and
        the rules are the same."""
        # When the document came in is no metadata the rules decide on: changed alone, they
        # do not run (Tobi, 21.10.2026).
        rules = None if changes.only_receipt else self._rules
        prepared = Prepared()
        if rules is not None:
            async with self._uow() as uow:
                document, _ = await writable_document(uow, await load_actor(uow, actor), id)
                candidates = await rules.rules(uow, document)
                candidates += await rules.followers(uow, candidates)
            prepared = await rules.prepare(candidates, document)
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document, _ = await writable_document(uow, user, id)
            if not confirm:
                admin_only(user, Action.CHANGE_UNCONFIRMED)
                if document.channel is not Channel.MIGRATION:
                    raise ValidationError(
                        "only a document taken over from another system (channel "
                        "'migration') is changed without confirming it"
                    )
            # What the person decided is the change as given; one the checks add (a topic the
            # new contact does not enable, cleared) is none of their decisions.
            given = changes
            changes = await checked_changes(uow, given, document, user)
            definitions = await field_definitions(uow)
            now = self._clock.now()
            before = copy.deepcopy(document)
            changed = document.apply_changes(changes, definitions, now)
            # Without `confirm`: the migration's alignment, the source system's values.
            if confirm and confirms(
                changed, before.tag_ids, document.tag_ids, await _manual(uow, before, document)
            ):
                document.mark_confirmed(now)
                if not dry_run:  # before the rules: the verdicts are on the person's change
                    await keep_verdicts(
                        uow,
                        Decision.CHANGE,
                        before=before,
                        after=document,
                        given=changed_fields(given),
                        definitions=definitions,
                        now=now,
                    )
            elif confirm and CONFIRMING & set(changed):
                document.record_decision()  # tags set by hand: no confirmation, but a decision
            run = None
            if rules is not None:
                run = await rules.after_change(
                    uow,
                    actor=user,
                    before=before,
                    document=document,
                    changes=given,
                    prepared=prepared,
                    definitions=definitions,
                    now=now,
                    log=not dry_run,
                )
            space = await uow.spaces.get(document.space_id)
            access = document_access(user, document, space)
            if not dry_run:
                await _save(uow, document)
                await uow.commit()
        report = access is not None and access.can_edit
        return MetadataChange(document, access, space, run if report else None, before)

    async def move(self, actor: UserId, id: DocumentId, space: SpaceId) -> None:
        """The editors of the document's space move it into a space they edit, or hand it over
        into another, active user's personal space; an admin moves any document into any space,
        but, as everyone, hands nothing over to a deactivated user (unless a member of their
        personal space). A green document becomes new for the editors of the target who could
        not read it before (`inbox.arrived`). A completed document then runs the target's rules
        (as change rules, `ChangeRules.after_arrival`); they leave the space the person chose."""
        prepared = Prepared()
        if self._rules is not None:
            async with self._uow() as uow:
                user = await load_actor(uow, actor)
                document, _ = await controllable_document(uow, user, id, Action.MOVE_DOCUMENT)
                entering = await uow.spaces.find(space)
                arriving = (
                    []
                    if entering is None
                    else await self._rules.arrival_rules(uow, document, entering)
                )
            prepared = await self._rules.prepare(arriving, document)
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document, source = await controllable_document(uow, user, id, Action.MOVE_DOCUMENT)
            target = await uow.spaces.find(space)
            if target is None or not (space_role(user, target) or can_hand_over(user, target)):
                raise NotFoundError("space", space)
            if not can_move_document(user, document, source, target):
                raise SpaceWriteDeniedError(target.id, target.name)
            if target.id == source.id:
                return
            if target.personal_of is not None and target.role_of(user.id) is None:
                receiver = await uow.users.find(target.personal_of)
                if receiver is None or not receiver.active:
                    raise NotFoundError("space", space)
            now = self._clock.now()
            before = copy.deepcopy(document)
            await move_by_person(
                uow,
                document,
                source,
                target,
                by=user,
                now=now,
                rules=self._rules,
                prepared=prepared,
            )
            await keep_verdicts(
                uow,
                Decision.MOVE,
                before=before,
                after=document,
                given={SPACE},
                definitions=await field_definitions(uow),
                now=now,
            )
            await uow.commit()

    async def delete(self, actor: UserId, id: DocumentId) -> None:
        """Editors and admins. Removes the metadata and queues the removal of its files
        (derivatives, and the original unless another document has the same file). Its tasks
        end (a late answer is refused)."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document, _ = await controllable_document(uow, user, id, Action.DELETE_DOCUMENT)
            document.delete(self._clock.now(), await _readers(uow, document))
            await cancel_tasks(uow, id, self._clock.now())
            await uow.documents.remove(id)
            await uow.outbox.add(document.pull_events())
            await uow.jobs.enqueue(
                REMOVE_FILES_JOB,
                RemoveFiles(id, document.sha256, document.page_count).to_json(),
                run_at=self._clock.now(),
            )
            await uow.commit()


async def _readers(uow: UnitOfWork, document: Document) -> list[UserId]:
    """The users who have the document within their reach now (`in_reach`): the editors of its
    space, and while it is green its readers (if their accounts are active). Admins hear of
    the deletion through their rights, not this list."""
    space = await uow.spaces.get(document.space_id)
    candidates = set(space.members)
    readers = []
    for candidate in candidates:
        user = await uow.users.find(candidate)
        if user is not None and in_reach(user, document, space):
            readers.append(candidate)
    return sorted(readers)


async def _manual(uow: UnitOfWork, before: Document, after: Document) -> frozenset[TagId]:
    """The tags added or removed between `before` and `after` that are set by hand only."""
    manual = set()
    for id in before.tag_ids ^ after.tag_ids:
        tag = await uow.tags.find(id)
        if tag is not None and tag.assignment is Assignment.MANUAL:
            manual.add(id)
    return frozenset(manual)


async def _save(uow: UnitOfWork, document: Document) -> None:
    await uow.documents.update(document)
    await uow.outbox.add(document.pull_events())
