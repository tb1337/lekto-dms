"""`GET /pipeline`: the graph of nodes a document goes through; `POST /pipeline/reparse`,
`/relate`, `/render-pages`, `/read-facts`: the maintenance over every document."""

from fastapi import APIRouter

from lekto.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.params import ADMINS_ONLY
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.pipeline import (
    GraphNodeOut,
    PipelineOut,
    QueuedOut,
    ReparseOut,
    VisionOut,
)
from lekto.core.domain.pipeline import NODES

router = APIRouter(tags=["pipeline"], dependencies=PROTECTED)


@router.get(
    "/pipeline",
    summary="The processing graph",
    description=(
        "The nodes a document goes through and what each one needs, in graph order: every "
        "node after the nodes it needs. Nodes that do not need each other run side by side. "
        "The graph is fixed for a version of Lekto; `processing.nodes` of a document names the "
        "state of each node. `vision` names the vision language model documents can be read "
        "with, if one is configured; `logo_fetch` says whether Lekto fetches the logos of "
        "contacts from their websites; `meaning_search` whether the search takes the meaning "
        "into account."
    ),
    response_model=PipelineOut,
    responses=problem_responses(401),
)
async def pipeline(user: CurrentUser, context: Context) -> PipelineOut:
    vision = context.pipeline.vision
    return PipelineOut(
        nodes=[
            GraphNodeOut(
                node=node,
                requires=sorted(node.requires),
                waits_for=sorted(node.waits_for - node.requires),
            )
            for node in NODES
        ],
        vision=None if vision is None else VisionOut(model=vision.model, endpoint=vision.endpoint),
        logo_fetch=context.logos.fetching,
        meaning_search=context.search is not None and context.search.meaning,
    )


@router.post(
    "/pipeline/reparse",
    status_code=202,
    summary="Read the text of every document again",
    description=(
        ADMINS_ONLY + " After an update of the parser (0.2 reads the text as it is set instead "
        "of Docling's Markdown): the worker reads the text of every document again whose text "
        "was read in its current run and that is not being processed. Nodes, lane and metadata "
        "stay as they are; the processing log gets the new reading (`input.reparse`), the "
        "search index takes up the new text (with embeddings, one per document). Train the "
        "classifier afterwards (`POST /classifier/train`). A document queued already is not "
        "queued twice."
    ),
    response_model=ReparseOut,
    responses=problem_responses(401, 403),
)
async def reparse(user: CurrentUser, context: Context) -> ReparseOut:
    return ReparseOut(queued=await context.pipeline.request_reparse(user))


@router.post(
    "/pipeline/relate",
    status_code=202,
    summary="Find the relations of every document again",
    description=(
        ADMINS_ONLY + " The worker relates every document that is not being processed with the "
        "documents it refers to and those that refer to it: for documents from before the "
        "node `relate`, and after a document type became a relation target. Relations a "
        "person set or rejected stay. A document queued already is not queued twice."
    ),
    response_model=QueuedOut,
    responses=problem_responses(401, 403),
)
async def relate(user: CurrentUser, context: Context) -> QueuedOut:
    return QueuedOut(queued=await context.pipeline.request_relate(user))


@router.post(
    "/pipeline/render-pages",
    status_code=202,
    summary="Render the missing page images",
    description=(
        ADMINS_ONLY + " The worker renders the page images of every document from before the "
        "node `pages` existed (its `pages` node is skipped in its current run). A document "
        "queued already is not queued twice."
    ),
    response_model=QueuedOut,
    responses=problem_responses(401, 403),
)
async def render_pages(user: CurrentUser, context: Context) -> QueuedOut:
    return QueuedOut(queued=await context.pipeline.request_render_pages(user))


@router.post(
    "/pipeline/read-facts",
    status_code=202,
    summary="Read the facts of every document again",
    description=(
        ADMINS_ONLY + " The worker reads the facts of every document whose text was read and "
        "that is not being processed again: the codes on its pages and the identifiers its "
        "text shows, with whose an IBAN, a creditor ID, a VAT ID or a domain is. For documents "
        "from before an "
        "update that reads facts differently. A document queued already is not queued twice."
    ),
    response_model=QueuedOut,
    responses=problem_responses(401, 403),
)
async def read_facts(user: CurrentUser, context: Context) -> QueuedOut:
    return QueuedOut(queued=await context.pipeline.request_read_facts(user))
