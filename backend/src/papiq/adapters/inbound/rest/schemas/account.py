"""Sign-in and the caller's own account: password, TOTP, sessions, API tokens, provider links."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr

from papiq.core.domain.identity import ApiToken, ExternalIdentity, LoginMethod, TokenScope
from papiq.core.domain.users import Role, User

Password = Annotated[SecretStr, Field(min_length=1, max_length=1024)]


Code = Annotated[str, Field(min_length=1, max_length=64)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"username": "alice", "password": "********", "code": "123456"}]
        },
    )

    username: str = Field(min_length=1, max_length=150, examples=["alice"])
    password: Password = Field(examples=["********"])
    code: str | None = Field(
        default=None, max_length=16, description="TOTP code, if the account has TOTP."
    )
    recovery_code: str | None = Field(
        default=None, max_length=64, description="Instead of `code`: a recovery code."
    )


class UserOut(BaseModel):
    """A user. Others than admins see only `id` and `username`."""

    id: UUID
    username: str = Field(examples=["alice"])
    role: Role | None = None
    active: bool | None = None
    created_at: datetime | None = None

    @classmethod
    def of(cls, user: User, *, full: bool = True) -> "UserOut":
        if not full:
            return cls(id=user.id, username=user.username)
        return cls(
            id=user.id,
            username=user.username,
            role=user.role,
            active=user.active,
            created_at=user.created_at,
        )


class LinkOut(BaseModel):
    """A link to an account at the identity provider."""

    issuer: str = Field(examples=["https://id.example.org/realms/home"])
    subject: str
    created_at: datetime

    @classmethod
    def of(cls, link: ExternalIdentity) -> "LinkOut":
        return cls(issuer=link.issuer, subject=link.subject, created_at=link.created_at)


class SessionOut(BaseModel):
    """A new session; its token is in the cookie only."""

    user: UserOut
    method: LoginMethod
    expires_at: datetime
    csrf_token: str = Field(
        description="Send as header `X-CSRF-Token` with every changing request.",
        examples=["3f5c0e…"],
    )


class Me(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user": {
                        "id": "01999d5e-1111-7c1e-b6a3-2f4d5e6f7a8b",
                        "username": "alice",
                        "role": "user",
                        "active": True,
                        "created_at": "2026-01-10T09:00:00Z",
                    },
                    "authenticated_with": "token",
                    "csrf_token": None,
                    "session_expires_at": None,
                    "token_scope": "read",
                    "has_password": True,
                    "totp_enabled": False,
                    "linked_accounts": [],
                }
            ]
        }
    )

    user: UserOut
    authenticated_with: Literal["session", "token"]
    csrf_token: str | None = Field(description="With a session: for `X-CSRF-Token`.")
    session_expires_at: datetime | None
    token_scope: TokenScope | None = Field(description="With an API token: its scope.")
    has_password: bool
    totp_enabled: bool
    linked_accounts: list[LinkOut]


class PasswordChange(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"current_password": "********", "new_password": "********", "revoke_tokens": False}
            ]
        },
    )

    current_password: Password
    new_password: Password = Field(description="12 to 256 characters, not the username.")
    revoke_tokens: bool = Field(
        default=False, description="Also revoke all API tokens. Other sessions end anyway."
    )


class SessionsEnded(BaseModel):
    ended: int


class TotpSetupOut(BaseModel):
    """Shown once. Confirm with a code to turn TOTP on."""

    secret: str = Field(examples=["JBSWY3DPEHPK3PXP"])
    otpauth_uri: str = Field(examples=["otpauth://totp/Papiq:alice?secret=JBSWY3DPEHPK3PXP"])


class CodeIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"code": "123456"}]},
    )

    code: Code = Field(description="A TOTP code; where noted, a recovery code works too.")


class RecoveryCodes(BaseModel):
    """Shown once; each works once instead of a TOTP code."""

    recovery_codes: list[str] = Field(examples=[["ABCD-EFGH-IJKL-MNOP"]])


class TokenCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"name": "scanner", "scope": "read_write", "expires_at": "2027-01-01T00:00:00Z"}
            ]
        },
    )

    name: str = Field(min_length=1, max_length=100, examples=["scanner"])
    scope: TokenScope
    expires_at: AwareDatetime | None = None


class TokenOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "01999d5e-6666-7c1e-b6a3-2f4d5e6f7a8b",
                    "name": "scanner",
                    "scope": "read_write",
                    "created_at": "2026-04-01T10:00:00Z",
                    "expires_at": "2027-01-01T00:00:00Z",
                    "last_used_at": "2026-04-02T07:30:00Z",
                }
            ]
        }
    )

    id: UUID
    name: str
    scope: TokenScope
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None

    @classmethod
    def of(cls, token: ApiToken) -> "TokenOut":
        return cls(
            id=token.id,
            name=token.name,
            scope=token.scope,
            created_at=token.created_at,
            expires_at=token.expires_at,
            last_used_at=token.last_used_at,
        )


class TokenCreated(TokenOut):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "01999d5e-6666-7c1e-b6a3-2f4d5e6f7a8b",
                    "name": "scanner",
                    "scope": "read_write",
                    "created_at": "2026-04-01T10:00:00Z",
                    "expires_at": "2027-01-01T00:00:00Z",
                    "last_used_at": None,
                    "token": "papiq_<token shown once>",
                }
            ]
        }
    )

    token: str = Field(
        description="The token itself; shown only now.", examples=["papiq_<token shown once>"]
    )


class OidcInfo(BaseModel):
    enabled: bool
    display_name: str | None = Field(examples=["Single sign-on"])


class AuthorizationUrl(BaseModel):
    authorization_url: str = Field(description="Send the browser there.")


class Removed(BaseModel):
    removed: int
