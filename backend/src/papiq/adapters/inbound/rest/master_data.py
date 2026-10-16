"""Master data: contacts, document types, tags, field definitions. Everyone reads them;
admins change them. Deleting works only for what no document (or field) uses."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from papiq.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from papiq.adapters.inbound.rest.context import ApiContext, Context
from papiq.adapters.inbound.rest.problems import problem_responses
from papiq.adapters.inbound.rest.schemas.common import NameIn
from papiq.adapters.inbound.rest.schemas.master_data import (
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
)
from papiq.core.domain.documents import UNSET, Unset
from papiq.core.domain.errors import ValidationError
from papiq.core.domain.identifiers import Identifier, IdentifierKind
from papiq.core.domain.ids import ContactId, DocumentTypeId, FieldId
from papiq.core.domain.master_data import MasterData
from papiq.core.ports import CountBy

ADMINS_ONLY = "Admins only."
COUNTS = (
    "Everyone reads them. With `document_counts`, each comes with how many documents within "
    "the caller's reach have it (a field: a value for it), counted in one query; admins count "
    "every document with `all_users` (others: 403)."
)
DocumentCounts = Annotated[
    bool, Query(description="Count the documents of each (`document_count`).")
]
AllUsers = Annotated[
    bool, Query(description="Count every user's documents instead of the caller's reach (admins).")
]

type Operation = Callable[..., Awaitable[Any]]


def _simple(
    path: str,
    kind: str,
    plural: str,
    name: str,
    out: type[MasterDataOut],
    create_in: type[BaseModel],
    patch_in: type[BaseModel],
    counted: CountBy,
    *,
    change: str = "rename",
    arguments: Callable[[dict[str, Any]], dict[str, Any]] = lambda given: given,
) -> APIRouter:
    """List, create, read, change (`change`: the service's verb) and delete one kind of named
    master data. The bodies' fields are the service's keyword arguments (as `arguments` turns
    them); a patch passes only the fields given."""
    router = APIRouter(prefix=f"/{path}", tags=["master data"], dependencies=PROTECTED)

    def service(context: ApiContext, action: str) -> Operation:
        operation: Operation = getattr(context.master_data, f"{action}_{name}")
        return operation

    @router.get(
        "",
        name=f"list_{plural}",
        summary=f"List {kind}s",
        description=COUNTS,
        response_model=list[out],  # type: ignore[valid-type]
        responses=problem_responses(401, 403, 422),
    )
    async def list_items(
        user: CurrentUser,
        context: Context,
        document_counts: DocumentCounts = False,
        all_users: AllUsers = False,
    ) -> list[MasterDataOut]:
        operation: Operation = getattr(context.master_data, f"list_{plural}")
        items: list[MasterData] = await operation(user)
        found = [out.of(item) for item in items]
        if not document_counts:
            return found
        counts = await context.documents.document_counts(user, counted, all_users=all_users)
        return [
            item.model_copy(update={"document_count": counts.get(item.id, 0)}) for item in found
        ]

    @router.post(
        "",
        name=f"create_{name}",
        status_code=201,
        summary=f"Create a {kind}",
        description=ADMINS_ONLY + " Names are unique regardless of case.",
        response_model=out,
        responses=problem_responses(401, 403, 409, 422),
    )
    async def create(
        body: create_in,  # type: ignore[valid-type]
        user: CurrentUser,
        context: Context,
    ) -> MasterDataOut:
        given = arguments(cast(BaseModel, body).model_dump())
        return out.of(await service(context, "create")(user, **given))

    @router.get(
        "/{id}",
        name=f"get_{name}",
        summary=f"A {kind}",
        response_model=out,
        responses=problem_responses(401, 404, 422),
    )
    async def get(id: UUID, user: CurrentUser, context: Context) -> MasterDataOut:
        return out.of(await service(context, "get")(user, id))

    @router.patch(
        "/{id}",
        name=f"{change}_{name}",
        summary=f"{change.capitalize()} a {kind}",
        description=ADMINS_ONLY,
        response_model=out,
        responses=problem_responses(401, 403, 404, 409, 422),
    )
    async def patch(
        id: UUID,
        body: patch_in,  # type: ignore[valid-type]
        user: CurrentUser,
        context: Context,
    ) -> MasterDataOut:
        model = cast(BaseModel, body)
        given = arguments(model.model_dump(include=model.model_fields_set))
        return out.of(await service(context, change)(user, id, **given))

    @router.delete(
        "/{id}",
        name=f"delete_{name}",
        status_code=204,
        summary=f"Delete a {kind}",
        description=ADMINS_ONLY + " Only while no document uses it (409).",
        responses=problem_responses(401, 403, 404, 409, 422),
    )
    async def delete(id: UUID, user: CurrentUser, context: Context) -> None:
        await service(context, "delete")(user, id)

    return router


def _contact_arguments(given: dict[str, Any]) -> dict[str, Any]:
    """Identifiers as written, normalised (ValidationError, 422, if one is none)."""
    for key in ("identifiers", "rejected_identifiers"):
        if given.get(key) is not None:
            given[key] = [
                Identifier.parse(IdentifierKind(item["kind"]), item["value"]) for item in given[key]
            ]
    return given


contacts = _simple(
    "contacts", "contact", "contacts", "contact", ContactOut, ContactCreate, ContactPatch,
    CountBy.CONTACT, change="change", arguments=_contact_arguments,
)  # fmt: skip


@contacts.post(
    "/{id}/identifiers",
    summary="Attach an identifier to a contact",
    description=(
        ADMINS_ONLY + " Enters one identifier by hand (as found on a document, see `GET "
        "/documents/{id}/facts`); the contact's other identifiers stay as they are. One the "
        "contact learned or rejected is then entered by hand; one another contact learned or "
        "rejected moves here; 409 if another contact has it entered by hand. Documents use it "
        "from their next processing on."
    ),
    response_model=ContactOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def attach_identifier(
    id: UUID, body: IdentifierIn, user: CurrentUser, context: Context
) -> ContactOut:
    identifier = Identifier.parse(body.kind, body.value)
    return ContactOut.of(await context.master_data.add_identifier(user, ContactId(id), identifier))


document_types = _simple(
    "document-types",
    "document type",
    "document_types",
    "document_type",
    DocumentTypeOut,
    DocumentTypeCreate,
    DocumentTypePatch,
    CountBy.DOCUMENT_TYPE,
    change="change",
)
tags = _simple("tags", "tag", "tags", "tag", MasterDataOut, NameIn, NameIn, CountBy.TAG)


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
    if len({item.field_id for item in body.fields}) != len(body.fields):
        raise ValidationError("each field once")
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
    all_users: AllUsers = False,
) -> list[FieldOut]:
    found = [FieldOut.of(item) for item in await context.master_data.list_fields(user)]
    if not document_counts:
        return found
    counts = await context.documents.document_counts(user, CountBy.FIELD, all_users=all_users)
    return [item.model_copy(update={"document_count": counts.get(item.id, 0)}) for item in found]


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
