"""Search: `POST /documents/search` (words and meaning in one call) and `POST /search/reindex`."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from lekto.adapters.inbound.rest.auth import PROTECTED, READS, CurrentUser
from lekto.adapters.inbound.rest.context import Indexing, Search
from lekto.adapters.inbound.rest.documents import DocumentSort
from lekto.adapters.inbound.rest.params import ADMINS_ONLY, AllDocuments, Filter
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.documents import ListedDocument
from lekto.adapters.inbound.rest.schemas.search import (
    IndexCheckOut,
    SearchIn,
    SearchResultItem,
    SearchResultPage,
    SearchStatusOut,
    SnippetSegment,
)
from lekto.adapters.inbound.schemas import ReasonOut
from lekto.core.ports.search_index import MAX_HITS, MAX_LIMIT, SEARCH_PAGE

router = APIRouter(tags=["search"], dependencies=PROTECTED)


@router.post(
    "/documents/search",
    openapi_extra=READS,
    summary="Search documents",
    description=(
        "Full text and, if the installation has embeddings, meaning in one call. Finds the "
        "documents within the caller's reach, the same ones as `GET /documents` lists, with the "
        "same filters (they combine; `tag_id`, `contact_group_id`, `document_type_group_id`, "
        "`topic_id` and `lane` may repeat, a topic takes the topics below it); admins search every "
        "document with `all_users` (others: 403). Each hit is checked "
        "against the permissions once more before it is returned. The index follows the "
        "documents a moment later, so a new document may take a few seconds to turn up. "
        f"Pages are by `offset`; at most {MAX_HITS} hits can be reached. `sort`: by relevance (the "
        "default), or by a key as in `GET /documents`, relevance breaking ties. The words go "
        "in the body, so that they stay out of addresses and logs; the filters and the rest "
        "stay query parameters."
    ),
    response_model=SearchResultPage,
    responses=problem_responses(401, 403, 422, 503),
)
async def search_documents(
    body: SearchIn,
    user: CurrentUser,
    search: Search,
    filter: Filter,
    sort: Annotated[
        DocumentSort | Literal["relevance"], Query(description="`relevance` or a key.")
    ] = "relevance",
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = SEARCH_PAGE,
    offset: Annotated[int, Query(ge=0, le=MAX_HITS)] = 0,
    semantic_ratio: Annotated[
        float | None,
        Query(
            ge=0,
            le=1,
            description="Weight of the meaning against the words: 0 words only, 1 meaning "
            "only. Default: the installation's setting.",
        ),
    ] = None,
    all_users: AllDocuments = False,
) -> SearchResultPage:
    page = await search.search(
        user,
        body.q,
        filter,
        offset=offset,
        limit=limit,
        semantic_ratio=semantic_ratio,
        order=None if sort == "relevance" else sort.order,
        all_users=all_users,
    )
    return SearchResultPage(
        items=[
            SearchResultItem(
                document=ListedDocument.listed(item.document, item.access, item.in_inbox),
                score=item.score,
                snippet=[SnippetSegment(text=s.text, match=s.match) for s in item.snippet],
            )
            for item in page.items
        ],
        estimated_total=page.estimated_total,
        next_offset=page.next_offset,
        semantic=page.semantic,
        mode=page.mode,
        reason=None if page.reason is None else ReasonOut.of(page.reason),
        meaning_pending=page.meaning_pending,
    )


@router.post(
    "/documents/search/warm",
    status_code=204,
    summary="Get the search ready",
    description=(
        "Has the model of the embeddings loaded before a search needs it, e.g. as soon as a "
        "person starts typing: one embedding in the background, at most once a minute. "
        "Answers at once."
    ),
    responses=problem_responses(401, 503),
)
async def warm_search(user: CurrentUser, search: Search) -> None:
    await search.warm(user)


@router.post(
    "/search/reindex",
    status_code=202,
    summary="Rebuild the search index",
    description=(
        ADMINS_ONLY + " Builds a new index from the database and the stored files next to the "
        "active one and swaps it in when it is complete; the search keeps working meanwhile. "
        "Runs in the background and may take long; a rebuild that is queued or running is not "
        "queued twice."
    ),
    response_class=Response,
    responses={202: {"description": "Queued."}, **problem_responses(401, 403, 503)},
)
async def reindex(user: CurrentUser, indexing: Indexing) -> Response:
    await indexing.request_rebuild(user)
    return Response(status_code=202)


@router.get(
    "/search/status",
    summary="The state of the search index",
    description=(
        "How many documents the database and the index hold, how many have vectors, the index "
        "jobs running and waiting with an estimate of when they are through, how long index "
        "jobs ran with and without embedding, and the embedding model. Every user. 503 "
        "without a search index or when it cannot be reached."
    ),
    response_model=SearchStatusOut,
    responses=problem_responses(401, 503),
)
async def search_status(user: CurrentUser, indexing: Indexing) -> SearchStatusOut:
    return SearchStatusOut.of(await indexing.status(user))


@router.post(
    "/search/check",
    summary="Check the search index",
    description=(
        ADMINS_ONLY + " Compares every document in the database with the index and counts "
        "what is current, missing, stale and left over; nothing is queued or removed (the "
        "next reconciliation does that). Reads the whole index: seconds for some thousand "
        "documents."
    ),
    response_model=IndexCheckOut,
    responses=problem_responses(401, 403, 503),
)
async def check_index(user: CurrentUser, indexing: Indexing) -> IndexCheckOut:
    return IndexCheckOut.of(await indexing.check(user))
