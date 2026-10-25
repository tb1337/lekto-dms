"""What consumers of tasks call: the answer to a task (`domain.tasks`), and the files of a
model call's document.

Not for users: the one-time token of the task is the credential of the answer
(`Authorization: Bearer`, never in the URL, which proxies log), the signature in its link that
of a file; no session or API token.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from lekto.adapters.inbound.bearer import bearer_token
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.problems import problem, problem_responses
from lekto.core.domain.errors import AuthenticationError
from lekto.core.domain.ids import TaskId
from lekto.core.domain.tasks import MAX_ANSWER_BYTES
from lekto.core.services.tasks.desk import CALLBACK_PATH
from lekto.core.services.tasks.files import FILES_PATH
from lekto.core.services.tasks.service import UNKNOWN_LINK, UNKNOWN_TOKEN

PREFIX = "/external"
ANSWER_PATH = CALLBACK_PATH.removeprefix("/api/v1")
FILE_PATH = FILES_PATH.removeprefix("/api/v1").replace("{name}", "{name:path}")

router = APIRouter(tags=["external"])


async def task_token(request: Request) -> str:
    """The task's token from `Authorization: Bearer`; AuthenticationError (401) without one."""
    header = request.headers.get("authorization")
    if header is None:
        raise AuthenticationError(UNKNOWN_TOKEN)
    return bearer_token(header)


TaskToken = Annotated[str, Depends(task_token)]


@dataclass(frozen=True)
class FileLink:
    expires: int
    signature: str


async def file_link(
    expires: Annotated[int | None, Query(description="When the link ends (Unix seconds).")] = None,
    signature: Annotated[
        str | None, Query(max_length=200, description="Lekto's signature.")
    ] = None,
) -> FileLink:
    """The signature of a file's link and its end; AuthenticationError (401) without them."""
    if expires is None or signature is None:
        raise AuthenticationError(UNKNOWN_LINK)
    return FileLink(expires, signature)


SignedLink = Annotated[FileLink, Depends(file_link)]


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


@router.get(
    FILE_PATH,
    summary="A file of a model call's document",
    description=(
        "The request of a model call (`external.propose`, `external.extract`) links the "
        "document's files: `content.json` (the structure of the text: pages, lines and words "
        "with their boxes) and `pages/<n>.webp` (the image of page n). Each link is signed and "
        "holds until the task's deadline, as long as the document is not processed again "
        "(409). 401: the link is unknown, altered, or its time is up."
    ),
    response_class=Response,
    responses={
        200: {"content": {"application/json": {}, "image/webp": {}}},
        **problem_responses(401, 404, 409, 422),
    },
)
async def task_file(id: UUID, name: str, link: SignedLink, context: Context) -> Response:
    found = await context.tasks.file(TaskId(id), name, link.expires, link.signature)
    return Response(found.data, media_type=found.media_type)
