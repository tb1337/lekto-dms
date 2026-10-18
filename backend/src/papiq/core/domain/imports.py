"""Metadata that comes with a document taken over from another system (channel `migration`)."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from papiq.core.domain.documents import UNSET, DocumentChanges
from papiq.core.domain.errors import ValidationError
from papiq.core.domain.fields import FieldDefinition, FieldValue, field_from_json, field_to_json
from papiq.core.domain.ids import ContactId, DocumentTypeId, FieldId, TagId
from papiq.core.domain.json_value import (
    JsonObject,
    JsonValue,
    as_list,
    as_object,
    as_text,
    require_date,
    require_object,
    require_uuid,
)

IMPORTED = "imported"
"""Key of the receive log entry's output that holds the metadata, and the `model_version` of
the nodes that applied it."""


@dataclass(frozen=True, kw_only=True)
class ImportedMetadata:
    """What the source system knew about a document. The classification nodes apply it instead
    of asking the language model. `None` leaves a field unset."""

    title: str | None = None
    contact_id: ContactId | None = None
    document_type_id: DocumentTypeId | None = None
    tag_ids: frozenset[TagId] = frozenset()
    document_date: date | None = None
    fields: Mapping[FieldId, FieldValue] = field(default_factory=dict)

    def classification(self) -> DocumentChanges:
        """Title, contact, type and date as a change; the tags are added separately."""
        return DocumentChanges(
            title=UNSET if self.title is None else self.title,
            contact_id=UNSET if self.contact_id is None else self.contact_id,
            document_type_id=UNSET if self.document_type_id is None else self.document_type_id,
            document_date=UNSET if self.document_date is None else self.document_date,
        )

    def to_json(self) -> JsonObject:
        return {
            "title": self.title,
            "contact_id": None if self.contact_id is None else str(self.contact_id),
            "document_type_id": (
                None if self.document_type_id is None else str(self.document_type_id)
            ),
            "tag_ids": [str(tag) for tag in sorted(self.tag_ids)],
            "document_date": None if self.document_date is None else self.document_date.isoformat(),
            "fields": {str(key): field_to_json(value) for key, value in self.fields.items()},
        }

    @classmethod
    def from_json(
        cls, data: JsonValue, definitions: Mapping[FieldId, FieldDefinition]
    ) -> "ImportedMetadata":
        """Read what `to_json` wrote; the field values are checked against `definitions`."""
        data = require_object(data, "imported metadata")
        try:
            fields: dict[FieldId, FieldValue] = {}
            for key, value in (as_object(data.get("fields")) or {}).items():
                field_id = FieldId(require_uuid(key, "fields"))
                if field_id not in definitions:
                    raise ValidationError(f"field {key} no longer exists")
                fields[field_id] = field_from_json(definitions[field_id], value)
            return cls(
                title=as_text(data.get("title")),
                contact_id=_optional_id(data.get("contact_id"), ContactId, "contact_id"),
                document_type_id=_optional_id(
                    data.get("document_type_id"), DocumentTypeId, "document_type_id"
                ),
                tag_ids=frozenset(
                    TagId(require_uuid(tag, "tag_ids")) for tag in as_list(data.get("tag_ids"))
                ),
                document_date=(
                    None
                    if (day := data.get("document_date")) is None
                    else require_date(day, "document_date")
                ),
                fields=fields,
            )
        except (ValidationError, ValueError, TypeError) as error:
            raise ValidationError(f"imported metadata: {error}") from None


def _optional_id[I](value: JsonValue, kind: Callable[[UUID], I], where: str) -> I | None:
    return None if value is None else kind(require_uuid(value, where))
