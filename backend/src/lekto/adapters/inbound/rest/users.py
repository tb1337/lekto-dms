"""`/users`: accounts. Admins manage them; everyone reads the active users' names, to share
spaces with them."""

from uuid import UUID

from fastapi import APIRouter

from lekto.adapters.inbound.problems import blocking_space_out
from lekto.adapters.inbound.rest.auth import (
    PROTECTED,
    Authenticated,
    CurrentUser,
    SessionPrincipal,
)
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.params import ADMINS_ONLY, SESSION_ONLY_NOTE
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.account import LinkOut, Removed, UserOut
from lekto.adapters.inbound.rest.schemas.users import (
    AccountOut,
    PasswordReset,
    UserCreate,
    UserPatch,
    UserRemovalIn,
    UserRemovalOut,
)
from lekto.core.domain.ids import SpaceId, UserId
from lekto.core.services.users import Account

router = APIRouter(prefix="/users", tags=["users"], dependencies=PROTECTED)


def _account(account: Account, personal_space: SpaceId | None) -> AccountOut:
    return AccountOut(
        **UserOut.of(account.user, personal_space=personal_space).model_dump(),
        has_password=account.has_password,
        totp_enabled=account.totp_enabled,
        linked_accounts=[LinkOut.of(link) for link in account.external_identities],
    )


@router.get(
    "",
    summary="List users",
    description=(
        "Admins see all users with role and state; others see the active users' id, name and "
        "personal space (to hand documents over to them)."
    ),
    response_model=list[UserOut],
    response_model_exclude_none=True,
    responses=problem_responses(401),
)
async def list_users(principal: Authenticated, context: Context) -> list[UserOut]:
    full = principal.user.is_admin
    users = await context.users.list_users(principal.id)
    personal = await context.users.personal_spaces(principal.id)
    return [UserOut.of(user, full=full, personal_space=personal.get(user.id)) for user in users]


@router.post(
    "",
    status_code=201,
    summary="Create a user",
    description=(
        ADMINS_ONLY + " Creates the user's personal space, too. A user with the role "
        "`user` and no password can be created with an admin's API token (`read_write`), e.g. "
        "by a migration; a password or the role `admin` needs a session, as for `/auth/*`."
    ),
    response_model=UserOut,
    responses=problem_responses(401, 403, 409, 422),
)
async def create_user(body: UserCreate, admin: Authenticated, context: Context) -> UserOut:
    password = None if body.password is None else body.password.get_secret_value()
    created = await context.users.create_user(
        admin.id, body.username, body.role, password, session=admin.session is not None
    )
    return UserOut.of(created)


@router.get(
    "/{id}",
    summary="A user",
    description=(
        "Admins see the account with its sign-in methods; others only active users' id, name and "
        "personal space."
    ),
    response_model=AccountOut | UserOut,
    response_model_exclude_none=True,
    responses=problem_responses(401, 404, 422),
)
async def get_user(id: UUID, principal: Authenticated, context: Context) -> AccountOut | UserOut:
    personal = (await context.users.personal_spaces(principal.id)).get(UserId(id))
    if principal.user.is_admin:
        return _account(await context.users.account(principal.id, UserId(id)), personal)
    found = await context.users.get(principal.id, UserId(id))
    return UserOut.of(found, full=False, personal_space=personal)


@router.patch(
    "/{id}",
    summary="Change role or state",
    description=(
        ADMINS_ONLY + " Deactivating ends the user's sessions and blocks their API tokens. "
        "The last active admin stays an active admin (409). Changing a role, or deactivating an "
        "admin, needs a session, as for `/auth/*`: an API token only deactivates and "
        "reactivates users (e.g. a migration)."
    ),
    response_model=UserOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def update_user(id: UUID, body: UserPatch, admin: Authenticated, context: Context) -> UserOut:
    changed = await context.users.update(
        admin.id, UserId(id), role=body.role, active=body.active, session=admin.session is not None
    )
    return UserOut.of(changed)


@router.post(
    "/{id}/password",
    status_code=204,
    summary="Reset a user's password",
    description=ADMINS_ONLY
    + " Ends all the user's sessions; API tokens stay unless `revoke_tokens`. Not for the "
    "own account (403): that is `POST /auth/password`." + SESSION_ONLY_NOTE,
    responses=problem_responses(401, 403, 404, 422),
)
async def reset_password(
    id: UUID, body: PasswordReset, admin: SessionPrincipal, context: Context
) -> None:
    await context.users.reset_password(
        admin.id, UserId(id), body.password.get_secret_value(), revoke_tokens=body.revoke_tokens
    )


@router.delete(
    "/{id}/totp",
    status_code=204,
    summary="Turn a user's TOTP off",
    description=ADMINS_ONLY
    + " For a user who lost authenticator and recovery codes. Not for the own account (403): "
    "that is `POST /auth/totp/disable`." + SESSION_ONLY_NOTE,
    responses=problem_responses(401, 403, 404, 422),
)
async def disable_totp(id: UUID, admin: SessionPrincipal, context: Context) -> None:
    await context.users.disable_totp(admin.id, UserId(id))


@router.delete(
    "/{id}/oidc",
    summary="Remove a user's links to the identity provider",
    description=ADMINS_ONLY + SESSION_ONLY_NOTE,
    response_model=Removed,
    responses=problem_responses(401, 403, 404, 422),
)
async def unlink(id: UUID, admin: SessionPrincipal, context: Context) -> Removed:
    return Removed(removed=await context.users.unlink_external_identities(admin.id, UserId(id)))


@router.get(
    "/{id}/removal",
    summary="What stops deleting a user",
    description=(
        ADMINS_ONLY + " The spaces deleting the user must settle (Tobi, 22.10.2026): their "
        "personal space while it holds documents, and each shared space they alone edit. "
        "Empty: nothing stops it."
    ),
    response_model=UserRemovalOut,
    responses=problem_responses(401, 403, 404, 422),
)
async def removal(id: UUID, user: CurrentUser, context: Context) -> UserRemovalOut:
    spaces = await context.users.removal(user, UserId(id))
    return UserRemovalOut(blocking_spaces=[blocking_space_out(item) for item in spaces])


@router.delete(
    "/{id}",
    status_code=204,
    summary="Delete a user",
    description=(
        ADMINS_ONLY + " The body settles each space that stops it (`GET /users/{id}/removal`; "
        "one left open: 409 with `blocking_spaces`): the personal space's documents move into "
        "another space (`move_to`); a shared space the user alone edits goes if empty "
        "(`remove`), moves its documents and goes (`move_to`), or gets another editor "
        "(`editor`). Documents move as an admin moves them by hand. All or nothing. Removes "
        "the personal space with its rules, the user's memberships and sign-in data; the "
        "documents they uploaded stay, without uploader."
    ),
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def delete_user(
    id: UUID, user: CurrentUser, context: Context, body: UserRemovalIn | None = None
) -> None:
    settle = (
        {} if body is None else {SpaceId(item.space_id): item.settlement() for item in body.spaces}
    )
    await context.users.delete_user(user, UserId(id), settle)
