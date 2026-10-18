"""The classifier: its status and training on request. Admins only."""

from fastapi import APIRouter, Response

from papiq.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from papiq.adapters.inbound.rest.context import Classifier
from papiq.adapters.inbound.rest.problems import problem_responses
from papiq.adapters.inbound.rest.schemas.classifier import ClassifierStatusOut

router = APIRouter(prefix="/classifier", tags=["classifier"], dependencies=PROTECTED)


@router.get(
    "",
    summary="The classifier's status",
    description=(
        "Admins only. The latest model (trained from the documents a person confirmed or that "
        "were taken over with metadata) and the confirmations since. 503 without a classifier."
    ),
    response_model=ClassifierStatusOut,
    responses=problem_responses(401, 403, 503),
)
async def status(user: CurrentUser, classifier: Classifier) -> ClassifierStatusOut:
    return ClassifierStatusOut.of(await classifier.status(user))


@router.post(
    "/train",
    status_code=202,
    summary="Train the classifier",
    description=(
        "Admins only. Trains a new model in the background (it also happens on its own after "
        "enough confirmations); one that is queued or running is not queued twice. 409 with "
        "fewer confirmed documents than the first model needs, 503 without a classifier."
    ),
    response_class=Response,
    responses={202: {"description": "Queued."}, **problem_responses(401, 403, 409, 503)},
)
async def train(user: CurrentUser, classifier: Classifier) -> Response:
    await classifier.request_training(user)
    return Response(status_code=202)
