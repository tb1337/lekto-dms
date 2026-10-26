"""`/documents/stream`: the documents a filter finds, in lanes (issue #145)."""

from fastapi import APIRouter

from lekto.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.params import AllDocuments, Filter
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.stream import StreamOut

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=PROTECTED)


@router.get(
    "/stream",
    summary="The documents in a stream",
    description=(
        "The documents the filters of `GET /documents` find among those the caller reads "
        "(with `all_users`, an admin's, every user's), in lanes: a series (one contact and "
        "type, and one contract or customer number, at a steady interval) with the relation "
        "target its documents refer to at its start and the document it expects next; branches "
        "(documents that refer to one of a series or to its target, with the chain of theirs); "
        "chains of documents related only among themselves; and the rest in one lane. At most "
        "the 500 newest documents (`truncated`); beyond 24 lanes of series and chains the rest "
        "come folded."
    ),
    response_model=StreamOut,
    responses=problem_responses(401, 403, 422),
)
async def stream(
    user: CurrentUser, context: Context, filter: Filter, all_users: AllDocuments = False
) -> StreamOut:
    return StreamOut.of(await context.stream.stream(user, filter, all_users=all_users))
