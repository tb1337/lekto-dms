"""Changing many documents at once: `POST /documents/bulk` and `GET /documents/bulk/{id}`."""

from uuid import UUID

from fastapi import APIRouter, Request, Response

from lekto.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.params import AllDocuments, Filter
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.bulk import BulkOperationOut, BulkRequest
from lekto.core.domain.bulk import MAX_DOCUMENTS, MAX_IDS
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import BulkOperationId, DocumentId
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.ports.repository import DocumentFilter
from lekto.core.ports.search_index import MAX_HITS
from lekto.core.services.bulk import Selection

router = APIRouter(prefix="/documents/bulk", tags=["documents"], dependencies=PROTECTED)


@router.post(
    "",
    status_code=202,
    summary="Change many documents at once",
    description=(
        "Does one action to the selected documents in the background; follow it at "
        f"`GET /documents/bulk/{{id}}`. The selection: `document_ids` (at most {MAX_IDS}), or "
        "every document the query parameters find, as `GET /documents` (at most "
        f"{MAX_DOCUMENTS}, more: 422) or with `q` in the body as `POST /documents/search` (the "
        f"hits it reaches, at most {MAX_HITS}); it is fixed now. Each document goes through the "
        "same change as one by hand, rights included: one the caller may not edit, one being "
        "processed (except to delete it) or one that changed meanwhile is skipped with the "
        "reason, one that is as the action wants it already stays as it is. A tag, contact, "
        "type, topic or space the action names that does not exist: 404. Admins act on "
        "every user's documents with `all_users` (others: 403)."
    ),
    response_model=BulkOperationOut,
    responses=problem_responses(401, 403, 404, 422, 503),
)
async def start_bulk(
    body: BulkRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    context: Context,
    filter: Filter,
    all_users: AllDocuments = False,
) -> BulkOperationOut:
    q = body.q
    if body.document_ids is not None and (q is not None or filter != DocumentFilter()):
        raise ValidationError(because(ReasonCode.BULK_IDS_AND_FILTER))
    operation = await context.bulk.start(
        user,
        Selection(
            ids=(
                None
                if body.document_ids is None
                else tuple(DocumentId(id) for id in body.document_ids)
            ),
            filter=filter,
            text=q,
            all_users=all_users,
        ),
        body.action.action(),
    )
    response.headers["Location"] = str(request.url_for("get_bulk", id=operation.id).path)
    return BulkOperationOut.of(operation)


@router.get(
    "/{id}",
    summary="Progress of a change of many documents",
    description="For the user who started it and admins.",
    response_model=BulkOperationOut,
    responses=problem_responses(401, 404, 422),
)
async def get_bulk(id: UUID, user: CurrentUser, context: Context) -> BulkOperationOut:
    return BulkOperationOut.of(await context.bulk.get(user, BulkOperationId(id)))
