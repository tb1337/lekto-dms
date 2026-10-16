"""Loading entities together with the caller's rights."""

from dataclasses import replace

from papiq.core.domain.documents import Document, DocumentChanges, Unset
from papiq.core.domain.errors import (
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from papiq.core.domain.ids import DocumentId, SpaceId, UserId
from papiq.core.domain.master_data import TagScope
from papiq.core.domain.permissions import (
    can_file_into,
    can_read_document,
    can_write_document,
    space_access,
)
from papiq.core.domain.pipeline import space_chooser
from papiq.core.domain.spaces import Space
from papiq.core.domain.tag_tree import TagTree
from papiq.core.domain.users import User
from papiq.core.ports import UnitOfWork


async def load_actor(uow: UnitOfWork, actor: UserId) -> User:
    """The caller; AuthenticationError if the account is gone or deactivated (it may have
    changed since the request was authenticated)."""
    user = await uow.users.find(actor)
    if user is None or not user.active:
        raise AuthenticationError("authentication is required")
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
    document, space = await readable_document(uow, user, id)
    if not can_write_document(user, document, space):
        raise PermissionDeniedError(f"no write access to document {id}")
    return document, space


async def visible_space(uow: UnitOfWork, user: User, id: SpaceId) -> Space:
    space = await uow.spaces.find(id)
    if space is None or space_access(user, space) is None:
        raise NotFoundError("space", id)
    return space


async def may_file(uow: UnitOfWork, document: Document, space: Space) -> bool:
    """Whether filing may put the document into `space`: its owner may write to the space, or
    an active admin put the document there by hand (admins file into any space)."""
    owner = await uow.users.get(document.owner_id)
    if can_file_into(owner, space):
        return True
    chooser = space_chooser(await uow.processing_log.list_for(document.id), space.id)
    if chooser is None:
        return False
    user = await uow.users.find(UserId(chooser))
    return user is not None and user.is_active_admin


async def checked_changes(uow: UnitOfWork, changes: DocumentChanges) -> DocumentChanges:
    """The change as it is applied: its tags normalised (a child and its parent set together
    leave the child, `TagTree.normalise`). NotFoundError if a contact, type or tag it refers
    to does not exist, ValidationError for a tag that does not describe documents (a group)."""
    if not isinstance(changes.contact_id, Unset) and changes.contact_id is not None:
        await uow.contacts.get(changes.contact_id)
    if not isinstance(changes.document_type_id, Unset) and changes.document_type_id is not None:
        await uow.document_types.get(changes.document_type_id)
    if isinstance(changes.tag_ids, Unset):
        return changes
    tree = TagTree.of(await uow.tags.list_all())
    for id in changes.tag_ids:
        tag = tree.get(id)
        if tag.scope is not TagScope.DOCUMENT:
            raise ValidationError(f"'{tag.name}' is a {tag.scope} group, not a document tag")
    return replace(changes, tag_ids=tree.normalise(changes.tag_ids))
