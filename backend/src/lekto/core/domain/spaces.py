"""Spaces: where documents lie, and the unit of permissions. Rights hang on spaces, never on
documents: the members of a space read (`read`) or edit (`edit`) what lies in it."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Self

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import SpaceId, UserId, new_id
from lekto.core.domain.master_data import checked_description
from lekto.core.domain.validation import require_name, require_utc

PERSONAL_SPACE_NAME = "Personal"
"""The stored name of every personal space; it is shown by its user (`Space.personal_of`)."""


class SpaceRole(StrEnum):
    READ = "read"  # green documents
    EDIT = "edit"  # every document in every lane; change, confirm, move, delete; the space

    @property
    def can_edit(self) -> bool:
        return self is SpaceRole.EDIT


@dataclass(kw_only=True)
class Space:
    """A space with its members and their roles.

    Every user has exactly one personal space (`personal_of`): what they upload lands there,
    they are always an editor of it, and only they (or an admin) choose its other members; it
    can be shared, but neither renamed nor deleted. Every other space keeps at least one
    editor, and its name is unique regardless of case among them. The description tells the
    language model what belongs in the space (`propose-5`); its editors write it, in a personal
    space its user.
    """

    id: SpaceId
    name: str
    personal_of: UserId | None = None
    members: dict[UserId, SpaceRole] = field(default_factory=dict)
    description: str | None = None
    created_at: datetime
    version: int = 1

    def __post_init__(self) -> None:
        self.name = require_name(self.name, "space name")
        self.description = checked_description(self.description)
        self.created_at = require_utc(self.created_at, "created_at")
        self._check_members(self.members)

    @classmethod
    def create(
        cls,
        *,
        name: str,
        members: Mapping[UserId, SpaceRole],
        now: datetime,
        description: str | None = None,
    ) -> Self:
        """A space shared by `members` (at least one editor)."""
        return cls(
            id=SpaceId(new_id()),
            name=name,
            members=dict(members),
            description=description,
            created_at=now,
        )

    @classmethod
    def create_personal(cls, *, user: UserId, now: datetime) -> Self:
        return cls(
            id=SpaceId(new_id()),
            name=PERSONAL_SPACE_NAME,
            personal_of=user,
            members={user: SpaceRole.EDIT},
            created_at=now,
        )

    @property
    def is_personal(self) -> bool:
        return self.personal_of is not None

    @property
    def editors(self) -> frozenset[UserId]:
        return frozenset(user for user, role in self.members.items() if role.can_edit)

    def role_of(self, user: UserId) -> SpaceRole | None:
        return self.members.get(user)

    def rename(self, name: str) -> None:
        if self.is_personal:
            raise ValidationError("a personal space keeps its name")
        self.name = require_name(name, "space name")

    def describe(self, description: str | None) -> None:
        """None or empty removes the description."""
        self.description = checked_description(description)

    def set_member(self, user: UserId, role: SpaceRole) -> None:
        members = {**self.members, user: role}
        self._check_members(members)
        self.members = members

    def remove_member(self, user: UserId) -> None:
        members = {member: role for member, role in self.members.items() if member != user}
        self._check_members(members)
        self.members = members

    def widens(self, target: "Space") -> bool:
        """Whether moving a document from this space into `target` shows it to someone who
        cannot read it here: `target` has a member this space lacks."""
        return any(user not in self.members for user in target.members)

    def _check_members(self, members: Mapping[UserId, SpaceRole]) -> None:
        if self.personal_of is not None:
            if members.get(self.personal_of) is not SpaceRole.EDIT:
                raise ValidationError("the user of a personal space always edits it")
        elif not any(role.can_edit for role in members.values()):
            raise ValidationError("a space keeps at least one editor")
