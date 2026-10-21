"""`/spaces`: the spaces the caller is a member of (every space for admins), and their
members."""

from uuid import UUID

from fastapi import APIRouter

from lekto.adapters.inbound.rest.auth import PROTECTED, Authenticated
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.common import NameIn
from lekto.adapters.inbound.rest.schemas.spaces import MemberIn, SpaceCreate, SpaceOut
from lekto.core.domain.ids import SpaceId, UserId
from lekto.core.domain.sorting import sort_key

router = APIRouter(prefix="/spaces", tags=["spaces"], dependencies=PROTECTED)

EDITORS = "Editors of the space and admins."


@router.get(
    "",
    summary="List spaces",
    description=(
        "The spaces the caller is a member of, their personal space first among them by its "
        "`personal_of`; every space for admins."
    ),
    response_model=list[SpaceOut],
    responses=problem_responses(401),
)
async def list_spaces(principal: Authenticated, context: Context) -> list[SpaceOut]:
    spaces = await context.spaces.list_spaces(principal.id)
    return [SpaceOut.of(d, principal.user) for d in sorted(spaces, key=lambda d: sort_key(d.name))]


@router.post(
    "",
    status_code=201,
    summary="Create a space",
    description=(
        "Names of the spaces that are nobody's personal one are unique regardless of case "
        "(409). The caller edits the space; `members` adds active users (an unknown or "
        "deactivated user: 404). An admin may give the members alone, one of whom edits (422 "
        "otherwise)."
    ),
    response_model=SpaceOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def create_space(body: SpaceCreate, principal: Authenticated, context: Context) -> SpaceOut:
    members = (
        None
        if body.members is None
        else {UserId(member.user_id): member.role for member in body.members}
    )
    space = await context.spaces.create(principal.id, body.name, members=members)
    return SpaceOut.of(space, principal.user)


@router.get(
    "/{id}",
    summary="A space",
    response_model=SpaceOut,
    responses=problem_responses(401, 404, 422),
)
async def get_space(id: UUID, principal: Authenticated, context: Context) -> SpaceOut:
    return SpaceOut.of(await context.spaces.get(principal.id, SpaceId(id)), principal.user)


@router.patch(
    "/{id}",
    summary="Rename a space",
    description=EDITORS + " Not a personal space (422).",
    response_model=SpaceOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def rename_space(
    id: UUID, body: NameIn, principal: Authenticated, context: Context
) -> SpaceOut:
    return SpaceOut.of(
        await context.spaces.rename(principal.id, SpaceId(id), body.name), principal.user
    )


@router.delete(
    "/{id}",
    status_code=204,
    summary="Delete a space",
    description=EDITORS
    + " Not a personal space, and only while it is empty (409). Its rules go with it; other "
    "rules that file into it are switched off.",
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def delete_space(id: UUID, principal: Authenticated, context: Context) -> None:
    await context.spaces.delete(principal.id, SpaceId(id))


@router.put(
    "/{id}/members/{user_id}",
    summary="Add a member or change their role",
    description=(
        EDITORS + " The members of a personal space are chosen by its user and admins. The "
        "user of a personal space always edits it, and a space keeps one editor (422); an "
        "unknown or deactivated user is not found (404). Readers see the green documents, "
        "editors every document."
    ),
    response_model=SpaceOut,
    responses=problem_responses(401, 403, 404, 422),
)
async def set_member(
    id: UUID, user_id: UUID, body: MemberIn, principal: Authenticated, context: Context
) -> SpaceOut:
    space = await context.spaces.set_member(principal.id, SpaceId(id), UserId(user_id), body.role)
    return SpaceOut.of(space, principal.user)


@router.delete(
    "/{id}/members/{user_id}",
    summary="Remove a member",
    description=(
        EDITORS + " As adding one. The user of a personal space stays, and a space keeps one "
        "editor (422)."
    ),
    response_model=SpaceOut,
    responses=problem_responses(401, 403, 404, 422),
)
async def remove_member(
    id: UUID, user_id: UUID, principal: Authenticated, context: Context
) -> SpaceOut:
    return SpaceOut.of(
        await context.spaces.remove_member(principal.id, SpaceId(id), UserId(user_id)),
        principal.user,
    )
