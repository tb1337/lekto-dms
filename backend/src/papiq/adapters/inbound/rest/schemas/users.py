"""Users, managed by admins."""

from pydantic import BaseModel, ConfigDict, Field

from papiq.adapters.inbound.rest.schemas.account import LinkOut, Password, UserOut
from papiq.core.domain.users import MAX_USERNAME, Role


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
