"""Errors as problem details (RFC 9457, `application/problem+json`): the error format of the
inbound adapters over HTTP (REST API, MCP endpoint)."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from lekto.core.domain.users import BlockingSpace

PROBLEM_JSON = "application/problem+json"


class BlockingSpaceOut(BaseModel):
    """A space that stops deleting a user until the deletion settles it."""

    space_id: UUID
    name: str = Field(description="The stored name; a personal space is presented by `personal`.")
    personal: bool = Field(description="The user's personal space (it holds documents).")
    documents: int = Field(description="How many documents lie in it.")
    choices: list[str] = Field(
        description="How it may be settled: `remove` (an empty space goes with the user), "
        "`move_to` (its documents move into another space, then it goes), `editor` (another "
        "user edits it, it stays).",
        examples=[["move_to", "editor"]],
    )


def blocking_space_out(space: BlockingSpace) -> BlockingSpaceOut:
    return BlockingSpaceOut(
        space_id=space.id,
        name=space.name,
        personal=space.personal,
        documents=space.documents,
        choices=[choice.value for choice in space.choices],
    )


class Problem(BaseModel):
    """What went wrong. `type` is `about:blank`: `title` and `status` say it all."""

    type: str = "about:blank"
    title: str = Field(examples=["Not Found"])
    status: int = Field(examples=[404])
    detail: str | None = Field(default=None, examples=["document 0199… not found"])
    existing_document_id: UUID | None = Field(
        default=None,
        description=(
            "For a duplicate (every file exists once per installation): the document that has "
            "the same file, if the caller may read it; missing if it lies in a space the caller "
            "cannot see."
        ),
    )
    space_id: UUID | None = Field(
        default=None,
        description="Filing or moving refused: the space the caller may not write to.",
    )
    open_fields: list[str] | None = Field(
        default=None, description="Confirming a document: the fields that need a decision."
    )
    blocking_spaces: list[BlockingSpaceOut] | None = Field(
        default=None,
        description="Deleting a user: the spaces that need a decision (`DELETE /users/{id}`).",
    )
    second_factor_required: bool | None = Field(
        default=None,
        description="Sign-in: the password was right; send it again with `code` or "
        "`recovery_code`.",
    )


# status: (title, example detail)
PROBLEMS: dict[int, tuple[str, str]] = {
    400: ("Bad Request", "expected multipart/form-data with a boundary"),
    401: ("Unauthorized", "authentication is required"),
    429: ("Too Many Requests", "too many failed attempts; try again later"),
    502: ("Bad Gateway", "the identity provider cannot be reached"),
    403: ("Forbidden", "only editors and admins control the processing of this document"),
    404: ("Not Found", "document 01999d5e-8a7f-7c1e-b6a3-2f4d5e6f7a8b not found"),
    405: ("Method Not Allowed", "the method is not allowed here"),
    409: ("Conflict", "duplicate of document 01999d5e-8a7f-7c1e-b6a3-2f4d5e6f7a8b"),
    413: ("Content Too Large", "the request body is larger than 1048576 bytes"),
    415: ("Unsupported Media Type", "unsupported file type"),
    422: ("Unprocessable Content", "from_node: Input should be 'ocr', 'parse', ..."),
    500: ("Internal Server Error", "an unexpected error occurred"),
    503: ("Service Unavailable", "database: unreachable"),
}


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses` for the given statuses and 500, with problem schema and example."""
    statuses = (*statuses, 500)
    return {
        status: {
            "description": PROBLEMS[status][0],
            "content": {
                PROBLEM_JSON: {
                    "schema": {"$ref": "#/components/schemas/Problem"},
                    "example": {
                        "type": "about:blank",
                        "title": PROBLEMS[status][0],
                        "status": status,
                        "detail": PROBLEMS[status][1],
                    },
                }
            },
        }
        for status in statuses
    }


def problem(
    status: int,
    detail: str | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    body = Problem(title=PROBLEMS.get(status, (str(status), ""))[0], status=status)
    body.detail = detail
    for name, value in extra.items():
        setattr(body, name, value)
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True),
        status_code=status,
        media_type=PROBLEM_JSON,
        headers=dict(headers or {}),
    )
