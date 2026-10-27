import logging
from collections.abc import Awaitable, Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from lekto.core.domain.documents import UNSET, DocumentChanges, Unset
from lekto.core.domain.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from lekto.core.domain.fields import FieldDefinition, FieldType
from lekto.core.domain.identifiers import Identifier, IdentifierSource, Key
from lekto.core.domain.ids import ContactId, DocumentId, DocumentTypeId, FieldId, TagId, UserId
from lekto.core.domain.jobs import Job, RetryPolicy
from lekto.core.domain.master_data import (
    MAX_ALIASES,
    Assignment,
    Contact,
    DocumentType,
    MasterData,
    Tag,
    TagScope,
    one_line,
)
from lekto.core.domain.names import match_key, related
from lekto.core.domain.reasons import Action, ReasonCode, because
from lekto.core.domain.rules import References, Rule, RuleScope, title_rule
from lekto.core.domain.rules_json import definition_to_json
from lekto.core.domain.sorting import sort_key
from lekto.core.domain.templates import rename_field_key, unknown_values
from lekto.core.domain.templates import uses_field as field_used
from lekto.core.ports.clock import Clock
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.repository import DocumentFilter, DocumentPosition, NamedRepository
from lekto.core.ports.templates import TemplateRenderer
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import (
    contact_topics_lock,
    field_definitions,
    load_actor,
    require_admin,
)
from lekto.core.services._identifiers import as_seen, claim_identifiers, member_spaces
from lekto.core.services._jobs import LEASE, JobRunner
from lekto.core.services._tags import tag_tree

# A rename queues the indexing service's refresh job; the worker runs it through that service.
from lekto.core.services.indexing import REFRESH_JOB, RefreshKind, refresh_payload
from lekto.core.services.logos import drop_logo, queue_logo_fetch
from lekto.core.services.rules.management import renamed_field, uses_field
from lekto.core.services.rules.references import disable_rules, misfits, refers_to

log = logging.getLogger(__name__)

type Repo[K, E] = Callable[[UnitOfWork], NamedRepository[K, E]]
type NameCheck[E] = Callable[[UnitOfWork, E], Awaitable[None]]
"""Raises ConflictError if another item of the kind has the item's name."""

MANUAL = IdentifierSource.MANUAL
TAG_TREE_LOCK = "tags"
"""Held while a tag is made or changed, before the tree is read: two moves at once could
otherwise each pass `TagTree.check_parent` and together make a cycle or a sixth level."""
NORMALISE_JOB = "tags.normalise"
"""Payload: `tag_id` of a tag that got another parent, `after` (optional) the document the step
starts after (`normalise_tagged`)."""
NORMALISE_BATCH = 200
"""Documents a step of `NORMALISE_JOB` changes at most, one job and one unit of work each
(`MasterDataService`, `normalise_batch`)."""

_NORMALISE_RETRY = RetryPolicy(max_attempts=5, delay=timedelta(minutes=1))


@dataclass(frozen=True)
class TagMembers:
    """How many contacts each contact group and topic holds, how many document types each type
    group (`MasterDataService.tag_members`); tags holding none are left out."""

    contacts: Mapping[TagId, int]
    document_types: Mapping[TagId, int]


def _contacts(uow: UnitOfWork) -> NamedRepository[ContactId, Contact]:
    return uow.contacts


def _document_types(uow: UnitOfWork) -> NamedRepository[DocumentTypeId, DocumentType]:
    return uow.document_types


def _tags(uow: UnitOfWork) -> NamedRepository[TagId, Tag]:
    return uow.tags


def _fields(uow: UnitOfWork) -> NamedRepository[FieldId, FieldDefinition]:
    return uow.fields


class MasterDataService:
    """Contacts, document types, tags and field definitions. Changes are admin-only."""

    job_kinds = (NORMALISE_JOB,)
    """The kinds of jobs `run_next_job` runs."""

    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        templates: TemplateRenderer,
        *,
        index_renames: bool = False,
        store: ObjectStore | None = None,
        fetch_logos: bool = False,
        normalise_batch: int = NORMALISE_BATCH,
    ) -> None:
        """`templates`: reads which fields the templates of rules use. `index_renames`:
        renaming a contact, type or tag, nesting a tag elsewhere and changing the groups of a
        contact or type queue a job that brings the search index of the documents concerned
        up to date (set when there is a search index). `store`: where the logos of contacts
        are, which go with a deleted contact. `fetch_logos`: a contact without a logo, or with a
        fetched one, that gets a new domain entered among its identifiers queues fetching its
        logo (`logos.queue_logo_fetch`). `normalise_batch`: documents per step of normalising after
        a move (`normalise_tagged`)."""
        self._uow = uow
        self._clock = clock
        self._templates = templates
        self._index_renames = index_renames
        self._store = store
        self._fetch_logos = fetch_logos
        self._normalise_batch = normalise_batch
        self._jobs = JobRunner(uow, clock)

    @property
    def index_renames(self) -> bool:
        """Whether renames and moves queue a refresh of the search index."""
        return self._index_renames

    @property
    def fetch_logos(self) -> bool:
        """Whether a new domain of a contact queues fetching its logo."""
        return self._fetch_logos

    async def create_contact(
        self,
        actor: UserId,
        name: str,
        aliases: Collection[str] = (),
        identifiers: Collection[Identifier] = (),
        group_ids: Collection[TagId] = (),
        topic_ids: Collection[TagId] = (),
    ) -> Contact:
        """`identifiers`: entered by hand, each pointing to one of `topic_ids` or none;
        `group_ids`: contact groups; `topic_ids`: the topics it enables (see
        `change_contact`)."""
        item = Contact.create(name=name, now=self._now(), aliases=aliases)

        async def check(uow: UnitOfWork) -> None:
            item.set_groups(await _groups(uow, group_ids, TagScope.CONTACT))
            item.set_topics(await _topics(uow, topic_ids))
            item.set_identifiers(identifiers)
            await _check_contact(uow, item)

        return await self._create(
            actor, _contacts, item, check, after=lambda uow: self._logo_for(uow, item, ())
        )

    async def change_contact(
        self,
        actor: UserId,
        id: ContactId,
        *,
        name: str | None = None,
        aliases: Collection[str] | None = None,
        identifiers: Collection[Identifier] | None = None,
        rejected_identifiers: Collection[Identifier] | None = None,
        group_ids: Collection[TagId] | None = None,
        topic_ids: Collection[TagId] | None = None,
    ) -> Contact:
        """`None` leaves a part as it is. `aliases` replaces all of them; `identifiers`
        replaces those entered by hand (a learned one given is then entered by hand) and
        `rejected_identifiers` the rejected ones (a learned one given no longer counts and is
        not learned again). A value entered here that another contact learned or rejected
        moves here; one another contact has entered is a conflict. `group_ids` replaces the
        contact groups (tags of scope `contact`; a child and its parent leave the child).

        `topic_ids` replaces the topics it enables (tags of scope `topic`). Taking one away is
        a conflict while a document of the contact carries it; its identifiers lose it. An
        identifier points to one of the topics the contact enables after the change, or to
        none (ValidationError otherwise). A new domain entered (a learned one taken over too)
        for a contact without a logo, or with a fetched one, queues fetching it, with fetching
        on."""
        known: list[str] = []

        def change(item: Contact) -> None:
            known.extend(item.domains)
            if name is not None:
                item.rename(name)
            if aliases is not None:
                item.set_aliases(aliases)

        async def check(uow: UnitOfWork, item: Contact) -> None:
            if group_ids is not None:
                item.set_groups(await _groups(uow, group_ids, TagScope.CONTACT))
            if topic_ids is not None:
                for removed in item.set_topics(await _topics(uow, topic_ids)):
                    if await uow.documents.exists(contact=item.id, topic=removed):
                        topic = await uow.tags.get(removed)
                        raise ConflictError(
                            because(ReasonCode.TOPIC_CARRIED, contact=item.name, topic=topic.name)
                        )
            if identifiers is not None or rejected_identifiers is not None:
                entered = identifiers
                if entered is None:
                    entered = [entry for entry in item.identifiers if entry.source is MANUAL]
                item.set_identifiers(entered, rejected_identifiers)
            await _check_contact(uow, item)

        return await self._change(
            actor,
            _contacts,
            id,
            change,
            check=check,
            after=lambda uow, item: self._logo_for(uow, item, known),
            index_as=RefreshKind.CONTACT,
            indexed=lambda item: (item.name, item.group_ids),
            # A document that gets a topic meanwhile is seen, or sees it gone.
            lock=None if topic_ids is None else contact_topics_lock(id),
        )

    async def add_identifier(self, actor: UserId, id: ContactId, identifier: Identifier) -> Contact:
        """Enter one identifier by hand for the contact (admins), from a document that shows
        it, with its topic (one the contact enables, ValidationError otherwise) or none; the
        others stay as they are. One the contact learned or rejected is then entered; one
        another contact learned or rejected moves here; one another contact has entered is a
        conflict."""
        entered = Identifier(
            identifier.kind, identifier.value, MANUAL, identifier.topic_id, identifier.user_id
        )
        known: list[str] = []

        def change(item: Contact) -> None:
            known.extend(item.domains)
            manual = [e for e in item.identifiers if e.source is MANUAL and e.key != entered.key]
            rejected = [
                e
                for e in item.identifiers
                if e.source is IdentifierSource.REJECTED and e.key != entered.key
            ]
            item.set_identifiers([*manual, entered], rejected)

        return await self._change(
            actor,
            _contacts,
            id,
            change,
            check=lambda uow, item: _check_contact(uow, item),
            after=lambda uow, item: self._logo_for(uow, item, known),
        )

    async def reject_identifier(self, actor: UserId, id: ContactId, key: Key) -> Contact:
        """Reject one identifier at the contact (admins): one it learned no longer counts, one
        no contact has is noted there; training learns neither again. The others stay as they
        are. One the contact entered by hand is a conflict (change the contact instead); one
        another contact learned or rejected moves here, one it entered is a conflict."""
        kind, value = key
        dropped = Identifier(kind, value, IdentifierSource.REJECTED)

        def change(item: Contact) -> None:
            if any(e.key == key and e.source is MANUAL for e in item.identifiers):
                raise ConflictError(because(ReasonCode.IDENTIFIER_ENTERED, value=value))
            manual = [e for e in item.identifiers if e.source is MANUAL]
            rejected = [
                e
                for e in item.identifiers
                if e.source is IdentifierSource.REJECTED and e.key != key
            ]
            item.set_identifiers(manual, [*rejected, dropped])

        return await self._change(
            actor, _contacts, id, change, check=lambda uow, item: _check_contact(uow, item)
        )

    async def _logo_for(self, uow: UnitOfWork, contact: Contact, known: Collection[str]) -> None:
        """With fetching on: the contact's logo is fetched for a domain beyond `known`."""
        if self._fetch_logos:
            await queue_logo_fetch(uow, contact, known, self._now())

    async def create_document_type(
        self,
        actor: UserId,
        name: str,
        description: str | None = None,
        title_pattern: str | None = None,
        group_ids: Collection[TagId] = (),
        icon: str | None = None,
        fields: Mapping[FieldId, bool] | None = None,
        relation_target: bool = False,
    ) -> DocumentType:
        """`fields`: the fields that belong to it besides the global ones, each required (True)
        or optional, as `assign_fields` sets them, in the same transaction (issue #73: all or
        nothing). `title_pattern` (a template, `domain.templates`) may name them and the global
        fields; it is carried out by a rule of the type (`rules.title_rule`). `group_ids`: type
        groups (tags of scope `document_type`). `icon`: the name of a Lucide icon.
        `relation_target`: documents refer to those of the type by a contract or customer
        number (`DocumentType.relation_target`)."""
        item = DocumentType.create(
            name=name,
            now=self._now(),
            description=description,
            title_pattern=title_pattern,
            icon=icon,
            relation_target=relation_target,
        )

        async def check(uow: UnitOfWork) -> None:
            item.set_groups(await _groups(uow, group_ids, TagScope.DOCUMENT_TYPE))

        async def after(uow: UnitOfWork) -> None:
            # The fields need the stored type; the pattern may name them.
            if fields:
                await self._fit_fields(uow, item, fields)
            await self._check_title_pattern(uow, item)
            await self._keep_title_rule(uow, actor, item)

        return await self._create(actor, _document_types, item, check, after=after)

    async def change_document_type(
        self,
        actor: UserId,
        id: DocumentTypeId,
        *,
        name: str | None = None,
        description: str | Unset | None = UNSET,
        title_pattern: str | Unset | None = UNSET,
        group_ids: Collection[TagId] | None = None,
        icon: str | Unset | None = UNSET,
        relation_target: bool | None = None,
    ) -> DocumentType:
        """`None` (name, groups, relation target) or UNSET (description, title pattern, icon)
        leaves it as it is; None removes a description, pattern or icon. A pattern's fields
        must apply to the type. `group_ids` replaces the type groups (tags of scope
        `document_type`)."""

        def change(item: DocumentType) -> None:
            if name is not None:
                item.rename(name)
            if not isinstance(description, Unset):
                item.describe(description)
            if not isinstance(title_pattern, Unset):
                item.set_title_pattern(title_pattern)
            if not isinstance(icon, Unset):
                item.set_icon(icon)
            if relation_target is not None:
                item.mark_relation_target(relation_target)

        async def check(uow: UnitOfWork, item: DocumentType) -> None:
            if group_ids is not None:
                item.set_groups(await _groups(uow, group_ids, TagScope.DOCUMENT_TYPE))
            if not isinstance(title_pattern, Unset):
                await self._check_title_pattern(uow, item)

        return await self._change(
            actor,
            _document_types,
            id,
            change,
            check=check,
            after=lambda uow, item: self._keep_title_rule(uow, actor, item),
            index_as=RefreshKind.DOCUMENT_TYPE,
            indexed=lambda item: (item.name, item.group_ids),
        )

    async def create_tag(
        self,
        actor: UserId,
        name: str,
        *,
        scope: TagScope = TagScope.DOCUMENT,
        parent_id: TagId | None = None,
        assignment: Assignment | None = None,
        shown: bool | None = None,
        icon: str | None = None,
        color: str | None = None,
    ) -> Tag:
        """A tag of `scope` (fixed from now on), under `parent_id` (a tag of the same scope;
        at most five levels). `assignment` and `shown` follow the scope unless given: a group
        is set by hand only (ValidationError for `auto`) and hidden at documents. `icon`: the
        name of a Lucide icon; `color`: one of the palette or `#rrggbb`."""
        tag = Tag.create(
            name=name,
            now=self._now(),
            scope=scope,
            parent_id=parent_id,
            assignment=assignment,
            shown=shown,
            icon=icon,
            color=color,
        )

        async def check(uow: UnitOfWork) -> None:
            (await tag_tree(uow)).check_parent(tag, parent_id)

        return await self._create(
            actor, _tags, tag, check, lock=TAG_TREE_LOCK, name_free=_check_tag_name_free
        )

    async def change_tag(
        self,
        actor: UserId,
        id: TagId,
        *,
        name: str | None = None,
        parent_id: TagId | Unset | None = UNSET,
        assignment: Assignment | None = None,
        shown: bool | None = None,
        icon: str | Unset | None = UNSET,
        color: str | Unset | None = UNSET,
    ) -> Tag:
        """Admins only. `None` (name, assignment, shown) or UNSET (parent, icon, colour)
        leaves it as it is; a `parent_id` of None makes it a top-level tag, an `icon` or
        `color` of None removes it. The scope never changes. A new name or parent queues the
        refresh of the search index of the documents concerned (they hold the tag's
        ancestors). A new parent of a document tag or a group queues normalising what carries
        the tag and one now above it (`NORMALISE_JOB`, `normalise_tagged`)."""
        parents: list[TagId | None] = []

        def change(tag: Tag) -> None:
            parents.append(tag.parent_id)
            if name is not None:
                tag.rename(name)

        async def check(uow: UnitOfWork, tag: Tag) -> None:
            if not isinstance(parent_id, Unset):
                (await tag_tree(uow)).check_parent(tag, parent_id)
                tag.move(parent_id)
            if assignment is not None:
                tag.assign(assignment)
            if shown is not None:
                tag.shown = shown
            if not isinstance(icon, Unset):
                tag.set_icon(icon)
            if not isinstance(color, Unset):
                tag.set_color(color)

        async def normalise(uow: UnitOfWork, tag: Tag) -> None:
            # A topic needs no normalising: a document has one, a contact may enable both.
            moved = tag.parent_id != parents[0] and tag.parent_id is not None
            if moved and tag.scope is not TagScope.TOPIC:
                await uow.jobs.enqueue(NORMALISE_JOB, {"tag_id": str(id)}, run_at=self._clock.now())

        return await self._change(
            actor,
            _tags,
            id,
            change,
            check=check,
            after=normalise,
            index_as=RefreshKind.TAG,
            indexed=lambda tag: (tag.name, tag.parent_id),
            lock=TAG_TREE_LOCK,
            name_free=_check_tag_name_free,
        )

    # --- normalising after a move ---------------------------------------------------------------

    async def run_next_job(self) -> bool:
        """Claim and run a due normalisation (`NORMALISE_JOB`); False if none was due."""
        return await self._jobs.run_next([NORMALISE_JOB], LEASE, self._normalise)

    async def _normalise(self, job: Job) -> None:
        """One step: the batch, completing the job and queueing the next step commit together;
        a row changed meanwhile (or a lost claim) leaves all of it to the next attempt."""
        try:
            tag = TagId(UUID(str(job.payload["tag_id"])))
            after = job.payload.get("after")
            start = None if after is None else DocumentId(UUID(str(after)))
        except (KeyError, ValueError) as error:
            await self._jobs.invalid(job, error)
            return
        try:
            async with self._uow() as uow:
                await uow.lock(TAG_TREE_LOCK)
                changed, last = await normalise_tagged(
                    uow, tag, start, self._now(), batch=self._normalise_batch
                )
                await uow.jobs.complete(job, now=self._now())
                if last is not None:
                    await uow.jobs.enqueue(
                        NORMALISE_JOB,
                        {"tag_id": str(tag), "after": str(last)},
                        run_at=self._clock.now(),
                    )
                await uow.commit()
        except Exception as error:  # a row changed meanwhile, or the database failed: again
            log.warning("normalising tags failed", extra={"job_id": str(job.id)}, exc_info=True)
            reason = f"{type(error).__name__}: {error}"
            await self._jobs.again(job, reason, _NORMALISE_RETRY.next_run(job.tries, self._now()))
            return
        log.info("tags normalised", extra={"tag_id": str(tag), "changed": changed})

    async def create_field(
        self,
        actor: UserId,
        name: str,
        data_type: FieldType,
        *,
        document_type_ids: Collection[DocumentTypeId] | None = None,
        choices: Collection[str] = (),
        required: bool = False,
        required_document_type_ids: Collection[DocumentTypeId] = (),
        description: str | None = None,
        assignment: Assignment = Assignment.AUTO,
    ) -> FieldDefinition:
        """`document_type_ids=None` creates a global field; `required` makes it required
        (global), `required_document_type_ids` for those of its types (typed); `description`
        tells the language model what belongs in it; `assignment` whether the model reads it
        or only a person or a rule sets it."""
        definition = FieldDefinition.create(
            name=name,
            data_type=data_type,
            now=self._now(),
            document_type_ids=document_type_ids,
            choices=choices,
            required=required,
            required_types=required_document_type_ids,
            description=description,
            assignment=assignment,
        )

        async def check(uow: UnitOfWork) -> None:
            for document_type in definition.document_type_ids or ():
                await uow.document_types.get(document_type)
            await _check_key_free(uow, definition)

        return await self._create(actor, _fields, definition, check)

    async def change_field(
        self,
        actor: UserId,
        id: FieldId,
        *,
        name: str | None = None,
        choices: Collection[str] | None = None,
        document_type_ids: Collection[DocumentTypeId] | Unset | None = UNSET,
        required: bool | None = None,
        required_document_type_ids: Collection[DocumentTypeId] | None = None,
        description: str | Unset | None = UNSET,
        assignment: Assignment | None = None,
    ) -> FieldDefinition:
        """Admins only. Description (None or empty removes it; UNSET leaves it); whether the
        model reads it (`assignment`; None leaves it); name (title
        patterns that use it follow); choices (adding is free,
        removing only what no document uses); scope (`None`: global; widening is free,
        narrowing only while no document outside the new scope has a value; the types it is
        required for narrow with it); required (global) or the types it is required for. The
        data type never changes. ConflictError if values are in use."""
        old_keys: list[str] = []

        def change(definition: FieldDefinition) -> None:
            old_keys.append(definition.key)
            if name is not None:
                definition.rename(name)

        async def check(uow: UnitOfWork, definition: FieldDefinition) -> None:
            old_key = old_keys[0]
            if name is not None:
                await _check_key_free(uow, definition)
                if definition.key != old_key:
                    await self._rename_in_patterns(uow, actor, old_key, definition.key)
                    await self._rename_in_rules(uow, actor, old_key, definition.key)
            if choices is not None:
                removed = definition.change_choices(choices)
                if removed and await uow.documents.field_in_use(id, values=removed):
                    raise ConflictError(because(ReasonCode.CHOICES_IN_USE, choices=sorted(removed)))
            if not isinstance(document_type_ids, Unset):
                for document_type in document_type_ids or ():
                    await uow.document_types.get(document_type)
                narrower = definition.change_scope(document_type_ids)
                scope = definition.document_type_ids
                if (
                    narrower
                    and scope is not None
                    and await uow.documents.field_in_use(id, outside_types=scope)
                ):
                    raise ConflictError(because(ReasonCode.VALUES_OUTSIDE_SCOPE))
                if narrower:
                    for patterned in await self._patterns_using(uow, definition.key):
                        if not definition.applies_to(patterned.id):
                            raise ConflictError(
                                because(
                                    ReasonCode.TITLE_PATTERN_USES_FIELD,
                                    type=patterned.name,
                                    key=definition.key,
                                )
                            )
            definition.require(required=required, types=required_document_type_ids)
            if not isinstance(description, Unset):
                definition.describe(description)
            if assignment is not None:
                definition.assignment = assignment

        async def after(uow: UnitOfWork, definition: FieldDefinition) -> None:
            if choices is not None:
                fields = await field_definitions(uow)
                fields[definition.id] = definition
                await disable_rules(
                    uow,
                    self._now(),
                    because(ReasonCode.RULE_DISABLED_CHOICE, field=definition.name),
                    misfits(definition.id, fields),
                )

        return await self._change(actor, _fields, id, change, check=check, after=after)

    async def assign_fields(
        self, actor: UserId, id: DocumentTypeId, fields: Mapping[FieldId, bool]
    ) -> list[FieldDefinition]:
        """Admins only. The fields of a document type, from the type: exactly `fields` belong
        to it besides the global ones, each required (True) or optional. A field taken off
        narrows its scope as `change_field` does: ConflictError while documents of the type
        have a value for it or the type's title pattern uses it; ValidationError for a field
        of no other type (it would belong nowhere) or a global one (it belongs to every type).
        One transaction; returns the fields that changed."""
        async with self._uow() as uow:
            await require_admin(uow, actor, Action.CHANGE_MASTER_DATA)
            document_type = await uow.document_types.get(id)
            changed = await self._fit_fields(uow, document_type, fields)
            await uow.commit()
        return changed

    async def _fit_fields(
        self, uow: UnitOfWork, document_type: DocumentType, fields: Mapping[FieldId, bool]
    ) -> list[FieldDefinition]:
        """Make `fields` the type's fields besides the global ones (`assign_fields`), in `uow`
        without committing; the fields that changed."""
        id = document_type.id
        definitions = await field_definitions(uow)
        for field in fields:
            if field not in definitions:
                raise NotFoundError("field", field)
            if definitions[field].document_type_ids is None:
                name = definitions[field].name
                raise ValidationError(because(ReasonCode.FIELD_IS_GLOBAL, field=name))
        pattern = document_type.title_pattern
        changed: list[FieldDefinition] = []
        for definition in definitions.values():
            scope = definition.document_type_ids
            if scope is None:
                continue
            required = set(definition.required_types)
            if definition.id in fields:
                new_scope = scope | {id}
                required = required | {id} if fields[definition.id] else required - {id}
            elif id in scope:
                new_scope, required = scope - {id}, required - {id}
                if not new_scope:
                    raise ValidationError(
                        because(ReasonCode.FIELD_ONLY_THIS_TYPE, field=definition.name)
                    )
                if await uow.documents.field_in_use(definition.id, outside_types=new_scope):
                    raise ConflictError(
                        because(
                            ReasonCode.TYPE_HAS_VALUES,
                            type=document_type.name,
                            field=definition.name,
                        )
                    )
                if pattern and field_used(self._templates.check(pattern), definition.key):
                    raise ConflictError(
                        because(
                            ReasonCode.TITLE_PATTERN_USES_FIELD,
                            type=document_type.name,
                            key=definition.key,
                        )
                    )
            else:
                continue
            if new_scope == scope and required == definition.required_types:
                continue
            definition.change_scope(new_scope)
            definition.require(types=required)
            await uow.fields.update(definition)
            changed.append(definition)
        return changed

    # --- reading (every signed-in user) ----------------------------------------------------------

    async def list_contacts(self, actor: UserId) -> list[Contact]:
        """By name, each with the identifiers the caller sees (`identifiers.seen_by`): a
        number that names a user only for admins and that user, a learned one only for the
        members of the spaces it was learned in."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            items = await uow.contacts.list_all()
            spaces = await member_spaces(uow, user)
        return sorted(
            (as_seen(item, user, spaces) for item in items), key=lambda item: sort_key(item.name)
        )

    async def list_document_types(self, actor: UserId) -> list[DocumentType]:
        return await self._list(actor, _document_types)

    async def list_tags(self, actor: UserId, scope: TagScope | None = None) -> list[Tag]:
        """All tags, or those of `scope`; by name."""
        tags = await self._list(actor, _tags)
        return [tag for tag in tags if scope is None or tag.scope is scope]

    async def list_fields(self, actor: UserId) -> list[FieldDefinition]:
        return await self._list(actor, _fields)

    async def tag_members(self, actor: UserId) -> TagMembers:
        """What the groups and topics hold, as their filters find it (`TagTree.holders`):
        the contacts of each contact group and topic (in it or one below it, each once) and
        the document types of each type group. Master data are global: no reach."""
        async with self._uow() as uow:
            await load_actor(uow, actor)
            tree = await tag_tree(uow)
            contacts = await uow.contacts.list_all()
            types = await uow.document_types.list_all()
        return TagMembers(
            contacts=tree.holders(
                [*(item.group_ids for item in contacts), *(item.topic_ids for item in contacts)]
            ),
            document_types=tree.holders(item.group_ids for item in types),
        )

    async def get_contact(self, actor: UserId, id: ContactId) -> Contact:
        """With the identifiers the caller sees (`list_contacts`)."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            return as_seen(await uow.contacts.get(id), user, await member_spaces(uow, user))

    async def get_document_type(self, actor: UserId, id: DocumentTypeId) -> DocumentType:
        return await self._get(actor, _document_types, id)

    async def get_tag(self, actor: UserId, id: TagId) -> Tag:
        return await self._get(actor, _tags, id)

    async def get_field(self, actor: UserId, id: FieldId) -> FieldDefinition:
        return await self._get(actor, _fields, id)

    # --- deleting (admins; only what no document uses) -------------------------------------------

    async def delete_contact(self, actor: UserId, id: ContactId) -> None:
        """Not while a document has it; its logo goes with it."""
        store = self._store

        async def drop(uow: UnitOfWork) -> None:
            if store is not None:
                await drop_logo(uow, store, id)

        await self._delete(
            actor,
            _contacts,
            id,
            lambda uow: uow.documents.exists(contact=id),
            ("contact", lambda refs: refs.contacts),
            before=drop,
        )

    async def delete_document_type(self, actor: UserId, id: DocumentTypeId) -> None:
        async def used(uow: UnitOfWork) -> bool:
            if await uow.documents.exists(document_type=id):
                return True
            return any(
                id in (field.document_type_ids or ()) for field in await uow.fields.list_all()
            )

        async def drop_title_rule(uow: UnitOfWork) -> None:
            rule = await _title_rule(uow, id)
            if rule is not None:
                rule.delete(self._now())
                await uow.rules.update(rule)

        await self._delete(
            actor,
            _document_types,
            id,
            used,
            ("document type", lambda refs: refs.document_types),
            before=drop_title_rule,
        )

    async def delete_tag(self, actor: UserId, id: TagId) -> None:
        """Only a tag without tags below it that nothing uses: no document carries it (as a
        tag or its topic), no contact or type is in it, no contact enables it as a topic and
        no identifier points to it, no rule refers to it (ConflictError naming what does)."""

        async def used(uow: UnitOfWork) -> bool:
            tag = await uow.tags.get(id)
            if any(item.parent_id == id for item in await uow.tags.list_all()):
                raise ConflictError(because(ReasonCode.TAG_HAS_CHILDREN, tag=tag.name))
            if await uow.documents.exists(tag=id) or await uow.documents.exists(topic=id):
                return True
            contacts = await uow.contacts.list_all()
            for code, items in (
                (ReasonCode.TAG_HAS_CONTACTS, contacts),
                (ReasonCode.TAG_HAS_TYPES, await uow.document_types.list_all()),
            ):
                if any(id in item.group_ids for item in items):
                    raise ConflictError(because(code, tag=tag.name))
            enabling = sorted(
                item.name
                for item in contacts
                if id in item.topic_ids or any(entry.topic_id == id for entry in item.identifiers)
            )
            if enabling:
                raise ConflictError(
                    because(ReasonCode.TOPIC_ENABLED_BY, contacts=enabling, tag=tag.name)
                )
            rules = [
                rule
                for rule in await uow.rules.list_for(spaces=None, include_global=True)
                if id in rule.definition.references().tags
            ]
            if rules:
                names = sorted((rule.definition.name for rule in rules), key=sort_key)
                raise ConflictError(
                    because(ReasonCode.TAG_USED_BY_RULES, tag=tag.name, rules=names)
                )
            return False

        await self._delete(actor, _tags, id, used, ("tag", lambda refs: refs.tags))

    async def delete_field(self, actor: UserId, id: FieldId) -> None:
        """Not while a document has a value or a template of a rule uses it."""

        async def used(uow: UnitOfWork) -> bool:
            if await uow.documents.exists(field=id):
                return True
            definition = await uow.fields.get(id)
            patterns = await self._patterns_using(uow, definition.key)
            if patterns:
                types = sorted((item.name for item in patterns), key=sort_key)
                raise ConflictError(
                    because(ReasonCode.FIELD_USED_BY_PATTERNS, key=definition.key, types=types)
                )
            rules = await self._rules_using(uow, definition.key)
            if rules:
                names = sorted((rule.definition.name for rule in rules), key=sort_key)
                raise ConflictError(
                    because(ReasonCode.FIELD_USED_BY_RULES, key=definition.key, rules=names)
                )
            return False

        await self._delete(actor, _fields, id, used, ("field", lambda refs: refs.fields))

    async def _rules_using(self, uow: UnitOfWork, key: str) -> list[Rule]:
        """The rules whose templates use the field `key`, but those of title patterns (they
        follow their type)."""
        return [
            rule
            for rule in await uow.rules.list_for(spaces=None, include_global=True)
            if rule.managed_by is None and uses_field(self._templates, rule.definition, key)
        ]

    async def _patterns_using(self, uow: UnitOfWork, key: str) -> list[DocumentType]:
        return [
            item
            for item in await uow.document_types.list_all()
            if item.title_pattern is not None
            and field_used(self._templates.check(item.title_pattern), key)
        ]

    async def _rename_in_patterns(self, uow: UnitOfWork, actor: UserId, old: str, new: str) -> None:
        """Title patterns that use `field.<old>` take the new key, and so do their rules."""
        for document_type in await self._patterns_using(uow, old):
            pattern = document_type.title_pattern or ""
            document_type.set_title_pattern(rename_field_key(pattern, old, new))
            await uow.document_types.update(document_type)
            await self._keep_title_rule(uow, actor, document_type)

    async def _check_title_pattern(self, uow: UnitOfWork, document_type: DocumentType) -> None:
        """A pattern is a valid template whose fields apply to the type."""
        if document_type.title_pattern is None:
            return
        keys = {
            item.key for item in await uow.fields.list_all() if item.applies_to(document_type.id)
        }
        unknown = unknown_values(self._templates.check(document_type.title_pattern), keys)
        if unknown:
            raise ValidationError(
                because(
                    ReasonCode.TITLE_PATTERN_UNKNOWN,
                    value=unknown[0],
                    type=document_type.name,
                )
            )

    async def _keep_title_rule(
        self, uow: UnitOfWork, actor: UserId, document_type: DocumentType
    ) -> None:
        """The type's rule as its pattern says: made, given a new version, or deleted."""
        rule = await _title_rule(uow, document_type.id)
        now = self._now()
        if document_type.title_pattern is None:
            if rule is not None:
                rule.delete(now)
                await uow.rules.update(rule)
            return
        definition = title_rule(document_type)
        if rule is None:
            await uow.rules.add(
                Rule.create(
                    scope=RuleScope.GLOBAL,
                    space_id=None,
                    definition=definition,
                    by=actor,
                    now=now,
                    managed_by=document_type.id,
                )
            )
        elif definition_to_json(rule.definition) != definition_to_json(definition):
            rule.change(definition, actor, now)
            await uow.rules.update(rule)

    async def _rename_in_rules(self, uow: UnitOfWork, actor: UserId, old: str, new: str) -> None:
        """The templates of rules that use `field.<old>` take the new key (a new version)."""
        for rule in await self._rules_using(uow, old):
            rule.change(renamed_field(rule.definition, old, new), actor, self._now())
            await uow.rules.update(rule)

    async def _list[K, E: MasterData](self, actor: UserId, repository: Repo[K, E]) -> list[E]:
        async with self._uow() as uow:
            await load_actor(uow, actor)
            items = await repository(uow).list_all()
        return sorted(items, key=lambda item: sort_key(item.name))

    async def _get[K, E: MasterData](self, actor: UserId, repository: Repo[K, E], id: K) -> E:
        async with self._uow() as uow:
            await load_actor(uow, actor)
            return await repository(uow).get(id)

    async def _delete[K, E: MasterData](
        self,
        actor: UserId,
        repository: Repo[K, E],
        id: K,
        used: Callable[[UnitOfWork], Awaitable[bool]],
        referenced: tuple[str, Callable[[References], frozenset[K]]],
        *,
        before: Callable[[UnitOfWork], Awaitable[None]] | None = None,
    ) -> None:
        """Only what no document uses; rules that refer to it are disabled. `before`: what
        goes with it, before it goes."""
        kind, select = referenced
        async with self._uow() as uow:
            await require_admin(uow, actor, Action.CHANGE_MASTER_DATA)
            item = await repository(uow).get(id)
            if await used(uow):
                raise ConflictError(because(ReasonCode.IN_USE, name=item.name))
            if before is not None:
                await before(uow)
            await repository(uow).remove(id)
            await disable_rules(
                uow,
                self._now(),
                because(ReasonCode.RULE_DISABLED_DELETED, kind=kind, name=item.name),
                refers_to(select, id),
            )
            await uow.commit()

    def _now(self) -> datetime:
        return self._clock.now()

    async def _create[K, E: MasterData](
        self,
        actor: UserId,
        repository: Repo[K, E],
        item: E,
        check: Callable[[UnitOfWork], Awaitable[None]] | None = None,
        *,
        after: Callable[[UnitOfWork], Awaitable[None]] | None = None,
        lock: str | None = None,
        name_free: NameCheck[E] | None = None,
    ) -> E:
        """`after`: what follows from the new item, in the same unit of work. `lock`: a name
        the unit locks before it reads. `name_free`: the check that no other item has the name
        (None: `_check_name_free`, unique per kind)."""
        async with self._uow() as uow:
            if lock is not None:
                await uow.lock(lock)
            await require_admin(uow, actor, Action.CHANGE_MASTER_DATA)
            if check is not None:
                await check(uow)
            if name_free is None:
                await _check_name_free(repository(uow), item)
            else:
                await name_free(uow, item)
            await repository(uow).add(item)
            if after is not None:
                await after(uow)
            await uow.commit()
        return item

    async def _change[K, E: MasterData](
        self,
        actor: UserId,
        repository: Repo[K, E],
        id: K,
        change: Callable[[E], None],
        *,
        check: Callable[[UnitOfWork, E], Awaitable[None]] | None = None,
        after: Callable[[UnitOfWork, E], Awaitable[None]] | None = None,
        index_as: RefreshKind | None = None,
        indexed: Callable[[E], object] = lambda item: item.name,
        lock: str | None = None,
        name_free: NameCheck[E] | None = None,
    ) -> E:
        """`change`, then the name's check (`name_free` as for `_create`), then `check`: the
        part of the change that reads the unit of work. `after`: what follows from the change,
        in the same unit of work. `index_as`: the kind whose documents' search index is brought
        up to date when what the index holds of it (`indexed`: the name) changed. `lock`: a
        name the unit locks before it reads."""
        async with self._uow() as uow:
            if lock is not None:
                await uow.lock(lock)
            await require_admin(uow, actor, Action.CHANGE_MASTER_DATA)
            item = await repository(uow).get(id)
            before = indexed(item)
            change(item)
            if name_free is None:
                await _check_name_free(repository(uow), item)
            else:
                await name_free(uow, item)
            if check is not None:
                await check(uow, item)
            await repository(uow).update(item)
            if after is not None:
                await after(uow, item)
            if index_as is not None and indexed(item) != before:
                await self._refresh(uow, index_as, item.id)
            await uow.commit()
        return item

    async def _refresh(self, uow: UnitOfWork, kind: RefreshKind, id: UUID) -> None:
        """Queue the refresh of the search index of the documents of the contact, type or tag
        (`IndexingService`), with a search index."""
        if self._index_renames:
            await uow.jobs.enqueue(REFRESH_JOB, refresh_payload(kind, id), run_at=self._clock.now())


async def normalise_tagged(
    uow: UnitOfWork, id: TagId, after: DocumentId | None, now: datetime, *, batch: int
) -> tuple[int, DocumentId | None]:
    """One step of `NORMALISE_JOB` after `id` got another parent, in `uow` (which holds
    `TAG_TREE_LOCK`, so the tree is the one the step works with): what carries `id` or a tag
    below it together with a tag now above it keeps only the one below (`TagTree.normalise`),
    as if set anew. For a document tag the next `batch` documents (by id, after
    `after`) that carry one of them, each changed one an update of its own (`document.updated`
    refreshes its search entry); for a group the contacts or document types in it (their
    groups with ancestors, what the index holds, stay the same). Neither lane nor confirmation
    changes. Returns how many were changed, and the last document of a full batch: the next
    step starts after it (None: done; also for a tag that is gone)."""
    tree = await tag_tree(uow)
    if id not in tree:
        return 0, None
    scope = tree.tags[id].scope
    below = tree.with_descendants([id])
    changed = 0
    if scope is TagScope.DOCUMENT:
        page = await uow.documents.query(
            DocumentFilter(tags=(below,)),
            after=DocumentPosition.after(after),
            limit=batch,
        )
        definitions = None
        for document in page:
            tags = tree.normalise(document.tag_ids)
            if tags == document.tag_ids:
                continue
            if definitions is None:
                definitions = await field_definitions(uow)
            document.apply_changes(DocumentChanges(tag_ids=tags), definitions, now)
            await uow.documents.update(document)
            await uow.outbox.add(document.pull_events())
            changed += 1
        return changed, page[-1].id if len(page) == batch else None
    if not scope.is_group:
        return 0, None  # a topic: a document carries one, a contact may enable both
    members: Sequence[Contact | DocumentType] = (
        await uow.contacts.list_all()
        if scope is TagScope.CONTACT
        else await uow.document_types.list_all()
    )
    for member in members:
        groups = tree.normalise(member.group_ids)
        if not member.group_ids & below or groups == member.group_ids:
            continue
        member.set_groups(groups)
        if isinstance(member, Contact):
            await uow.contacts.update(member)
        else:
            await uow.document_types.update(member)
        changed += 1
    return changed, None


async def _check_name_free[K, E: MasterData](repository: NamedRepository[K, E], item: E) -> None:
    """Names are unique per kind. The repository holds that rule too (`core.ports.repository`);
    this look-up gives the message."""
    existing = await repository.find_by_name(item.name)
    if existing is not None and existing.id != item.id:
        raise ConflictError(because(ReasonCode.NAME_TAKEN, name=item.name))


async def _check_tag_name_free(uow: UnitOfWork, tag: Tag) -> None:
    """Names are unique per scope (as `_check_name_free`)."""
    existing = await uow.tags.find_by_name(tag.name, tag.scope)
    if existing is not None and existing.id != tag.id:
        raise ConflictError(because(ReasonCode.NAME_TAKEN, name=tag.name))


async def _groups(uow: UnitOfWork, ids: Collection[TagId], scope: TagScope) -> frozenset[TagId]:
    """`ids` as the groups of a contact or a type: tags of `scope` (NotFoundError for one
    that does not exist, ValidationError for one of another scope), normalised."""
    if not ids:
        return frozenset()
    tree = await tag_tree(uow)
    for id in ids:
        tree.require(id, scope)
    return tree.normalise(ids)


async def _topics(uow: UnitOfWork, ids: Collection[TagId]) -> frozenset[TagId]:
    """`ids` as the topics a contact enables: tags of scope `topic` (NotFoundError for one that
    does not exist, ValidationError for one of another scope). A topic and one below it are
    both enabled: a document may carry either."""
    if not ids:
        return frozenset()
    tree = await tag_tree(uow)
    for id in ids:
        tree.require(id, TagScope.TOPIC)
    return frozenset(ids)


async def _check_key_free(uow: UnitOfWork, definition: FieldDefinition) -> None:
    """Templates name a field by its key: no two fields may share one."""
    for other in await uow.fields.list_all():
        if other.id != definition.id and other.key == definition.key:
            raise ConflictError(
                because(
                    ReasonCode.FIELD_KEY_TAKEN,
                    field=definition.name,
                    key=definition.key,
                    other=other.name,
                )
            )


async def _title_rule(uow: UnitOfWork, document_type: DocumentTypeId) -> Rule | None:
    """The live rule of the type's title pattern, if it has one."""
    for rule in await uow.rules.list_for(spaces=[], include_global=True):
        if rule.managed_by == document_type:
            return rule
    return None


async def _check_contact(uow: UnitOfWork, contact: Contact) -> None:
    await _check_contact_names(uow, contact)
    await _check_contact_identifiers(uow, contact)


async def _check_contact_identifiers(uow: UnitOfWork, contact: Contact) -> None:
    """No identifier of the contact is one another contact entered by hand, or a person's (a
    user's profile). Another contact's learned or rejected one gives way, in `uow`: a person's
    choice is the newer word (`claim_identifiers`; admins change contacts). A user an
    identifier names exists."""
    for item in contact.identifiers:
        if item.user_id is not None:
            await uow.users.get(item.user_id)
    await claim_identifiers(uow, [contact])


async def replace_learned_identifiers(
    uow: UnitOfWork,
    learned: Mapping[ContactId, Collection[Identifier]],
) -> int:
    """Make `learned` the learned identifiers of all contacts (training found them), in `uow`
    without committing; a contact not in `learned` has none afterwards. Values entered or
    rejected anywhere stay where they are. A learned one points to its topic if its contact
    enables it (`Contact.set_learned`). Returns how many are learned. A learned domain fetches
    no logo: only one entered does (`Contact.domains`)."""
    contacts = await uow.contacts.list_all()
    taken = {
        item.key
        for contact in contacts
        for item in contact.identifiers
        if item.source is not IdentifierSource.LEARNED
    }
    fresh = {
        contact.id: [item for item in learned.get(contact.id, ()) if item.key not in taken]
        for contact in contacts
    }
    # First every contact gives up what it no longer holds, then takes what is new: a value
    # may move from one contact to another, and it is unique across contacts.
    for contact in contacts:
        keep = {item.key for item in fresh[contact.id]}
        held = [item for item in contact.identifiers if item.source is IdentifierSource.LEARNED]
        if any(item.key not in keep for item in held):
            contact.set_learned([item for item in held if item.key in keep])
            await uow.contacts.update(contact)
    count = 0
    for contact in contacts:
        before = list(contact.identifiers)
        contact.set_learned(fresh[contact.id])
        count += sum(item.source is IdentifierSource.LEARNED for item in contact.identifiers)
        if contact.identifiers != before:
            await uow.contacts.update(contact)
    return count


async def _check_contact_names(uow: UnitOfWork, contact: Contact) -> None:
    """No name or alias of the contact is a name or an alias of another contact. An alias
    must not even match another contact's name or alias the way classification compares
    names (legal forms and punctuation aside): both would always be equally close."""
    for other in await uow.contacts.list_all():
        if other.id == contact.id:
            continue
        for name in contact.names():
            if other.is_named(name):
                raise ConflictError(
                    because(ReasonCode.NAME_OF_CONTACT, name=name, contact=other.name)
                )
        for mine, theirs in _alias_pairs(contact, other):
            if match_key(mine) and match_key(mine) == match_key(theirs):
                raise ConflictError(
                    because(ReasonCode.NAME_TOO_CLOSE, name=mine, other=theirs, contact=other.name)
                )


def _alias_pairs(contact: Contact, other: Contact) -> Iterator[tuple[str, str]]:
    """Pairs of their names in which at least one is an alias."""
    for mine in contact.names():
        for theirs in other.names():
            if mine in contact.aliases or theirs in other.aliases:
                yield mine, theirs


async def learn_alias(
    uow: UnitOfWork, contact_id: ContactId, alias: str, *, threshold: float
) -> Contact | None:
    """Make `alias` an alias of the contact, in `uow` without committing: a person chose the
    contact for a document in which the language model read `alias`. The contact with the new
    alias, or None if nothing is learned:

    - it is a name or an alias of the contact already, or the contact has all aliases it may;
    - it is not related to the contact's names (`names.related` with `threshold`, the one
      from which a name suggests a contact): the model read something else, often the
      recipient, and the person corrected it;
    - it matches another contact's name (see `names.match_key`).

    An alias of another contact that it matches moves (the person's choice is the newer word).
    """
    alias = one_line(alias)
    key = match_key(alias)
    contacts = await uow.contacts.list_all()
    target = next((item for item in contacts if item.id == contact_id), None)
    if not key or target is None or target.is_named(alias):
        return None
    if len(target.aliases) >= MAX_ALIASES or not _related(key, target, threshold):
        return None
    others = [item for item in contacts if item.id != contact_id]
    if any(match_key(other.name) == key for other in others):
        return None
    for other in others:
        kept = [item for item in other.aliases if match_key(item) != key]
        if len(kept) < len(other.aliases):
            other.set_aliases(kept)
            await uow.contacts.update(other)
    target.set_aliases([*target.aliases, alias])
    await uow.contacts.update(target)
    return target


def _related(key: str, contact: Contact, threshold: float) -> bool:
    return any(related(key, match_key(own), threshold=threshold) for own in contact.names())
