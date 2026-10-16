"""Contacts, document types, tags and field definitions: named master data."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Row, delete

from papiq.adapters.outbound.sql import tables as t
from papiq.adapters.outbound.sql.repositories import SqlRepository, Values
from papiq.core.domain.fields import FieldDefinition, FieldType
from papiq.core.domain.identifiers import Identifier, IdentifierKind, IdentifierSource
from papiq.core.domain.ids import ContactId, DocumentTypeId, FieldId, TagId
from papiq.core.domain.master_data import Contact, DocumentType, MasterData, Tag
from papiq.core.domain.validation import name_key


class SqlNamedRepository[K: UUID, E: MasterData](SqlRepository[K, E]):
    async def find_by_name(self, name: str) -> E | None:
        found = await self._load(self.table.c.name_key == name_key(name))
        return found[0] if found else None

    def _values(self, entity: E) -> Values:
        return {
            "id": self._id(entity),
            "name": entity.name,
            "name_key": name_key(entity.name),
            "created_at": entity.created_at,
            "version": entity.version,
        }


class SqlContactRepository(SqlNamedRepository[ContactId, Contact]):
    kind = "contact"
    table = t.contacts

    async def _entities(self, rows: Sequence[Row[Any]]) -> list[Contact]:
        ids = [row.id for row in rows]
        aliases = await self._children(t.contact_aliases, "contact_id", ids)
        identifiers = await self._children(t.contact_identifiers, "contact_id", ids)
        return [
            Contact(
                id=ContactId(row.id),
                name=row.name,
                aliases=[
                    alias.name for alias in sorted(aliases[row.id], key=lambda item: item.position)
                ],
                identifiers=[
                    Identifier(IdentifierKind(item.kind), item.value, IdentifierSource(item.source))
                    for item in identifiers[row.id]
                ],
                created_at=row.created_at,
                version=row.version,
            )
            for row in rows
        ]

    async def _write_children(self, entity: Contact) -> None:
        await self._insert_many(
            t.contact_aliases,
            [
                {
                    "contact_id": entity.id,
                    "name": alias,
                    "name_key": name_key(alias),
                    "position": position,
                }
                for position, alias in enumerate(entity.aliases)
            ],
        )
        await self._insert_many(
            t.contact_identifiers,
            [
                {
                    "contact_id": entity.id,
                    "kind": item.kind.value,
                    "value": item.value,
                    "source": item.source.value,
                }
                for item in entity.identifiers
            ],
        )

    async def _delete_children(self, ids: list[ContactId]) -> None:
        await self._tx.write(
            delete(t.contact_aliases).where(t.contact_aliases.c.contact_id.in_(ids))
        )
        await self._tx.write(
            delete(t.contact_identifiers).where(t.contact_identifiers.c.contact_id.in_(ids))
        )


class SqlDocumentTypeRepository(SqlNamedRepository[DocumentTypeId, DocumentType]):
    kind = "document type"
    table = t.document_types

    def _values(self, entity: DocumentType) -> Values:
        return super()._values(entity) | {
            "description": entity.description,
            "title_pattern": entity.title_pattern,
        }

    def _entity(self, row: Row[Any]) -> DocumentType:
        return DocumentType(
            id=DocumentTypeId(row.id),
            name=row.name,
            description=row.description,
            title_pattern=row.title_pattern,
            created_at=row.created_at,
            version=row.version,
        )


class SqlTagRepository(SqlNamedRepository[TagId, Tag]):
    kind = "tag"
    table = t.tags

    def _entity(self, row: Row[Any]) -> Tag:
        return Tag(id=TagId(row.id), name=row.name, created_at=row.created_at, version=row.version)


class SqlFieldRepository(SqlNamedRepository[FieldId, FieldDefinition]):
    kind = "field"
    table = t.field_definitions

    async def _entities(self, rows: Sequence[Row[Any]]) -> list[FieldDefinition]:
        scopes = await self._children(t.field_document_types, "field_id", (row.id for row in rows))
        return [
            FieldDefinition(
                id=FieldId(row.id),
                name=row.name,
                data_type=FieldType(row.data_type),
                document_type_ids=(
                    None
                    if row.is_global
                    else frozenset(DocumentTypeId(s.document_type_id) for s in scopes[row.id])
                ),
                choices=tuple(row.choices),
                required=row.is_global and row.required,
                required_types=frozenset(
                    DocumentTypeId(s.document_type_id)
                    for s in scopes[row.id]
                    if s.required and not row.is_global
                ),
                description=row.description,
                created_at=row.created_at,
                version=row.version,
            )
            for row in rows
        ]

    def _values(self, entity: FieldDefinition) -> Values:
        return {
            **super()._values(entity),
            "data_type": entity.data_type.value,
            "is_global": entity.document_type_ids is None,
            "required": entity.required,
            "choices": list(entity.choices),
            "description": entity.description,
        }

    async def _write_children(self, entity: FieldDefinition) -> None:
        await self._insert_many(
            t.field_document_types,
            [
                {
                    "field_id": entity.id,
                    "document_type_id": type_id,
                    "required": type_id in entity.required_types,
                }
                for type_id in entity.document_type_ids or ()
            ],
        )

    async def _delete_children(self, ids: list[FieldId]) -> None:
        table = t.field_document_types
        await self._tx.write(delete(table).where(table.c.field_id.in_(ids)))
