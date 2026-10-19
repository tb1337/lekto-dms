"""Documents: list, metadata, moving, deleting, files; upload, processing log, retry and
reprocessing; the inbox with its tabs, summary and seen, review and confirmation.

Documents the caller may not read are "not found", the same as documents that do not exist:
the list leaves them out, filters and pages only ever see readable ones.
"""

import asyncio
import os
import tempfile
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi import Path as FastApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from pydantic import ValidationError as PydanticValidationError
from starlette.background import BackgroundTask

from lekto.adapters.inbound.rest.auth import PROTECTED, Authenticated, CurrentUser
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.cursors import Cursor, decode_cursor, encode_cursor
from lekto.adapters.inbound.rest.params import AllDocuments, AllInboxes, Filter
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.documents import (
    DocumentAccepted,
    DocumentChanged,
    DocumentDetails,
    DocumentOutOfReach,
    DocumentPage,
    DocumentPatch,
    DocumentPreviewOut,
    DocumentTextOut,
    ExchangeNode,
    ImportedMetadataIn,
    ListedDocument,
    LogEntry,
    MoveRequest,
    ReadingOut,
    ReprocessRequest,
    RunExchangeOut,
    UploadFields,
    VisibilityOut,
)
from lekto.adapters.inbound.rest.schemas.facts import FactsOut
from lekto.adapters.inbound.rest.schemas.files import DocumentFilesOut
from lekto.adapters.inbound.rest.schemas.inbox import (
    ConfirmRequest,
    InboxItemOut,
    InboxPage,
    InboxSeenOut,
    InboxSummaryOut,
    ReviewOut,
)
from lekto.adapters.inbound.rest.upload import read_upload, upload_body
from lekto.adapters.inbound.schemas import RuleReportOut
from lekto.core.domain.classification import CHANGE_FIELDS, SPACE, field_key
from lekto.core.domain.documents import UNSET, Channel, Document, DocumentChanges, Unset
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import field_from_json
from lekto.core.domain.ids import (
    ContactId,
    DocumentId,
    DocumentTypeId,
    FieldId,
    SpaceId,
    TagId,
    UserId,
)
from lekto.core.domain.imports import ImportedMetadata
from lekto.core.domain.inbox import InboxTab
from lekto.core.domain.pipeline import Node
from lekto.core.ports.pages import PAGE_MEDIA_TYPE
from lekto.core.ports.repository import PAGE_LIMIT, PAGE_SIZE, DocumentOrder, SortKey
from lekto.core.services.documents import DocumentFile, DocumentView, MetadataChange

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=PROTECTED)
inbox = APIRouter(prefix="/inbox", tags=["inbox"], dependencies=PROTECTED)


class DocumentSort(StrEnum):
    """A key to sort by, descending with a `-` before it. Documents without a date come last
    either way."""

    CREATED = "created_at"
    CREATED_DESC = "-created_at"
    DOCUMENT_DATE = "document_date"
    DOCUMENT_DATE_DESC = "-document_date"
    TITLE = "title"
    TITLE_DESC = "-title"

    @property
    def order(self) -> DocumentOrder:
        return DocumentOrder(SortKey(self.value.lstrip("-")), ascending=not self.startswith("-"))


_UPLOAD_BODY = upload_body(
    "PDF, JPEG, PNG or TIFF; recognised by content.", **UploadFields.form_schema()
)


@router.post(
    "",
    status_code=202,
    summary="Upload a document",
    description=(
        "Stores the file and starts processing in the background. The file is hashed while it "
        "is received; a file the caller already has is rejected with 409. Follow the progress "
        "at `status_url` or with `GET /events`."
    ),
    response_model=DocumentAccepted,
    responses={
        202: {
            "description": "Accepted; processing runs in the background.",
            "headers": {
                "Location": {
                    "description": "The status of the document.",
                    "schema": {"type": "string"},
                }
            },
            "content": {
                "application/json": {
                    "example": {
                        "id": "01999d5e-8a7f-7c1e-b6a3-2f4d5e6f7a8b",
                        "status_url": "/api/v1/documents/01999d5e-8a7f-7c1e-b6a3-2f4d5e6f7a8b",
                    }
                }
            },
        },
        **problem_responses(400, 401, 403, 404, 409, 413, 415, 422),
    },
    openapi_extra=_UPLOAD_BODY,
)
async def upload(
    request: Request, response: Response, principal: Authenticated, context: Context
) -> DocumentAccepted:
    received = await read_upload(
        request,
        max_size=context.max_upload_size,
        fields=UploadFields.model_fields,
        limits=UploadFields.LIMITS,
    )
    try:
        try:
            form = UploadFields.model_validate(received.fields)
        except PydanticValidationError as error:
            # The form is the body: its errors read as those of a JSON body.
            raise RequestValidationError(
                [{**item, "loc": ("body", *item["loc"])} for item in error.errors()]
            ) from None
        # The intake channel: as the caller says (`migration` only), else by credentials.
        channel = Channel.API if principal.session is None else Channel.WEB
        if form.channel is not None:
            channel = Channel(form.channel)
        imported = (
            None
            if form.metadata is None
            else await _imported_metadata(form.metadata, principal.id, context)
        )
        document = await context.pipeline.receive(
            principal.id,
            received.file,
            filename=received.filename,
            space=None if form.space_id is None else SpaceId(form.space_id),
            channel=channel,
            owner=None if form.owner is None else UserId(form.owner),
            imported=imported,
        )
    finally:
        await asyncio.shield(asyncio.to_thread(received.file.path.unlink, missing_ok=True))
    url = str(request.url_for("get_document", id=document.id).path)
    response.headers["Location"] = url
    return DocumentAccepted(id=document.id, status_url=url)


@router.get(
    "",
    summary="List documents",
    description=(
        "The documents within the caller's reach, newest first: their own, and green "
        "documents in spaces they own or that are shared with them. Admins may read every "
        "document and list them all with `all_users` (others: 403). Filters combine; `tag_id`, "
        "`contact_group_id`, `document_type_group_id`, `topic_id` and `lane` may repeat (all "
        "tags and groups, any topic, any lane; `processing`: no lane yet). A tag matches the "
        "documents with it or a tag below it; a group those whose contact (type) is in it or a "
        "group below it; a topic the documents with it or one below it. "
        "`field_id`: a value for the field is set. `sort` orders by arrival (the default, "
        "newest first), "
        "document date or title; documents without a date come last. Each document says whether "
        "it stands in the caller's inbox (`in_inbox`). To search by words and meaning use "
        "`GET /documents/search`."
    ),
    response_model=DocumentPage,
    responses=problem_responses(401, 403, 422),
)
async def list_documents(
    user: CurrentUser,
    context: Context,
    filter: Filter,
    sort: DocumentSort = DocumentSort.CREATED_DESC,
    limit: Annotated[int, Query(ge=1, le=PAGE_LIMIT)] = PAGE_SIZE,
    cursor: Cursor = None,
    all_users: AllDocuments = False,
) -> DocumentPage:
    views = await context.documents.query(
        user,
        filter,
        order=sort.order,
        after=decode_cursor(cursor),
        limit=limit,
        all_users=all_users,
    )
    next_cursor = encode_cursor(views[-1].document.id) if len(views) == limit else None
    return DocumentPage(
        items=[ListedDocument.listed(view.document, view.access, view.in_inbox) for view in views],
        next_cursor=next_cursor,
    )


@router.get(
    "/{id}",
    name="get_document",
    summary="A document",
    description="Metadata, processing state and lane, and the caller's access.",
    response_model=DocumentDetails,
    responses=problem_responses(401, 404, 422),
)
async def get_document(id: UUID, user: CurrentUser, context: Context) -> DocumentDetails:
    view = await context.documents.view(user, DocumentId(id))
    return DocumentDetails.of(view.document, view.access)


@router.patch(
    "/{id}",
    summary="Change a document's metadata",
    description=(
        "Needs write access (owner or a `read_write` share). Referenced contact, type, tags "
        "and fields must exist; field values must fit their type and apply to the "
        "document type. On a filed document, the change sets off the owner's rules and the "
        "global ones with trigger `change` that hold after it and did not before; fields set "
        "in the change stay as they are. The owner sees what the rules did in `rules`. If the "
        "rules filed the document where the caller can no longer read it, the answer has only "
        "its `id` and `access: null`."
    ),
    response_model=DocumentChanged | DocumentOutOfReach,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def update_document(
    id: UUID, body: DocumentPatch, user: CurrentUser, context: Context
) -> DocumentChanged | DocumentOutOfReach:
    changes = await _changes(body, user, context)
    change = await context.documents.change_metadata(user, DocumentId(id), changes)
    return _changed(change)


@router.post(
    "/{id}/dry-run",
    summary="Try a metadata change",
    description=(
        "What `PATCH /documents/{id}` with this body would do, without storing anything: the "
        "document afterwards, the fields that would change, what the rules would do (owner "
        "and admins) and who would see it. Needs write access."
    ),
    response_model=DocumentPreviewOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def preview_change(
    id: UUID, body: DocumentPatch, principal: Authenticated, context: Context
) -> DocumentPreviewOut:
    user = principal.id
    changes = await _changes(body, user, context)
    change = await context.documents.change_metadata(user, DocumentId(id), changes, dry_run=True)
    readable = change.access is not None
    return DocumentPreviewOut(
        document=DocumentDetails.of(change.document, change.access) if change.access else None,
        changed=_differences(change.before, change.document) if change.before else [],
        rules=(
            None
            if change.rules is None
            else [RuleReportOut.of(report) for report in change.rules.plan.reports]
        ),
        visibility=(
            VisibilityOut.of(change.document, change.space, principal.user) if readable else None
        ),
    )


@router.post(
    "/{id}/move",
    status_code=204,
    summary="Move a document to another space",
    description=(
        "The owner moves into spaces they may write to; an admin moves any document into any "
        "space. Shares do not allow moving."
    ),
    responses=problem_responses(401, 403, 404, 422),
)
async def move_document(id: UUID, body: MoveRequest, user: CurrentUser, context: Context) -> None:
    await context.documents.move(user, DocumentId(id), SpaceId(body.space_id))


@router.delete(
    "/{id}",
    status_code=204,
    summary="Delete a document",
    description="The owner and admins.",
    responses=problem_responses(401, 403, 404, 422),
)
async def delete_document(id: UUID, user: CurrentUser, context: Context) -> None:
    await context.documents.delete(user, DocumentId(id))


def _file_route(file: DocumentFile, summary: str, media: str, disposition: str) -> None:
    @router.get(
        f"/{{id}}/{file.value}",
        name=f"get_document_{file.value}",
        summary=summary,
        description="Needs read access. 404 while the file does not exist (yet).",
        response_class=FileResponse,
        responses={
            200: {"content": {media: {"schema": {"type": "string", "format": "binary"}}}},
            **problem_responses(401, 404, 422),
        },
    )
    async def download(id: UUID, user: CurrentUser, context: Context) -> FileResponse:
        return await _download(context, user, DocumentId(id), file, disposition)


_file_route(DocumentFile.ORIGINAL, "The original file", "application/octet-stream", "attachment")
_file_route(
    DocumentFile.ARCHIVE, "The archive PDF (PDF/A with text layer)", "application/pdf", "inline"
)
_file_route(DocumentFile.PREVIEW, "The preview image of the first page", PAGE_MEDIA_TYPE, "inline")


@router.get(
    "/{id}/pages/{number}",
    summary="The image of one page",
    description=(
        "Needs read access. Pages are numbered from 1 up to `page_count`; 404 while the page "
        "images do not exist (yet) or for a number the document does not have."
    ),
    response_class=FileResponse,
    responses={
        200: {"content": {PAGE_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}}},
        **problem_responses(401, 404, 422),
    },
)
async def get_document_page(
    id: UUID, number: Annotated[int, FastApiPath(ge=1)], user: CurrentUser, context: Context
) -> FileResponse:
    return await _download(context, user, DocumentId(id), DocumentFile.PAGE, "inline", page=number)


async def _download(
    context: Context,
    user: UserId,
    id: DocumentId,
    file: DocumentFile,
    disposition: str,
    *,
    page: int = 1,
) -> FileResponse:
    descriptor, name = await asyncio.to_thread(tempfile.mkstemp, prefix="papiq-download-")
    os.close(descriptor)
    path = Path(name)
    try:
        info = await context.documents.download(user, id, file, path, page=page)
    except BaseException:
        await asyncio.shield(asyncio.to_thread(path.unlink, missing_ok=True))
        raise
    return FileResponse(
        path,
        media_type=info.media_type,
        filename=info.filename,
        content_disposition_type=disposition,
        # `Cache-Control: no-store` and `nosniff` come from the `NoStore` middleware, as for
        # every answer. A file shown in the browser runs no scripts and reaches nothing of
        # this site.
        headers={"Content-Security-Policy": "sandbox; default-src 'none'"},
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.get(
    "/{id}/text",
    summary="The recognised text of a document",
    description=(
        "Needs read access. The text read from the archive, plain text as it is set (the "
        "pages apart by a form feed on a line of its own; a document parsed before 0.2 has "
        "Markdown until it is read again), in pieces of at most `PAPIQ_MCP_TEXT_MAX` "
        "characters; continue with `next_offset`. 409 while the document has no text yet (it "
        "is not parsed), 422 for a larger `limit`."
    ),
    response_model=DocumentTextOut,
    responses=problem_responses(401, 404, 409, 422),
)
async def document_text(
    id: UUID,
    user: CurrentUser,
    context: Context,
    offset: Annotated[int, Query(ge=0, description="First character.")] = 0,
    limit: Annotated[
        int | None, Query(ge=1, description="Characters; without it, as many as one answer holds.")
    ] = None,
) -> DocumentTextOut:
    if limit is None:
        limit = context.text_max
    elif limit > context.text_max:
        raise ValidationError(f"limit is at most {context.text_max} characters")
    piece = await context.documents.read_text(user, DocumentId(id), offset=offset, limit=limit)
    return DocumentTextOut(
        text=piece.text,
        offset=piece.offset,
        total_length=piece.total_length,
        next_offset=piece.next_offset,
    )


@router.get(
    "/{id}/structure",
    summary="The parsed structure of a document",
    description=(
        "Needs read access. The structure of the text: `pages` with `number`, `width` and "
        "`height` (points), their `lines` with `text`, `box` and `words` (each with `text` and "
        "`box`); a box is `[x1, y1, x2, y2]` in fractions of the page as shown, from its top "
        "left. A document parsed before 0.2 has Docling's JSON until it is read again. Can be "
        "large. 409 while the document is not parsed."
    ),
    response_class=Response,
    responses={
        200: {"content": {"application/json": {"schema": {"type": "object"}}}},
        **problem_responses(401, 404, 409, 422),
    },
)
async def document_structure(id: UUID, user: CurrentUser, context: Context) -> Response:
    data = await context.documents.read_structure(user, DocumentId(id))
    return Response(data, media_type="application/json")


@router.get(
    "/{id}/exchanges/{node}",
    summary="What a node sent to the language model",
    description=(
        "The owner and admins, as the log. The messages, the answer and the usage report of "
        "every call of `node` to the language model, per processing run, oldest first; empty "
        "if it never asked one (also for runs from before the messages were kept). For `ocr`, "
        "the vision language model's calls, one per page; the page image stands in the "
        "message as a placeholder."
    ),
    response_model=list[RunExchangeOut],
    responses=problem_responses(401, 403, 404, 422),
)
async def model_exchanges(
    id: UUID, node: ExchangeNode, user: CurrentUser, context: Context
) -> list[RunExchangeOut]:
    exchanges = await context.documents.exchanges(user, DocumentId(id), Node(node.value))
    return [RunExchangeOut.of(exchange) for exchange in exchanges]


@router.get(
    "/{id}/log",
    summary="Processing log of a document",
    description="The owner and admins. Every execution of every node, oldest first.",
    response_model=list[LogEntry],
    responses=problem_responses(401, 403, 404, 422),
)
async def processing_log(id: UUID, user: CurrentUser, context: Context) -> list[LogEntry]:
    return [
        LogEntry.of(run) for run in await context.documents.processing_log(user, DocumentId(id))
    ]


@router.post(
    "/{id}/retry",
    status_code=202,
    summary="Repeat the failed node",
    description="The owner and admins. Processing continues with the following nodes.",
    response_model=DocumentDetails,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def retry(id: UUID, user: CurrentUser, context: Context) -> DocumentDetails:
    return _details(await context.pipeline.retry(user, DocumentId(id)))


@router.post(
    "/{id}/vision",
    status_code=202,
    summary="Read the document with the vision language model",
    description=(
        "The owner and admins. Sends every page as an image to the vision language model "
        "(`PAPIQ_VLM_*`, named in `GET /pipeline`) and processes the document again from "
        "`ocr`: the model's text becomes the archive's text layer and is checked like any "
        "other OCR. Only a person asks for it; the advice is in `GET /documents/{id}/reading`. "
        "409 without a model, while processing runs, or past a failed node."
    ),
    response_model=DocumentDetails,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def read_with_vision(id: UUID, user: CurrentUser, context: Context) -> DocumentDetails:
    return _details(await context.pipeline.read_with_vision(user, DocumentId(id)))


@router.get(
    "/{id}/facts",
    summary="What a document shows of its contact",
    description=(
        "Needs read access. The names of contacts and the identifiers (IBAN, VAT and customer "
        "numbers, mail domains) its text shows, each with where it stands (`spans`, characters "
        "of `GET /documents/{id}/text`), and the codes on its pages (QR, Data Matrix, Code 128, "
        "...) with what they hold: a GiroCode read as its credit transfer. Found as the facts "
        "signal finds them now, so an identifier attached since counts at once. 409 while the "
        "document has no text yet."
    ),
    response_model=FactsOut,
    responses=problem_responses(401, 404, 409, 422),
)
async def document_facts(id: UUID, user: CurrentUser, context: Context) -> FactsOut:
    return FactsOut.of(await context.documents.facts(user, DocumentId(id)))


@router.get(
    "/{id}/files",
    summary="A document's files and their metadata",
    description=(
        "Needs read access. When the document was added and last changed, its original's "
        "name and media type, and for the original and the archive (null while there is none) "
        "their size, SHA-256 and what they say about themselves: a PDF's version, PDF/A level, "
        "pages, document information and XMP; an image's format, size, resolution and EXIF. "
        "The files are read for it, so it takes a moment for large ones."
    ),
    response_model=DocumentFilesOut,
    responses=problem_responses(401, 404, 422),
)
async def document_files(id: UUID, user: CurrentUser, context: Context) -> DocumentFilesOut:
    return DocumentFilesOut.of(await context.documents.files(user, DocumentId(id)))


@router.get(
    "/{id}/reading",
    summary="How the text of a document was read",
    description=(
        "The owner and admins, as the log. Whether the archive's text is the vision language "
        "model's, the words and unsure words of each page its latest OCR recognised, and "
        "whether reading it with the model is advised."
    ),
    response_model=ReadingOut,
    responses=problem_responses(401, 403, 404, 422),
)
async def reading(id: UUID, user: CurrentUser, context: Context) -> ReadingOut:
    return ReadingOut.of(await context.pipeline.reading(user, DocumentId(id)))


@router.post(
    "/{id}/reprocess",
    status_code=202,
    summary="Process again from a node",
    description=(
        "The owner and admins. Discards the results from `from_node` on, e.g. after a model "
        "change. Not while processing runs, not past a failed node, and not from `file` while "
        "uncertain fields wait for confirmation."
    ),
    response_model=DocumentDetails,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def reprocess(
    id: UUID, body: ReprocessRequest, user: CurrentUser, context: Context
) -> DocumentDetails:
    node = Node(body.from_node.value)
    return _details(await context.pipeline.reprocess_from(user, DocumentId(id), node))


@router.put(
    "/{id}/seen",
    status_code=204,
    summary="Mark a document as seen",
    description=(
        "The caller saw the document: if it stands in their inbox as new, it leaves it (`done`, "
        "`GET /inbox`); seen again later, it keeps that time. The web UI calls it when the "
        "document view opens; reading a document "
        "(`GET /documents/{id}`, MCP) does not. Needs read access; nothing changes for a "
        "document that is new for no one, or one the caller reaches through a share only (it "
        "never stands in their inbox). Seen is per user and changes nothing else: not "
        "`confirmed_at`, the training, rules or the lane."
    ),
    responses=problem_responses(401, 403, 404, 422),
)
async def mark_seen(id: UUID, user: CurrentUser, context: Context) -> None:
    await context.inbox.mark_seen(user, DocumentId(id))


@router.delete(
    "/{id}/seen",
    status_code=204,
    summary="Mark a document as new again",
    description=(
        "Forgets that the caller saw the document: while it is new, it stands in their inbox "
        "under `new` again. Needs read access."
    ),
    responses=problem_responses(401, 403, 404, 422),
)
async def mark_unseen(id: UUID, user: CurrentUser, context: Context) -> None:
    await context.inbox.mark_unseen(user, DocumentId(id))


@router.get(
    "/{id}/review",
    summary="What the model proposed for a document",
    description=(
        "The owner and admins. The open nodes and fields, and the latest classification and "
        "field extraction by the model: each field as proposed, checked and applied."
    ),
    response_model=ReviewOut,
    responses=problem_responses(401, 403, 404, 422),
)
async def review(id: UUID, user: CurrentUser, context: Context) -> ReviewOut:
    return ReviewOut.of(await context.documents.review(user, DocumentId(id)))


@router.post(
    "/{id}/confirm",
    status_code=202,
    summary="Confirm a document from the inbox",
    description=(
        "The owner and admins, for yellow and red documents that are not being processed. "
        "`space_id` must be a space the owner may write to; an admin chooses any space. "
        "Every open field of the nodes before `resume_at` (and of `apply_rules` when processing "
        "resumes with it) needs a decision: a value or null in `changes`, a value the document "
        "already has (it is kept), or its suggestion with `accept_suggestions`. Otherwise 422 "
        "lists the open fields in `open_fields`. The rules' fields `space`, `title` and "
        "`review` always have a value: confirming keeps it, `space_id` moves the document. The "
        "results before `resume_at` count as confirmed; processing continues from there up to "
        "filing, and the rules leave what the owner decided or changed as it is. From "
        "`fields` on, the fields read again replace the ones the document has; otherwise the "
        "type's title pattern is rendered with the decided values (while the title is the "
        "machine's)."
    ),
    response_model=DocumentDetails,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def confirm(
    id: UUID, body: ConfirmRequest, user: CurrentUser, context: Context
) -> DocumentDetails:
    changes = await _changes(body.changes, user, context)
    view = await context.pipeline.confirm(
        user,
        DocumentId(id),
        changes,
        accept_suggestions=body.accept_suggestions,
        resume_at=Node(body.resume_at.value),
        space=None if body.space_id is None else SpaceId(body.space_id),
    )
    return _details(view)


@inbox.get(
    "",
    summary="The caller's inbox",
    description=(
        "The caller's own documents that wait for them, newest first: in processing, yellow "
        "(`review`), red (`intervene`), and new ones, which went green without a person's "
        "decision and are not seen by the caller since (`PUT /documents/{id}/seen`); each with "
        "its open nodes and fields. Documents the caller reaches through a share never stand "
        "there. `tab` takes one of them, or `done`: what left the inbox in the last 14 days, "
        "with how (confirmed out of yellow or red, or seen), when and by whom, newest first by "
        "when it left (a `cursor` whose document is no longer done: 422). With "
        "`all_users` (admins, others: 403) every user's inbox, with the caller's own seen. "
        "Confirm yellow and red documents with `POST /documents/{id}/confirm`, or repeat a "
        "failed node with `retry`."
    ),
    response_model=InboxPage,
    responses=problem_responses(401, 403, 422),
)
async def list_inbox(
    user: CurrentUser,
    context: Context,
    tab: Annotated[
        InboxTab | None, Query(description="One tab; without it, everything but `done`.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=PAGE_LIMIT)] = PAGE_SIZE,
    cursor: Cursor = None,
    all_users: AllInboxes = False,
) -> InboxPage:
    items = await context.inbox.items(
        user, tab=tab, after=decode_cursor(cursor), limit=limit, all_users=all_users
    )
    next_cursor = encode_cursor(items[-1].document.id) if len(items) == limit else None
    return InboxPage(items=[InboxItemOut.of(item) for item in items], next_cursor=next_cursor)


@inbox.get(
    "/summary",
    summary="What the caller's inbox holds",
    description=(
        "How many documents stand under each tab of the caller's inbox (as `GET /inbox`), "
        "everything open together, and the worst lane among the open ones (red before yellow "
        "before green; null with nothing open but documents in processing). With `all_users` "
        "(admins, others: 403) every user's inbox."
    ),
    response_model=InboxSummaryOut,
    responses=problem_responses(401, 403, 422),
)
async def inbox_summary(
    user: CurrentUser, context: Context, all_users: AllInboxes = False
) -> InboxSummaryOut:
    return InboxSummaryOut.of(await context.inbox.summary(user, all_users=all_users))


@inbox.post(
    "/seen",
    summary="Mark everything new in the inbox as seen",
    description=(
        "Marks every document that stands under `new` in the caller's inbox as seen by them "
        "(with `all_users`, admins, others: 403: in every user's inbox, for the caller). They "
        "go to `done`."
    ),
    response_model=InboxSeenOut,
    responses=problem_responses(401, 403, 422),
)
async def mark_all_seen(
    user: CurrentUser, context: Context, all_users: AllInboxes = False
) -> InboxSeenOut:
    return InboxSeenOut(marked=await context.inbox.mark_all_seen(user, all_users=all_users))


def _differences(before: Document, after: Document) -> list[str]:
    fields: dict[str, tuple[object, object]] = {
        name: (getattr(before, attribute), getattr(after, attribute))
        for name, attribute in CHANGE_FIELDS.items()
    }
    fields[SPACE] = (before.space_id, after.space_id)
    for field in sorted(set(before.fields) | set(after.fields)):
        fields[field_key(field)] = (before.fields.get(field), after.fields.get(field))
    return [name for name, (old, new) in fields.items() if old != new]


def _changed(change: MetadataChange) -> DocumentChanged | DocumentOutOfReach:
    if change.access is None:
        return DocumentOutOfReach(id=change.document.id)
    details = DocumentDetails.of(change.document, change.access)
    rules = None
    if change.rules is not None:
        rules = [RuleReportOut.of(report) for report in change.rules.plan.reports]
    return DocumentChanged(**details.model_dump(), rules=rules)


def _details(view: DocumentView) -> DocumentDetails:
    return DocumentDetails.of(view.document, view.access)


async def _changes(body: DocumentPatch, user: UserId, context: Context) -> DocumentChanges:
    given = body.model_fields_set
    fields: dict[FieldId, object] = {}
    if body.fields:
        definitions = {a.id: a for a in await context.master_data.list_fields(user)}
        for field_id, value in body.fields.items():
            definition = definitions.get(FieldId(field_id))
            fields[FieldId(field_id)] = (
                value if definition is None or value is None else field_from_json(definition, value)
            )
    if "title" in given and body.title is None:
        raise ValidationError("title: must not be null")
    return DocumentChanges(
        title=body.title if body.title is not None else UNSET,
        contact_id=_given(given, "contact_id", body.contact_id, ContactId),
        document_type_id=_given(given, "document_type_id", body.document_type_id, DocumentTypeId),
        topic_id=_given(given, "topic_id", body.topic_id, TagId),
        tag_ids=(
            frozenset(TagId(tag) for tag in body.tag_ids or ()) if "tag_ids" in given else UNSET
        ),
        document_date=body.document_date if "document_date" in given else UNSET,
        fields=fields,
    )


def _given[T](
    given: set[str], name: str, value: UUID | None, kind: Callable[[UUID], T]
) -> T | Unset | None:
    if name not in given:
        return UNSET
    return None if value is None else kind(value)


async def _imported_metadata(
    body: ImportedMetadataIn, user: UserId, context: Context
) -> ImportedMetadata:
    """The metadata field as domain values (field values by their definitions)."""
    definitions = {a.id: a for a in await context.master_data.list_fields(user)}
    fields = {}
    for field_id, raw in body.fields.items():
        definition = definitions.get(FieldId(field_id))
        if definition is None:
            raise ValidationError(f"metadata.fields: field {field_id} does not exist")
        if raw is None:
            raise ValidationError(f"metadata.fields.{field_id}: must not be null")
        fields[FieldId(field_id)] = raw
    try:
        return ImportedMetadata(
            title=body.title,
            contact_id=None if body.contact_id is None else ContactId(body.contact_id),
            document_type_id=(
                None if body.document_type_id is None else DocumentTypeId(body.document_type_id)
            ),
            tag_ids=frozenset(TagId(tag) for tag in body.tag_ids),
            document_date=body.document_date,
            fields={key: field_from_json(definitions[key], raw) for key, raw in fields.items()},
        )
    except ValidationError as error:
        raise ValidationError(f"metadata: {error}") from None
