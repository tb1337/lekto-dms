"""What templates and webhook bodies see of a document: its values with the names resolved, as
the document is now."""

from collections.abc import Iterable
from datetime import datetime

from lekto.core.domain.codes import Code
from lekto.core.domain.documents import Document
from lekto.core.domain.fields import FieldDefinition, field_to_json
from lekto.core.domain.ids import DocumentTypeId, EventId
from lekto.core.domain.json_value import JsonObject, JsonValue
from lekto.core.domain.templates import EVENT, TemplateValue, template_values
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.services._access import space_label


async def document_values(
    uow: UnitOfWork,
    document: Document,
    document_type: DocumentTypeId | None,
    fields: Iterable[FieldDefinition],
    codes: Iterable[Code] = (),
) -> dict[str, TemplateValue]:
    """The values a template sees of `document` as it is (`templates.template_values`), its
    facts too (`codes`: those on its pages, for `facts.girocode`)."""
    contact = None if document.contact_id is None else await uow.contacts.find(document.contact_id)
    kind = None if document_type is None else await uow.document_types.find(document_type)
    space = await uow.spaces.find(document.space_id)
    users = {user.id: user for user in await uow.users.list_all()}
    uploader = None if document.uploaded_by is None else users.get(document.uploaded_by)
    names = {tag.id: tag.name for tag in await uow.tags.list_all()}
    tags = [names[id] for id in document.tag_ids if id in names]
    return template_values(
        document,
        contact=None if contact is None else contact.name,
        document_type=None if kind is None else kind.name,
        space=None if space is None else space_label(space, users),
        uploaded_by=None if uploader is None else uploader.label,
        tags=tags,
        document_date=document.document_date,
        fields=[(item, document.fields.get(item.id)) for item in fields],
        contact_groups=[names[id] for id in (contact.group_ids if contact else ()) if id in names],
        document_type_groups=[names[id] for id in (kind.group_ids if kind else ()) if id in names],
        topic=names.get(document.topic_id) if document.topic_id is not None else None,
        kept_facts=await uow.document_facts.of_document(document.id),
        codes=codes,
    )


def document_link(link_base: str | None, document: Document) -> str | None:
    """Where a person opens the document in the web UI; None without `LEKTO_PUBLIC_URL`."""
    if link_base is None:
        return None
    return f"{link_base.rstrip('/')}/ui/documents/{document.id}"


def event_values(event_id: EventId, type: str, occurred_at: datetime) -> dict[str, TemplateValue]:
    """`event` as a webhook's template sees it."""
    return {
        EVENT: {
            "id": str(event_id),
            "type": type,
            "occurred_at": occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    }


async def webhook_values(
    uow: UnitOfWork, document: Document, link_base: str | None, codes: Iterable[Code] = ()
) -> dict[str, TemplateValue]:
    """The values a webhook's template sees of `document`: those of a rule's template (the fields
    of its type, `codes` for `facts.girocode`), its id, lane and link."""
    fields = [
        item for item in await uow.fields.list_all() if item.applies_to(document.document_type_id)
    ]
    values = await document_values(uow, document, document.document_type_id, fields, codes)
    values["document_id"] = str(document.id)
    if document.lane is not None:
        values["lane"] = document.lane.value
    if (link := document_link(link_base, document)) is not None:
        values["link"] = link
    return values


async def document_json(uow: UnitOfWork, document: Document, link_base: str | None) -> JsonObject:
    """The document as a webhook's `full` body shows it: ids with names, the fields of its type
    with a value (by key, in their JSON form), its lane and link."""
    contact = None if document.contact_id is None else await uow.contacts.find(document.contact_id)
    kind = (
        None
        if document.document_type_id is None
        else await uow.document_types.find(document.document_type_id)
    )
    space = await uow.spaces.find(document.space_id)
    users = {user.id: user for user in await uow.users.list_all()}
    tags = {tag.id: tag.name for tag in await uow.tags.list_all()}
    definitions = {item.id: item for item in await uow.fields.list_all()}

    def named(id: object, name: str | None) -> JsonValue:
        return None if id is None or name is None else {"id": str(id), "name": name}

    fields: JsonObject = {
        definitions[id].key: field_to_json(value)
        for id, value in document.fields.items()
        if id in definitions and value is not None
    }
    return {
        "id": str(document.id),
        "title": document.title,
        "original_filename": document.original_filename,
        "contact": named(document.contact_id, None if contact is None else contact.name),
        "document_type": named(document.document_type_id, None if kind is None else kind.name),
        "topic": named(
            document.topic_id, tags.get(document.topic_id) if document.topic_id else None
        ),
        "tags": [
            {"id": str(id), "name": tags[id]}
            for id in sorted(document.tag_ids, key=str)
            if id in tags
        ],
        "document_date": None
        if document.document_date is None
        else document.document_date.isoformat(),
        "added": document.created_at.date().isoformat(),
        "space": named(document.space_id, None if space is None else space_label(space, users)),
        "lane": None if document.lane is None else document.lane.value,
        "channel": document.channel.value,
        "pages": document.page_count,
        "fields": fields,
        "link": document_link(link_base, document),
    }
