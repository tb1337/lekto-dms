"""Permission rules. Rights hang on spaces, never on single documents.

- A document lies in exactly one space. The members of the space read it (`read`, once it is
  green) or edit it (`edit`, in every lane and in processing). Nobody has rights on a document
  for having uploaded it.
- Editing covers changing the metadata, confirming, deleting, retrying, reprocessing, reading
  the processing log, marking it seen and moving it.
- Filing into a space needs edit rights on it. Moving a document needs edit rights on its
  space and on the target, or the target is another user's personal space (handing it over).
- Managing a space (rename, members, delete) is up to its editors; the members of a personal
  space are chosen by its user only.
- Admins have every right and see everything (Tobi, 08.10.2026): they edit every document in
  every space and manage every space, and manage users and master data. Only admins do the
  latter.
- A deactivated user has no rights at all, a deactivated admin included.

What a user reaches without the admin's rights (`reach_access`, `in_reach`, `Reach`) is what
lists show by default and what webhooks report: every document in the spaces they edit, and the
green ones in the spaces they read.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from lekto.core.domain.documents import Document
from lekto.core.domain.ids import SpaceId, UserId
from lekto.core.domain.pipeline import Lane
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import User


class Placed(Protocol):
    """Where a document lies and how far it got (a `Document`, an `IndexDocument`)."""

    @property
    def space_id(self) -> SpaceId: ...

    @property
    def lane(self) -> Lane | None: ...


def within_reach(edits: Iterable[SpaceId], reads: Iterable[SpaceId], document: Placed) -> bool:
    """Whether `document` is within the reach of a user who edits `edits` and reads `reads`:
    every document in the former, the green ones in the latter. Whether the user is active the
    services check (`load_actor`)."""
    return document.space_id in set(edits) or (
        document.lane is Lane.GREEN and document.space_id in set(reads)
    )


@dataclass(frozen=True)
class Reach:
    """The spaces a user is a member of, by role (`within_reach`): `reads` holds those they
    only read."""

    edits: frozenset[SpaceId]
    reads: frozenset[SpaceId]

    @classmethod
    def of(cls, user: UserId, spaces: Iterable[Space]) -> "Reach":
        edits: set[SpaceId] = set()
        reads: set[SpaceId] = set()
        for space in spaces:
            role = space.role_of(user)
            if role is SpaceRole.EDIT:
                edits.add(space.id)
            elif role is SpaceRole.READ:
                reads.add(space.id)
        return cls(frozenset(edits), frozenset(reads))

    @property
    def spaces(self) -> frozenset[SpaceId]:
        return self.edits | self.reads

    def allows(self, document: Placed) -> bool:
        return within_reach(self.edits, self.reads, document)


def space_role(user: User, space: Space) -> SpaceRole | None:
    """The user's role in the space; an active admin edits every space."""
    if user.is_active_admin:
        return SpaceRole.EDIT
    return member_role(user, space)


def member_role(user: User, space: Space) -> SpaceRole | None:
    """As `space_role`, without the rights of an admin."""
    if not user.active:
        return None
    return space.role_of(user.id)


def document_access(user: User, document: Document, space: Space) -> SpaceRole | None:
    """Access of `user` to `document`, which lies in `space`."""
    if document.space_id != space.id:
        raise ValueError(f"document {document.id} is not in space {space.id}")
    if user.is_active_admin:
        return SpaceRole.EDIT
    return reach_access(user, document, space)


def reach_access(user: User, document: Document, space: Space) -> SpaceRole | None:
    """As `document_access`, without the rights of an admin."""
    if document.space_id != space.id:
        raise ValueError(f"document {document.id} is not in space {space.id}")
    role = member_role(user, space)
    if role is SpaceRole.EDIT:
        return role
    if role is SpaceRole.READ and document.lane is Lane.GREEN:
        return role
    return None


def can_read_document(user: User, document: Document, space: Space) -> bool:
    return document_access(user, document, space) is not None


def in_reach(user: User, document: Document, space: Space) -> bool:
    """`can_read_document` without the rights of an admin."""
    return reach_access(user, document, space) is not None


def can_edit_document(user: User, document: Document, space: Space) -> bool:
    """Change, confirm, delete, retry and reprocess the document, read its processing log."""
    access = document_access(user, document, space)
    return access is not None and access.can_edit


def can_file_into(user: User, space: Space) -> bool:
    role = space_role(user, space)
    return role is not None and role.can_edit


def can_hand_over(user: User, space: Space) -> bool:
    """Whether `user` may put a document they edit into `space` without editing it: it is
    another user's personal space."""
    return user.active and space.personal_of is not None and space.personal_of != user.id


def can_move_document(user: User, document: Document, source: Space, target: Space) -> bool:
    """Move `document` out of `source`, the space it lies in, into `target`."""
    if not can_edit_document(user, document, source):
        return False
    return can_file_into(user, target) or can_hand_over(user, target)


def can_manage_space(user: User, space: Space) -> bool:
    """Rename and delete a space, and choose the members of a shared one."""
    role = space_role(user, space)
    return role is not None and role.can_edit


def can_choose_members(user: User, space: Space) -> bool:
    """Add, change and remove members: the space's editors; of a personal space, its user."""
    if space.personal_of is not None:
        return user.active and (space.personal_of == user.id or user.is_admin)
    return can_manage_space(user, space)
