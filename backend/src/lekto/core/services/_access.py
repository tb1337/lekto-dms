"""Loading entities, together with the caller's rights where they matter."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from uuid import UUID

from lekto.core.domain.documents import Document, DocumentChanges, Sha256, Unset
from lekto.core.domain.errors import (
    AuthenticationError,
    DuplicateDocumentError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from lekto.core.domain.fields import FieldDefinition
from lekto.core.domain.ids import ContactId, DocumentId, FieldId, SpaceId, UserId
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.master_data import TagScope
from lekto.core.domain.permissions import (
    can_edit_document,
    can_read_document,
    document_access,
    space_role,
)
from lekto.core.domain.pipeline import Node, NodeRun
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import User
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.services._tags import tag_tree


async def load_actor(uow: UnitOfWork, actor: UserId) -> User:
    """The caller; AuthenticationError if the account is gone or deactivated (it may have
    changed since the request was authenticated)."""
    user = await uow.users.find(actor)
    if user is None or not user.active:
        raise AuthenticationError("authentication is required")
    return user


async def field_definitions(uow: UnitOfWork) -> dict[FieldId, FieldDefinition]:
    """Every field definition, by id."""
    return {item.id: item for item in await uow.fields.list_all()}


def admin_only(user: User, action: str) -> None:
    """PermissionDeniedError ("only admins <action>") unless `user` is an active admin."""
    if not user.is_active_admin:
        raise PermissionDeniedError(f"only admins {action}")


async def require_admin(uow: UnitOfWork, actor: UserId, action: str) -> User:
    """The caller, if an active admin (`admin_only`)."""
    user = await load_actor(uow, actor)
    admin_only(user, action)
    return user


async def load_lister(uow: UnitOfWork, actor: UserId, all_users: bool, action: str) -> User:
    """The caller of a list; with `all_users` (every user's instead of their own or their
    reach), only an active admin (`admin_only`, "only admins <action>")."""
    user = await load_actor(uow, actor)
    if all_users:
        admin_only(user, action)
    return user


async def readable_document(uow: UnitOfWork, user: User, id: DocumentId) -> tuple[Document, Space]:
    document = await uow.documents.find(id)
    if document is None:
        raise NotFoundError("document", id)
    space = await uow.spaces.get(document.space_id)
    if not can_read_document(user, document, space):
        raise NotFoundError("document", id)
    return document, space


async def writable_document(uow: UnitOfWork, user: User, id: DocumentId) -> tuple[Document, Space]:
    """The document and its space, if `user` edits it (`can_edit_document`); NotFoundError if
    they cannot read it, PermissionDeniedError if they only read it."""
    document, space = await readable_document(uow, user, id)
    if not can_edit_document(user, document, space):
        raise PermissionDeniedError(f"no write access to document {id}")
    return document, space


async def controllable_document(
    uow: UnitOfWork, user: User, id: DocumentId, action: str
) -> tuple[Document, Space]:
    """The document and its space, if `user` edits it (`can_edit_document`: an editor of its
    space or an admin); NotFoundError if they cannot read it, PermissionDeniedError ("only
    editors and admins <action>") if they only read it."""
    document, space = await readable_document(uow, user, id)
    if not can_edit_document(user, document, space):
        raise PermissionDeniedError(f"only editors and admins {action}")
    return document, space


async def access_to(uow: UnitOfWork, user: User, document: Document) -> SpaceRole:
    """The access of `user`, who may read `document`, to it in the space it lies in now."""
    access = document_access(user, document, await uow.spaces.get(document.space_id))
    assert access is not None  # readable
    return access


def space_label(space: Space, users: Mapping[UserId, User]) -> str:
    """How a person reads a space's name: a personal space by its user's name."""
    if space.personal_of is not None and (user := users.get(space.personal_of)) is not None:
        return user.username
    return space.name


async def visible_space(uow: UnitOfWork, user: User, id: SpaceId) -> Space:
    """The space, if `user` is a member or an admin; NotFoundError otherwise."""
    space = await uow.spaces.find(id)
    if space is None or space_role(user, space) is None:
        raise NotFoundError("space", id)
    return space


async def duplicate_of(
    uow: UnitOfWork, user: User, sha256: Sha256
) -> DuplicateDocumentError | None:
    """The error for a file that lies in Lekto already (every file exists once per
    installation): it names the document if `user` may read it; one in a space they cannot
    see stays unnamed. None for a new file."""
    existing = await uow.documents.find_by_sha256(sha256)
    if existing is None:
        return None
    space = await uow.spaces.get(existing.space_id)
    return DuplicateDocumentError(existing.id if can_read_document(user, existing, space) else None)


def contact_topics_lock(contact: ContactId) -> str:
    """The lock (`UnitOfWork.lock`) a unit takes before it reads the topics a contact enables
    to give a document of the contact a topic, or to take topics away from the contact: one
    waits for the other and sees what it did."""
    return f"contact-topics:{contact}"


async def checked_changes(
    uow: UnitOfWork,
    changes: DocumentChanges,
    document: Document | None = None,
    actor: User | None = None,
) -> DocumentChanges:
    """The change as it is applied to `document` (None: a new one): its tags normalised (a
    child and its parent set together leave the child, `TagTree.normalise`), and its topic one
    the contact after the change enables.

    A contact given that does not enable the document's topic clears the topic. A topic given
    that the contact does not enable is enabled at the contact, in `uow`, if `actor` is an
    active admin; otherwise, and for a topic without a contact, it is a ValidationError. A
    topic the document keeps or gets is checked under `contact_topics_lock`: the unit must
    not have written yet.
    NotFoundError if a contact, type, tag or topic it refers to does not exist,
    ValidationError for a tag that does not describe documents (a group, a topic) or a topic
    that is none."""
    if not isinstance(changes.contact_id, Unset) and changes.contact_id is not None:
        await uow.contacts.get(changes.contact_id)
    if not isinstance(changes.document_type_id, Unset) and changes.document_type_id is not None:
        await uow.document_types.get(changes.document_type_id)
    topic_given = not isinstance(changes.topic_id, Unset)
    if isinstance(changes.tag_ids, Unset) and not topic_given:
        return await _fitted_topic(uow, changes, document, actor)
    tree = await tag_tree(uow)
    if not isinstance(changes.tag_ids, Unset):
        for id in changes.tag_ids:
            tree.require(id, TagScope.DOCUMENT)
        changes = replace(changes, tag_ids=tree.normalise(changes.tag_ids))
    if not isinstance(changes.topic_id, Unset) and changes.topic_id is not None:
        tree.require(changes.topic_id, TagScope.TOPIC)
    return await _fitted_topic(uow, changes, document, actor)


async def _fitted_topic(
    uow: UnitOfWork, changes: DocumentChanges, document: Document | None, actor: User | None
) -> DocumentChanges:
    """`changes` with the topic the contact after it enables (see `checked_changes`); only a
    change of the contact or the topic looks at it."""
    contact_given = not isinstance(changes.contact_id, Unset)
    topic_given = not isinstance(changes.topic_id, Unset)
    if not (contact_given or topic_given):
        return changes
    current = document.contact_id if document is not None else None
    contact_id = changes.contact_id if not isinstance(changes.contact_id, Unset) else current
    topic_id = changes.topic_id if not isinstance(changes.topic_id, Unset) else None
    if not topic_given and document is not None:
        topic_id = document.topic_id
    if topic_id is None:
        return changes
    if contact_id is None:
        if topic_given:
            raise ValidationError("a topic is one of the contact's: give the document a contact")
        return replace(changes, topic_id=None)
    await uow.lock(contact_topics_lock(contact_id))
    contact = await uow.contacts.get(contact_id)
    if topic_id in contact.topic_ids:
        return changes
    if not topic_given:
        return replace(changes, topic_id=None)  # the new contact does not enable it
    if actor is not None and actor.is_active_admin:
        contact.enable_topic(topic_id)
        await uow.contacts.update(contact)
        return changes
    topic = await uow.tags.get(topic_id)
    raise ValidationError(
        f"'{contact.name}' does not enable the topic '{topic.name}' (an admin enables it at "
        "the contact, or by choosing it)"
    )


async def readable_log(uow: UnitOfWork, user: User, log: Sequence[NodeRun]) -> list[NodeRun]:
    """`log` as `user` may see it. The similar documents a signal found are searched from the
    uploader's reach, which an editor of the document's space need not share: they see a
    similar document (with what it carries, and as the source of a candidate) only if they may
    read it, and what the uploader's confirmed documents carry (`known`) not at all. Admins
    see everything; the stored log keeps everything for reprocessing."""
    if user.is_active_admin:
        return list(log)
    readable: dict[str, bool] = {}

    async def may_read(id: JsonValue) -> bool:
        if not isinstance(id, str):
            return False
        if id not in readable:
            try:
                document = await uow.documents.find(DocumentId(UUID(id)))
            except ValueError:
                document = None
            readable[id] = document is not None and can_read_document(
                user, document, await uow.spaces.get(document.space_id)
            )
        return readable[id]

    result = []
    for run in log:
        neighbours = run.node is Node.SIGNAL_NEIGHBOURS
        output = await _readable(run.result.output, may_read, neighbours=neighbours)
        assert isinstance(output, dict)
        result.append(replace(run, result=replace(run.result, output=output)))
    return result


async def _readable(
    value: JsonValue, may_read: Callable[[JsonValue], Awaitable[bool]], *, neighbours: bool
) -> JsonValue:
    if isinstance(value, list):
        return [await _readable(item, may_read, neighbours=False) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, JsonValue] = {}
    for key, item in value.items():
        if neighbours and key == "known":
            continue
        if neighbours and key == "neighbours" and isinstance(item, list):
            result[key] = [
                found
                for found in item
                if isinstance(found, dict) and await may_read(found.get("document_id"))
            ]
        elif key == "documents" and "signal" in value and isinstance(item, list):
            result[key] = [document for document in item if await may_read(document)]
        else:
            result[key] = await _readable(item, may_read, neighbours=False)
    return result
