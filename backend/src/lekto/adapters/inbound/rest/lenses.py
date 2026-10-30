"""`/lenses`: a user's saved looks at the documents."""

from uuid import UUID

from fastapi import APIRouter

from lekto.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.lenses import LensCreate, LensOrder, LensOut, LensPatch
from lekto.core.domain.ids import FieldId, LensId
from lekto.core.domain.lenses import UNSET, LensChanges

router = APIRouter(prefix="/lenses", tags=["lenses"], dependencies=PROTECTED)

WHO = "Only its owner sees and changes a lens; other users' lenses are not found (404)."
GONE = (
    "Contacts, types, tags, spaces and fields a lens names that were deleted are left out; a "
    "sort or grouping that needed a deleted field falls back to the default."
)


@router.get(
    "",
    summary="List lenses",
    description="The caller's lenses in their order. " + GONE,
    response_model=list[LensOut],
    responses=problem_responses(401),
)
async def list_lenses(user: CurrentUser, context: Context) -> list[LensOut]:
    return [LensOut.of(lens, context.refs) for lens in await context.lenses.list_lenses(user)]


@router.post(
    "",
    status_code=201,
    summary="Create a lens",
    description=(
        "A saved look at the documents: filters, words, sort, grouping, layout, the fields "
        "its cards show and the date field that is their deadline; it goes after the caller's "
        "other lenses. The card fields must exist, the deadline must be a date field, the sort "
        "field one of type date, period, number or amount (422). 409: the caller has a lens of "
        "that name (regardless of case) or 100 lenses."
    ),
    response_model=LensOut,
    responses=problem_responses(401, 409, 422),
)
async def create_lens(body: LensCreate, user: CurrentUser, context: Context) -> LensOut:
    changes = LensChanges(
        filter=body.filter.domain(context.refs),
        query=body.query,
        sort=body.sort,
        sort_field_id=None if body.sort_field_id is None else FieldId(body.sort_field_id),
        grouping=body.grouping,
        layout=body.layout,
        card_field_ids=tuple(FieldId(id) for id in body.card_field_ids),
        due_field_id=None if body.due_field_id is None else FieldId(body.due_field_id),
    )
    return LensOut.of(await context.lenses.create(user, body.name, changes), context.refs)


@router.put(
    "/order",
    summary="Order the lenses",
    description="`ids` names each of the caller's lenses once (422 otherwise).",
    response_model=list[LensOut],
    responses=problem_responses(401, 409, 422),
)
async def order_lenses(body: LensOrder, user: CurrentUser, context: Context) -> list[LensOut]:
    lenses = await context.lenses.reorder(user, [LensId(id) for id in body.ids])
    return [LensOut.of(lens, context.refs) for lens in lenses]


@router.get(
    "/{id}",
    summary="A lens",
    description=f"{WHO} {GONE}",
    response_model=LensOut,
    responses=problem_responses(401, 404, 422),
)
async def get_lens(id: UUID, user: CurrentUser, context: Context) -> LensOut:
    return LensOut.of(await context.lenses.get(user, LensId(id)), context.refs)


@router.patch(
    "/{id}",
    summary="Change a lens",
    description=f"Checks as when creating. {WHO}",
    response_model=LensOut,
    responses=problem_responses(401, 404, 409, 422),
)
async def update_lens(id: UUID, body: LensPatch, user: CurrentUser, context: Context) -> LensOut:
    given = body.model_fields_set

    def field(value: UUID | None) -> FieldId | None:
        return None if value is None else FieldId(value)

    changes = LensChanges(
        name=body.name if body.name is not None else UNSET,
        filter=body.filter.domain(context.refs) if body.filter is not None else UNSET,
        query=body.query if "query" in given else UNSET,
        sort=body.sort if "sort" in given else UNSET,
        sort_field_id=field(body.sort_field_id) if "sort_field_id" in given else UNSET,
        grouping=body.grouping if body.grouping is not None else UNSET,
        layout=body.layout if body.layout is not None else UNSET,
        card_field_ids=(
            tuple(FieldId(id) for id in body.card_field_ids)
            if body.card_field_ids is not None
            else UNSET
        ),
        due_field_id=field(body.due_field_id) if "due_field_id" in given else UNSET,
    )
    return LensOut.of(await context.lenses.update(user, LensId(id), changes), context.refs)


@router.delete(
    "/{id}",
    status_code=204,
    summary="Delete a lens",
    description=WHO,
    responses=problem_responses(401, 404, 422),
)
async def delete_lens(id: UUID, user: CurrentUser, context: Context) -> None:
    await context.lenses.delete(user, LensId(id))
