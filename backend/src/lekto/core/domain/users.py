"""Users and roles. Passwords, TOTP and tokens belong to identity (`identity.py`), not to the
user; what is private about a person (aliases, birth date, e-mail, identifiers) to their
profile (`profiles.py`)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self

from lekto.core.domain.errors import ConflictError, ValidationError
from lekto.core.domain.ids import SpaceId, UserId, new_id
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.validation import require_name, require_utc

MAX_USERNAME = 150
"""Characters of a username; the REST schemas take their limit from here."""
MAX_DISPLAY_NAME = 150
"""Characters of a display name (and of an alias in the profile)."""


class Role(StrEnum):
    ADMIN = "admin"  # all rights: users, master data, every document and space (`permissions`)
    USER = "user"


@dataclass(kw_only=True)
class User:
    id: UserId
    username: str  # unique regardless of case
    role: Role
    created_at: datetime
    active: bool = True  # a deactivated user cannot sign in and reads nothing
    # How others see them ("Anna Busch"); public, unique regardless of case. None: the username.
    display_name: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        self.username = require_name(self.username, "username", max_length=MAX_USERNAME)
        self.created_at = require_utc(self.created_at, "created_at")
        self.display_name = display_name_of(self.display_name)

    @property
    def label(self) -> str:
        """What others read: the display name, else the username."""
        return self.display_name or self.username

    @classmethod
    def create(cls, *, username: str, role: Role, now: datetime) -> Self:
        return cls(id=UserId(new_id()), username=username, role=role, created_at=now)

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    @property
    def is_active_admin(self) -> bool:
        return self.active and self.is_admin


def display_name_of(value: str | None) -> str | None:
    """A display name as stored: trimmed, at most `MAX_DISPLAY_NAME` characters; None for none
    (an empty one is none)."""
    if value is None or not value.strip():
        return None
    return require_name(value, "display name", max_length=MAX_DISPLAY_NAME)


# --- deleting a user ----------------------------------------------------------------------------


class Settle(StrEnum):
    """What becomes of a space that stops deleting its user (Tobi, 22.10.2026)."""

    REMOVE = "remove"  # an empty space goes with the user
    MOVE_TO = "move_to"  # its documents move into another space, then it goes with the user
    EDITOR = "editor"  # another user edits it; it stays with its documents


@dataclass(frozen=True)
class BlockingSpace:
    """A space that stops deleting a user until the deletion settles it: their personal space
    while it holds documents, or a shared space they alone edit. `choices`: how it may be
    settled."""

    id: SpaceId
    name: str
    personal: bool
    documents: int
    choices: tuple[Settle, ...]


@dataclass(frozen=True)
class Settlement:
    """How a deletion settles one blocking space: `move_to` names the space its documents go
    into, `editor` the user who edits it from then on."""

    how: Settle
    move_to: SpaceId | None = None
    editor: UserId | None = None

    def __post_init__(self) -> None:
        if (self.how is Settle.MOVE_TO) != (self.move_to is not None):
            raise ValidationError("move_to: the space the documents move into, and only then")
        if (self.how is Settle.EDITOR) != (self.editor is not None):
            raise ValidationError("editor: the user who edits the space, and only then")


class UserDeletionBlockedError(ConflictError):
    """Deleting the user needs a decision on each of `spaces` (`Settlement`)."""

    def __init__(self, spaces: tuple[BlockingSpace, ...]) -> None:
        names = [space.name for space in spaces]
        super().__init__(because(ReasonCode.USER_DELETION_BLOCKED, spaces=names))
        self.spaces = spaces
