"""Users, managed by admins."""

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lekto.adapters.inbound.problems import BlockingSpaceOut
from lekto.adapters.inbound.rest.schemas.account import LinkOut, Password, UserOut
from lekto.core.domain.ids import SpaceId, UserId
from lekto.core.domain.users import MAX_USERNAME, Role, Settle, Settlement


class UserCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"username": "bob", "role": "user", "password": "********"}]
        },
    )

    username: str = Field(min_length=1, max_length=MAX_USERNAME)
    role: Role = Role.USER
    password: Password | None = Field(
        default=None, description="Optional; 12 to 256 characters, not the username."
    )


class UserPatch(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"role": "admin", "active": True}]},
    )

    role: Role | None = None
    active: bool | None = Field(
        default=None, description="false ends the user's sessions and blocks their tokens."
    )


class PasswordReset(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"password": "********", "revoke_tokens": True}]},
    )

    password: Password
    revoke_tokens: bool = False


class AccountOut(UserOut):
    has_password: bool
    totp_enabled: bool
    linked_accounts: list[LinkOut]


class UserRemovalOut(BaseModel):
    """What stops deleting a user until the deletion settles it."""

    blocking_spaces: list[BlockingSpaceOut]


class SpaceSettlementIn(BaseModel):
    """How deleting a user settles one of the spaces that stop it."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "space_id": "01999d5e-8a7f-7c1e-b6a3-2f4d5e6f7a8b",
                    "move_to": "01999d5e-9b8a-7c1e-b6a3-2f4d5e6f7a8b",
                },
                {"space_id": "01999d5e-8a7f-7c1e-b6a3-2f4d5e6f7a8c", "remove": True},
            ]
        },
    )

    space_id: UUID
    remove: bool = Field(default=False, description="The empty space goes with the user.")
    move_to: UUID | None = Field(
        default=None,
        description="Its documents move into this space (as an admin moves them by hand), "
        "then the space goes with the user.",
    )
    editor: UUID | None = Field(
        default=None, description="This user edits the space from then on; it stays."
    )

    @model_validator(mode="after")
    def _one(self) -> Self:
        if sum([self.remove, self.move_to is not None, self.editor is not None]) != 1:
            raise ValueError("give exactly one of remove, move_to, editor")
        return self

    def settlement(self) -> Settlement:
        if self.move_to is not None:
            return Settlement(Settle.MOVE_TO, move_to=SpaceId(self.move_to))
        if self.editor is not None:
            return Settlement(Settle.EDITOR, editor=UserId(self.editor))
        return Settlement(Settle.REMOVE)


class UserRemovalIn(BaseModel):
    """The decisions on the spaces that stop deleting a user (`GET /users/{id}/removal`)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "spaces": [
                        {
                            "space_id": "01999d5e-8a7f-7c1e-b6a3-2f4d5e6f7a8b",
                            "move_to": "01999d5e-9b8a-7c1e-b6a3-2f4d5e6f7a8b",
                        },
                        {
                            "space_id": "01999d5e-8a7f-7c1e-b6a3-2f4d5e6f7a8c",
                            "editor": "01999d5e-1111-7c1e-b6a3-2f4d5e6f7a8b",
                        },
                    ]
                }
            ]
        },
    )

    spaces: list[SpaceSettlementIn] = Field(default_factory=list, description="Each space once.")

    @field_validator("spaces")
    @classmethod
    def _each_once(cls, spaces: list[SpaceSettlementIn]) -> list[SpaceSettlementIn]:
        if len({item.space_id for item in spaces}) != len(spaces):
            raise ValueError("each space once")
        return spaces
