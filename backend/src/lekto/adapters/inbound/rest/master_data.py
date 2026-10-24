"""Master data: contacts, document types, tags, field definitions. Everyone reads them;
admins change them. Deleting works only for what nothing uses."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import GenericAlias
from typing import Any, Concatenate, Protocol, Self
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from lekto.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from lekto.adapters.inbound.rest.context import ApiContext, Context
from lekto.adapters.inbound.rest.params import ADMINS_ONLY, CountAll, DocumentCounts
from lekto.adapters.inbound.rest.paths import PREFIX
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.master_data import (
    ContactCreate,
    ContactOut,
    ContactPatch,
    DocumentTypeCreate,
    DocumentTypeOut,
    DocumentTypePatch,
    FieldAssignmentsIn,
    FieldCreate,
    FieldOut,
    FieldPatch,
    IdentifierIn,
    MasterDataOut,
    TagCreate,
    TagOut,
    TagPatch,
)
from lekto.adapters.inbound.rest.upload import read_upload, upload_body
from lekto.core.domain.documents import UNSET, Unset
from lekto.core.domain.identifiers import Identifier
from lekto.core.domain.ids import ContactId, DocumentTypeId, FieldId, TagId, UserId
from lekto.core.domain.master_data import MasterData, TagScope
from lekto.core.domain.tag_tree import TagTree
from lekto.core.ports.repository import CountBy
from lekto.core.services.logos import LOGO_MAX_SIZE, LOGO_TYPE
from lekto.core.services.master_data import MasterDataService

COUNTS = (
    "Everyone reads them. With `document_counts`, each comes with how many documents within "
    "the caller's reach have it (a field: a value for it), counted in one query; admins count "
    "every document with `all_users` (others: 403)."
)


@dataclass(frozen=True, kw_only=True)
class Kind[K: UUID, E: MasterData, C: BaseModel, P: BaseModel, O: MasterDataOut]:
    """One kind of named master data for `_simple`: the service's methods for it, the bodies
    that create (`C`) and change it (`P`), and its answer (`O`, made with `of`). The bodies'
    fields, as validated (a nested body stays a model), are the methods' keyword arguments, as
    `arguments` turns them."""

    path: str
    noun: str  # in summaries: "List document types"
    name: str  # in route names: `create_document_type`
    plural: str  # in the list's route name: `list_document_types`
    id: Callable[[UUID], K]
    list: Callable[[MasterDataService, UserId], Awaitable[list[E]]]
    create: Callable[Concatenate[MasterDataService, UserId, ...], Awaitable[E]]
    get: Callable[[MasterDataService, UserId, K], Awaitable[E]]
    change: Callable[Concatenate[MasterDataService, UserId, K, ...], Awaitable[E]]
    delete: Callable[[MasterDataService, UserId, K], Awaitable[None]]
    create_in: type[C]
    patch_in: type[P]
    out: type[O]
    of: Callable[[E], O]
    counted: CountBy
    arguments: Callable[[dict[str, Any]], dict[str, Any]] = lambda given: given


def _simple[K: UUID, E: MasterData, C: BaseModel, P: BaseModel, O: MasterDataOut](
    kind: Kind[K, E, C, P, O],
) -> APIRouter:
    """List, create, read, change and delete one kind of named master data; a patch passes
    only the fields given."""
    router = APIRouter(prefix=f"/{kind.path}", tags=["master data"], dependencies=PROTECTED)

    @router.get(
        "",
        name=f"list_{kind.plural}",
        summary=f"List {kind.noun}s",
        description=COUNTS,
        response_model=GenericAlias(list, (kind.out,)),
        responses=problem_responses(401, 403, 422),
    )
    async def list_items(
        user: CurrentUser,
        context: Context,
        document_counts: DocumentCounts = False,
        all_users: CountAll = False,
    ) -> list[O]:
        found = [kind.of(item) for item in await kind.list(context.master_data, user)]
        if not document_counts:
            return found
        counts = await context.documents.document_counts(user, kind.counted, all_users=all_users)
        return _with_counts(found, counts)

    @router.post(
        "",
        name=f"create_{kind.name}",
        status_code=201,
        summary=f"Create a {kind.noun}",
        description=ADMINS_ONLY
        + " Names are unique regardless of case. A group in `group_ids` (a topic in "
        "`topic_ids`) that does not exist is `404`, one of another scope `422`.",
        response_model=kind.out,
        responses=problem_responses(401, 403, 404, 409, 422),
    )
    @_body(kind.create_in)
    async def create(body: C, user: CurrentUser, context: Context) -> O:
        given = kind.arguments(dict(body))
        return kind.of(await kind.create(context.master_data, user, **given))

    @router.get(
        "/{id}",
        name=f"get_{kind.name}",
        summary=f"A {kind.noun}",
        response_model=kind.out,
        responses=problem_responses(401, 404, 422),
    )
    async def get(id: UUID, user: CurrentUser, context: Context) -> O:
        return kind.of(await kind.get(context.master_data, user, kind.id(id)))

    @router.patch(
        "/{id}",
        name=f"change_{kind.name}",
        summary=f"Change a {kind.noun}",
        description=ADMINS_ONLY
        + " A group in `group_ids` (a topic in `topic_ids`) that does not exist is `404`, one "
        "of another scope `422`.",
        response_model=kind.out,
        responses=problem_responses(401, 403, 404, 409, 422),
    )
    @_body(kind.patch_in)
    async def patch(id: UUID, body: P, user: CurrentUser, context: Context) -> O:
        given = kind.arguments(
            {name: value for name, value in body if name in body.model_fields_set}
        )
        return kind.of(await kind.change(context.master_data, user, kind.id(id), **given))

    @router.delete(
        "/{id}",
        name=f"delete_{kind.name}",
        status_code=204,
        summary=f"Delete a {kind.noun}",
        description=ADMINS_ONLY + " Only while no document uses it (409).",
        responses=problem_responses(401, 403, 404, 409, 422),
    )
    async def delete(id: UUID, user: CurrentUser, context: Context) -> None:
        await kind.delete(context.master_data, user, kind.id(id))

    return router


def _body[F: Callable[..., Awaitable[object]]](model: type[BaseModel]) -> Callable[[F], F]:
    """FastAPI reads a body's model from the endpoint's annotation, which in `_simple` is a type
    parameter: this puts the kind's model there."""

    def put(endpoint: F) -> F:
        endpoint.__annotations__["body"] = model
        return endpoint

    return put


class _Counted(Protocol):
    """An answer with a `document_count`."""

    id: UUID

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self: ...


def _with_counts[O: _Counted](items: list[O], counts: Mapping[UUID, int]) -> list[O]:
    """The items with their `document_count` from `counts` (0 for one not counted)."""
    return [item.model_copy(update={"document_count": counts.get(item.id, 0)}) for item in items]


def _identifier(item: IdentifierIn, *, rejected: bool = False) -> Identifier:
    """As written, normalised (ValidationError, 422, if it is none), with its topic; a rejected
    one has none."""
    topic = None if rejected or item.topic_id is None else TagId(item.topic_id)
    user = None if rejected or item.user_id is None else UserId(item.user_id)
    return Identifier.parse(item.kind, item.value, topic_id=topic, user_id=user)


def _document_type_arguments(given: dict[str, Any]) -> dict[str, Any]:
    """The fields of a new type's body as required or not, by field."""
    if given.get("fields") is not None:
        given["fields"] = {FieldId(item.field_id): item.required for item in given["fields"]}
    return given


def _contact_arguments(given: dict[str, Any]) -> dict[str, Any]:
    """The identifiers of a contact's body as `Identifier`s."""
    for key in ("identifiers", "rejected_identifiers"):
        if given.get(key) is not None:
            rejected = key == "rejected_identifiers"
            given[key] = [_identifier(item, rejected=rejected) for item in given[key]]
    return given


contacts = _simple(
    Kind(
        path="contacts",
        noun="contact",
        name="contact",
        plural="contacts",
        id=ContactId,
        list=MasterDataService.list_contacts,
        create=MasterDataService.create_contact,
        get=MasterDataService.get_contact,
        change=MasterDataService.change_contact,
        delete=MasterDataService.delete_contact,
        create_in=ContactCreate,
        patch_in=ContactPatch,
        out=ContactOut,
        of=ContactOut.of,
        counted=CountBy.CONTACT,
        arguments=_contact_arguments,
    )
)


@contacts.post(
    "/{id}/identifiers",
    summary="Attach an identifier to a contact",
    description=(
        ADMINS_ONLY + " Enters one identifier by hand (as found on a document, see `GET "
        "/documents/{id}/facts`), with a topic the contact enables (422 otherwise) or none; the "
        "contact's other identifiers stay as they are. One the contact learned or rejected is "
        "then entered by hand; one another contact learned or rejected moves here; 409 if "
        "another contact has it entered by hand. Documents use it from their next processing "
        "on."
    ),
    response_model=ContactOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def attach_identifier(
    id: UUID, body: IdentifierIn, user: CurrentUser, context: Context
) -> ContactOut:
    identifier = _identifier(body)
    return ContactOut.of(await context.master_data.add_identifier(user, ContactId(id), identifier))


LOGO_PATH = f"{PREFIX}/contacts/{{id}}/logo"
_LOGO_BODY = upload_body(
    f"PNG, JPEG or WebP, recognised by content; at most {LOGO_MAX_SIZE} bytes."
)


@contacts.put(
    "/{id}/logo",
    summary="Upload a contact's logo",
    description=(
        ADMINS_ONLY + " One part `file`: a PNG, JPEG or WebP image of at most 1 MiB (413 "
        "otherwise); another kind, SVG among them, is 415, an image that cannot be read 422. "
        "Lekto keeps it scaled to fit 128 px as WebP, in place of any other logo; a fetched "
        "one never replaces it."
    ),
    response_model=ContactOut,
    responses=problem_responses(400, 401, 403, 404, 413, 415, 422),
    openapi_extra=_LOGO_BODY,
)
async def upload_logo(
    id: UUID, request: Request, user: CurrentUser, context: Context
) -> ContactOut:
    received = await read_upload(request, max_size=LOGO_MAX_SIZE)
    try:
        data = await asyncio.to_thread(received.file.path.read_bytes)
    finally:
        await asyncio.shield(asyncio.to_thread(received.file.path.unlink, missing_ok=True))
    return ContactOut.of(await context.logos.upload(user, ContactId(id), data))


@contacts.delete(
    "/{id}/logo",
    status_code=204,
    summary="Remove a contact's logo",
    description=ADMINS_ONLY + " The contact shows its initials again.",
    responses=problem_responses(401, 403, 404, 422),
)
async def remove_logo(id: UUID, user: CurrentUser, context: Context) -> None:
    await context.logos.remove(user, ContactId(id))


@contacts.post(
    "/{id}/logo/fetch",
    status_code=202,
    summary="Fetch a contact's logo from its website",
    description=(
        ADMINS_ONLY + " Only with `LEKTO_LOGO_FETCH` (503 otherwise; `GET /pipeline` tells, "
        "`logo_fetch`). The worker asks the website at each of the contact's domains in turn "
        "for its icon (HTTPS to public addresses only), also one whose fetch failed before, "
        "and stores the first that fits in place of a fetched logo; `ContactOut.logo` or "
        "`logo_failure` tell the outcome. 409 while the contact has an uploaded logo (it is "
        "never replaced), 422 without a domain among its identifiers."
    ),
    response_class=Response,
    responses={202: {"description": "Queued"}, **problem_responses(401, 403, 404, 409, 422, 503)},
)
async def fetch_logo(id: UUID, user: CurrentUser, context: Context) -> Response:
    await context.logos.request_fetch(user, ContactId(id))
    return Response(status_code=202)


@contacts.get(
    "/{id}/logo",
    summary="A contact's logo",
    description=(
        "Everyone reads it (master data is global): WebP, up to 128 px. Unlike the API's "
        "other answers it may be cached (`Cache-Control: private, max-age=86400`): its URL "
        "in `ContactOut.logo.url` carries its version. 404 without a logo."
    ),
    response_class=Response,
    responses={
        200: {"content": {LOGO_TYPE: {"schema": {"type": "string", "format": "binary"}}}},
        **problem_responses(401, 404, 422),
    },
)
async def get_logo(id: UUID, user: CurrentUser, context: Context) -> Response:
    stored = await context.logos.logo(user, ContactId(id))
    return Response(
        stored.data,
        media_type=LOGO_TYPE,
        headers={"Cache-Control": "private, max-age=86400"},
    )


document_types = _simple(
    Kind(
        path="document-types",
        noun="document type",
        name="document_type",
        plural="document_types",
        id=DocumentTypeId,
        list=MasterDataService.list_document_types,
        create=MasterDataService.create_document_type,
        get=MasterDataService.get_document_type,
        change=MasterDataService.change_document_type,
        delete=MasterDataService.delete_document_type,
        create_in=DocumentTypeCreate,
        patch_in=DocumentTypePatch,
        out=DocumentTypeOut,
        of=DocumentTypeOut.of,
        counted=CountBy.DOCUMENT_TYPE,
        arguments=_document_type_arguments,
    )
)
tags = APIRouter(prefix="/tags", tags=["master data"], dependencies=PROTECTED)


async def _tree(context: ApiContext, user: UserId) -> TagTree:
    return TagTree.of(await context.master_data.list_tags(user))


@tags.get(
    "",
    summary="List tags",
    description=(
        "Tags of every scope, or of `scope`: document tags, contact groups, type groups, "
        "topics. In the order of their trees: each after its parent, siblings by name (scopes "
        "in this order). Everyone reads them. With `document_counts`, each comes with how many "
        "documents within the caller's reach it stands for (`TagOut.document_count`); admins "
        "count every document with `all_users` (others: 403). A contact group or topic comes "
        "with its contacts (`contact_count`), a type group with its document types "
        "(`document_type_count`), whoever asks."
    ),
    response_model=list[TagOut],
    responses=problem_responses(401, 403, 422),
)
async def list_tags(
    user: CurrentUser,
    context: Context,
    scope: TagScope | None = None,
    document_counts: DocumentCounts = False,
    all_users: CountAll = False,
) -> list[TagOut]:
    tree = await _tree(context, user)
    scopes = list(TagScope) if scope is None else [scope]
    found = [TagOut.of(tag, tree) for wanted in scopes for tag in tree.of_scope(wanted)]
    if not document_counts:
        return found
    counts = await context.documents.document_counts(user, CountBy.TAG, all_users=all_users)
    members = await context.master_data.tag_members(user)

    def with_members(item: TagOut) -> TagOut:
        if item.scope in (TagScope.CONTACT, TagScope.TOPIC):
            return item.model_copy(
                update={"contact_count": members.contacts.get(TagId(item.id), 0)}
            )
        if item.scope is TagScope.DOCUMENT_TYPE:
            return item.model_copy(
                update={"document_type_count": members.document_types.get(TagId(item.id), 0)}
            )
        return item

    return [with_members(item) for item in _with_counts(found, counts)]


@tags.post(
    "",
    status_code=201,
    summary="Create a tag",
    description=ADMINS_ONLY + " Names are unique per scope, regardless of case.",
    response_model=TagOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def create_tag(body: TagCreate, user: CurrentUser, context: Context) -> TagOut:
    tag = await context.master_data.create_tag(
        user,
        body.name,
        scope=body.scope,
        parent_id=None if body.parent_id is None else TagId(body.parent_id),
        assignment=body.assignment,
        shown=body.shown,
        icon=body.icon,
        color=body.color,
    )
    return TagOut.of(tag, await _tree(context, user))


@tags.get(
    "/{id}",
    summary="A tag",
    response_model=TagOut,
    responses=problem_responses(401, 404, 422),
)
async def get_tag(id: UUID, user: CurrentUser, context: Context) -> TagOut:
    tag = await context.master_data.get_tag(user, TagId(id))
    return TagOut.of(tag, await _tree(context, user))


@tags.patch(
    "/{id}",
    summary="Change a tag",
    description=(
        ADMINS_ONLY + " Name, parent (of the same scope, not below the tag itself; at most "
        "five levels), assignment, whether documents show it, icon and colour. The scope "
        "stays. A new name or parent brings the search index of the documents concerned up to "
        "date. After a new parent, a job leaves documents (for a group: contacts or document "
        "types) that carry the tag and one now above it only the one below; a topic needs "
        "none."
    ),
    response_model=TagOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def change_tag(id: UUID, body: TagPatch, user: CurrentUser, context: Context) -> TagOut:
    parent: TagId | Unset | None = UNSET
    if "parent_id" in body.model_fields_set:
        parent = None if body.parent_id is None else TagId(body.parent_id)
    given = body.model_fields_set
    tag = await context.master_data.change_tag(
        user,
        TagId(id),
        name=body.name,
        parent_id=parent,
        assignment=body.assignment,
        shown=body.shown,
        icon=body.icon if "icon" in given else UNSET,
        color=body.color if "color" in given else UNSET,
    )
    return TagOut.of(tag, await _tree(context, user))


@tags.delete(
    "/{id}",
    status_code=204,
    summary="Delete a tag",
    description=ADMINS_ONLY
    + " Only a tag without tags below it that nothing uses: no document carries it (as a "
    "tag or its topic), no contact or document type is in it, no contact enables it as a "
    "topic, no rule refers to it (409).",
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def delete_tag(id: UUID, user: CurrentUser, context: Context) -> None:
    await context.master_data.delete_tag(user, TagId(id))


@document_types.put(
    "/{id}/fields",
    summary="Set the fields of a document type",
    description=(
        ADMINS_ONLY + " Exactly these fields belong to the type besides the global ones, each "
        "required or optional; in one transaction. A field taken off is no longer for the "
        "type: 409 while documents of the type have a value for it or the type's title "
        "pattern uses it; 422 for a field of no other type, or a global one. Returns the "
        "fields of the type, global ones aside."
    ),
    response_model=list[FieldOut],
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def assign_fields(
    id: UUID, body: FieldAssignmentsIn, user: CurrentUser, context: Context
) -> list[FieldOut]:
    type_id = DocumentTypeId(id)
    await context.master_data.assign_fields(
        user, type_id, {FieldId(item.field_id): item.required for item in body.fields}
    )
    return [
        FieldOut.of(item)
        for item in await context.master_data.list_fields(user)
        if item.document_type_ids is not None and type_id in item.document_type_ids
    ]


fields = APIRouter(prefix="/fields", tags=["master data"], dependencies=PROTECTED)


@fields.get(
    "",
    summary="List field definitions",
    description=COUNTS,
    response_model=list[FieldOut],
    responses=problem_responses(401, 403, 422),
)
async def list_fields(
    user: CurrentUser,
    context: Context,
    document_counts: DocumentCounts = False,
    all_users: CountAll = False,
) -> list[FieldOut]:
    found = [FieldOut.of(item) for item in await context.master_data.list_fields(user)]
    if not document_counts:
        return found
    counts = await context.documents.document_counts(user, CountBy.FIELD, all_users=all_users)
    return _with_counts(found, counts)


@fields.post(
    "",
    status_code=201,
    summary="Create a field definition",
    description=(
        ADMINS_ONLY + " Global (`document_type_ids` null) or for some document types; `choice` "
        "needs `choices`."
    ),
    response_model=FieldOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def create_field(body: FieldCreate, user: CurrentUser, context: Context) -> FieldOut:
    item = await context.master_data.create_field(
        user,
        body.name,
        body.data_type,
        document_type_ids=(
            None
            if body.document_type_ids is None
            else [DocumentTypeId(id) for id in body.document_type_ids]
        ),
        choices=body.choices,
        required=body.required,
        required_document_type_ids=[DocumentTypeId(id) for id in body.required_document_type_ids],
        description=body.description,
        assignment=body.assignment,
    )
    return FieldOut.of(item)


@fields.get(
    "/{id}",
    summary="A field definition",
    response_model=FieldOut,
    responses=problem_responses(401, 404, 422),
)
async def get_field(id: UUID, user: CurrentUser, context: Context) -> FieldOut:
    return FieldOut.of(await context.master_data.get_field(user, FieldId(id)))


@fields.patch(
    "/{id}",
    summary="Change a field definition",
    description=(
        ADMINS_ONLY + " Name, description, choices and scope; the data type stays. Values "
        "documents use are "
        "never changed: removing a used choice or narrowing the scope past documents with "
        "values is a conflict (409)."
    ),
    response_model=FieldOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def change_field(id: UUID, body: FieldPatch, user: CurrentUser, context: Context) -> FieldOut:
    scope: list[DocumentTypeId] | Unset | None = UNSET
    if "document_type_ids" in body.model_fields_set:
        scope = (
            None
            if body.document_type_ids is None
            else [DocumentTypeId(type_id) for type_id in body.document_type_ids]
        )
    required_types = body.required_document_type_ids
    item = await context.master_data.change_field(
        user,
        FieldId(id),
        name=body.name,
        choices=body.choices,
        document_type_ids=scope,
        required=body.required,
        required_document_type_ids=(
            None if required_types is None else [DocumentTypeId(id) for id in required_types]
        ),
        description=body.description if "description" in body.model_fields_set else UNSET,
        assignment=body.assignment,
    )
    return FieldOut.of(item)


@fields.delete(
    "/{id}",
    status_code=204,
    summary="Delete a field definition",
    description=ADMINS_ONLY + " Only while no document has a value for it (409).",
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def delete_field(id: UUID, user: CurrentUser, context: Context) -> None:
    await context.master_data.delete_field(user, FieldId(id))


ROUTERS = [contacts, document_types, tags, fields]
