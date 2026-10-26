"""`/documents/{id}/relations`: the relations between documents (issue #145)."""

from uuid import UUID

from fastapi import APIRouter

from lekto.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.relations import RelateIn, RelationsOut
from lekto.core.domain.ids import DocumentId

router = APIRouter(prefix="/documents", tags=["relations"], dependencies=PROTECTED)

WHO = (
    "A relation points from the newer document to the older one (by their document dates, else "
    "when they came in). Only who reads both documents sees it; who edits the newer and reads "
    "the older sets, accepts or removes it (403 otherwise)."
)


@router.get(
    "/{id}/relations",
    summary="The relations of a document",
    description="Needs read access. The relations whose other end the caller reads. " + WHO,
    response_model=RelationsOut,
    responses=problem_responses(401, 404, 422),
)
async def relations(id: UUID, user: CurrentUser, context: Context) -> RelationsOut:
    return RelationsOut.of(await context.relations.relations(user, DocumentId(id)))


@router.post(
    "/{id}/relations",
    summary="Relate a document with another",
    description=(
        "Sets the relation between the two documents, or accepts Lekto's suggestion of it. "
        + WHO
        + " 409 if it is set already or both are the same document."
    ),
    response_model=RelationsOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def relate(id: UUID, body: RelateIn, user: CurrentUser, context: Context) -> RelationsOut:
    await context.relations.relate(user, DocumentId(id), DocumentId(body.document_id))
    return RelationsOut.of(await context.relations.relations(user, DocumentId(id)))


@router.delete(
    "/{id}/relations/{other_id}",
    summary="Remove a relation",
    description=(
        "Removes the relation between the two documents, or rejects Lekto's suggestion of it: "
        "one Lekto made is kept as rejected, so it is not suggested again. "
        + WHO
        + " 404 if they are not related."
    ),
    response_model=RelationsOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def unrelate(id: UUID, other_id: UUID, user: CurrentUser, context: Context) -> RelationsOut:
    await context.relations.unrelate(user, DocumentId(id), DocumentId(other_id))
    return RelationsOut.of(await context.relations.relations(user, DocumentId(id)))
