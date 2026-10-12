"""`GET /pipeline`: the graph of nodes a document goes through."""

from fastapi import APIRouter

from papiq.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from papiq.adapters.inbound.rest.problems import problem_responses
from papiq.adapters.inbound.rest.schemas.pipeline import GraphNodeOut, PipelineOut
from papiq.core.domain.pipeline import NODES

router = APIRouter(tags=["pipeline"], dependencies=PROTECTED)


@router.get(
    "/pipeline",
    summary="The processing graph",
    description=(
        "The nodes a document goes through and what each one needs, in graph order: every "
        "node after the nodes it needs. Nodes that do not need each other run side by side. "
        "The graph is fixed for a version of Papiq; `processing.nodes` of a document names the "
        "state of each node."
    ),
    response_model=PipelineOut,
    responses=problem_responses(401),
)
async def pipeline(user: CurrentUser) -> PipelineOut:
    return PipelineOut(
        nodes=[GraphNodeOut(node=node, requires=sorted(node.requires)) for node in NODES]
    )
