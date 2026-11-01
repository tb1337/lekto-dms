"""The tools of the master data: contacts, document types, fields and tags, read only (Tobi,
01.11.2026: master data is changed in the web UI)."""

from collections.abc import Iterable
from typing import Annotated, Literal

from mcp.server.mcpserver import Context
from pydantic import BaseModel, Field

from lekto.adapters.inbound.context import ApiContext
from lekto.adapters.inbound.mcp.names import Names
from lekto.adapters.inbound.mcp.output import compact
from lekto.adapters.inbound.mcp.registry import Tools, principal_of
from lekto.core.domain.identifiers import IdentifierSource
from lekto.core.domain.ids import TagId
from lekto.core.domain.master_data import Contact, TagScope
from lekto.core.domain.tag_tree import TagTree
from lekto.core.ports.repository import DocumentFilter

PATH_SEPARATOR = " / "
type Scope = Literal["document", "contact", "document_type", "topic"]
"""`TagScope` as a parameter: the enum would put its docstring into the schema."""


class IdentifierOut(BaseModel):
    kind: str
    value: str
    learned: bool | None  # training found it; else entered by hand
    topic: str | None
    person: bool | None  # a number that names a user (only they and admins see it)


class ContactOut(BaseModel):
    name: str
    aliases: list[str]
    groups: list[str]
    topics: list[str]
    documents: int
    identifiers: list[IdentifierOut] = []


class ContactsOut(BaseModel):
    contacts: list[ContactOut]


class DocumentTypeOut(BaseModel):
    name: str
    description: str | None
    groups: list[str]
    fields: list[str]
    relation_target: bool | None
    documents: int


class DocumentTypesOut(BaseModel):
    document_types: list[DocumentTypeOut]


class FieldOut(BaseModel):
    name: str
    type: str
    description: str | None
    choices: list[str]
    document_types: list[str] | None  # none: every type
    required: bool | None


class FieldsOut(BaseModel):
    fields: list[FieldOut]


class TagsOut(BaseModel):
    """The tags of each scope asked for, each as its path from the top-level tag down."""

    document: list[str] | None = None
    contact: list[str] | None = None
    document_type: list[str] | None = None
    topic: list[str] | None = None


def add_master_data_tools(tools: Tools, context: ApiContext) -> None:
    @tools.read(
        "contacts_list",
        "The contacts by name, with aliases, groups, topics and how many of your documents "
        "they have; query keeps those whose name or alias holds it. Master data are changed "
        "in the web UI.",
    )
    async def contacts_list(
        ctx: Context, query: Annotated[str | None, Field(max_length=100)] = None
    ) -> str:
        user = principal_of(ctx).id
        names = await Names.load(context, user)
        counts = (await context.documents.facets(user, DocumentFilter())).contacts
        wanted = None if query is None else query.casefold()
        return compact(
            ContactsOut(
                contacts=[
                    _contact(contact, names, counts.get(contact.id, 0))
                    for contact in await context.master_data.list_contacts(user)
                    if wanted is None
                    or any(wanted in name.casefold() for name in (contact.name, *contact.aliases))
                ]
            )
        )

    @tools.read(
        "contacts_get",
        "A contact by name with its identifiers you may see (IBAN, customer number, ...): "
        "entered by hand or learned by training, with their topic.",
    )
    async def contacts_get(ctx: Context, name: str) -> str:
        user = principal_of(ctx).id
        names = await Names.load(context, user)
        contact = await context.master_data.get_contact(user, names.find_contact(name))
        counts = (await context.documents.facets(user, DocumentFilter())).contacts
        out = _contact(contact, names, counts.get(contact.id, 0))
        out.identifiers = [
            IdentifierOut(
                kind=item.kind.value,
                value=item.value,
                learned=True if item.source is IdentifierSource.LEARNED else None,
                topic=names.topic(item.topic_id),
                person=True if item.user_id is not None else None,
            )
            for item in contact.identifiers
        ]
        return compact(out)

    @tools.read(
        "document_types_list",
        "The document types by name, with groups, the fields that apply to them, whether "
        "relations point to them (relation_target: contracts) and how many of your documents "
        "they have.",
    )
    async def document_types_list(ctx: Context) -> str:
        user = principal_of(ctx).id
        names = await Names.load(context, user)
        counts = (await context.documents.facets(user, DocumentFilter())).document_types
        fields = list(names.fields.values())
        return compact(
            DocumentTypesOut(
                document_types=[
                    DocumentTypeOut(
                        name=item.name,
                        description=item.description,
                        groups=_paths(names, item.group_ids),
                        fields=sorted(field.name for field in fields if field.applies_to(item.id)),
                        relation_target=item.relation_target or None,
                        documents=counts.get(item.id, 0),
                    )
                    for item in await context.master_data.list_document_types(user)
                ]
            )
        )

    @tools.read(
        "fields_list",
        "The custom fields by name with their type (text, number, amount, date, boolean, "
        "choice, link, period), choices, the document types they apply to (none: every type).",
    )
    async def fields_list(ctx: Context) -> str:
        user = principal_of(ctx).id
        names = await Names.load(context, user)
        return compact(
            FieldsOut(
                fields=[
                    FieldOut(
                        name=item.name,
                        type=item.data_type.value,
                        description=item.description,
                        choices=list(item.choices),
                        document_types=(
                            None
                            if item.document_type_ids is None
                            else sorted(
                                name
                                for id in item.document_type_ids
                                if (name := names.document_type(id)) is not None
                            )
                        ),
                        required=item.required or None,
                    )
                    for item in sorted(names.fields.values(), key=lambda item: item.name)
                ]
            )
        )

    @tools.read(
        "tags_list",
        "The tags by scope, in the order of their trees, each as its path from the top ' / ' "
        "between names; the other tools take a tag's own name. document: tags of documents "
        "(a tag finds those below it too); topic: topics (the topic of a document); contact "
        "and document_type: groups of contacts and types.",
    )
    async def tags_list(
        ctx: Context, scope: Annotated[Scope | None, Field(description="Default: all.")] = None
    ) -> str:
        user = principal_of(ctx).id
        tree = TagTree.of(await context.master_data.list_tags(user))
        scopes = list(TagScope) if scope is None else [TagScope(scope)]
        return compact(
            TagsOut.model_validate(
                {
                    wanted.value: [
                        PATH_SEPARATOR.join(tree.path(tag.id)) for tag in tree.of_scope(wanted)
                    ]
                    for wanted in scopes
                }
            )
        )


def _contact(contact: Contact, names: Names, documents: int) -> ContactOut:
    return ContactOut(
        name=contact.name,
        aliases=list(contact.aliases),
        groups=_paths(names, contact.group_ids),
        topics=sorted(name for id in contact.topic_ids if (name := names.topic(id)) is not None),
        documents=documents,
    )


def _paths(names: Names, ids: Iterable[TagId]) -> list[str]:
    """The names of groups `ids` (of contacts or types: `scope`)."""
    return sorted(name for id in ids if (name := names.groups.get(id)) is not None)
