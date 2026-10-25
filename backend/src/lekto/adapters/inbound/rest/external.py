"""What consumers of tasks call: the answer to a task (`domain.tasks`).

Not for users: the one-time token of the task is the credential (`Authorization: Bearer`, never
in the URL, which proxies log), no session or API token.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from lekto.adapters.inbound.bearer import bearer_token
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.problems import problem, problem_responses
from lekto.core.domain.errors import AuthenticationError
from lekto.core.domain.ids import TaskId
from lekto.core.domain.tasks import MAX_ANSWER_BYTES
from lekto.core.services.tasks.desk import CALLBACK_PATH
from lekto.core.services.tasks.service import UNKNOWN_TOKEN

PREFIX = "/external"
ANSWER_PATH = CALLBACK_PATH.removeprefix("/api/v1")

router = APIRouter(tags=["external"])


async def task_token(request: Request) -> str:
    """The task's token from `Authorization: Bearer`; AuthenticationError (401) without one."""
    header = request.headers.get("authorization")
    if header is None:
        raise AuthenticationError(UNKNOWN_TOKEN)
    return bearer_token(header)


TaskToken = Annotated[str, Depends(task_token)]


@router.post(
    ANSWER_PATH,
    status_code=204,
    summary="Answer a task",
    description=(
        "The consumer of a task (a request with the headers `lekto-task-id`, `lekto-callback`, "
        "`lekto-task-token`, `lekto-deadline`) answers it here, with the task's token as "
        "`Authorization: Bearer`. The token holds for one answer, until the deadline.\n\n"
        "The body is an envelope: `status` `ok` with `answer` (any JSON; a rule step's "
        "answer is `steps.<name>` for the steps after it), or `status` `error` with `reason` "
        "(a text, shown cut to 300 characters); `producer` (optional) names what answered. "
        "`error`, an envelope that is not valid (422) and an answer larger than 1 MB (413) "
        "count as no answer: the step goes on as it says for a missing answer, and the token "
        "is used up. 409: the task was answered before, or its document was processed again "
        "or deleted. 401: unknown task or token, or the deadline has passed."
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/TaskAnswer"}}
            },
        }
    },
    response_class=Response,
    responses=problem_responses(401, 409, 413, 422),
)
async def answer_task(id: UUID, request: Request, token: TaskToken, context: Context) -> Response:
    received = bytearray()
    too_large = False
    async for chunk in request.stream():
        received += chunk
        if len(received) > MAX_ANSWER_BYTES:
            too_large = True
            break
    body = None if too_large else bytes(received)
    receipt = await context.tasks.answer(TaskId(id), token, body)
    if receipt.too_large:
        return problem(413, receipt.problem or "too large")
    if receipt.problem is not None:
        return problem(422, receipt.problem)
    return Response(status_code=204)
