"""Contacts, document types, tags, topics and fields by name: the tools take names, not IDs (a
client has no other way to learn IDs), and give names. A name matches regardless of case; an
unknown one is an error that names similar ones, so the client need not list them first."""

import difflib
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from lekto.adapters.inbound.context import ApiContext
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import FieldDefinition
from lekto.core.domain.ids import ContactId, DocumentTypeId, FieldId, TagId, UserId
from lekto.core.domain.master_data import TagScope
from lekto.core.domain.sorting import sort_key
from lekto.core.domain.validation import name_key

SIMILAR = 3
"""Names an error suggests at most."""
_CONTAINED = 3
"""Characters a name has at least to be suggested for standing in the one asked for or it."""


@dataclass(frozen=True)
class Names:
    """The names of contacts, document types, tags and fields (visible to every user)."""

    contacts: dict[UUID, str]
    document_types: dict[UUID, str]
    tags: dict[UUID, str]
    fields: dict[FieldId, FieldDefinition]
    topics: dict[UUID, str]

    @classmethod
    async def load(cls, context: ApiContext, user: UserId) -> "Names":
        master = context.master_data
        return cls(
            contacts={c.id: c.name for c in await master.list_contacts(user)},
            document_types={t.id: t.name for t in await master.list_document_types(user)},
            tags={t.id: t.name for t in await master.list_tags(user, TagScope.DOCUMENT)},
            fields={a.id: a for a in await master.list_fields(user)},
            topics={t.id: t.name for t in await master.list_tags(user, TagScope.TOPIC)},
        )

    def contact(self, id: UUID | None) -> str | None:
        return None if id is None else self.contacts.get(id, str(id))

    def document_type(self, id: UUID | None) -> str | None:
        return None if id is None else self.document_types.get(id, str(id))

    def topic(self, id: UUID | None) -> str | None:
        return None if id is None else self.topics.get(id, str(id))

    def tag_names(self, ids: Iterable[UUID]) -> list[str]:
        return sorted((self.tags.get(i, str(i)) for i in ids), key=sort_key)

    def field_name(self, id: FieldId) -> str:
        definition = self.fields.get(id)
        return str(id) if definition is None else definition.name

    # --- name to id, for input

    def find_contact(self, name: str) -> ContactId:
        return ContactId(find("contact", name, self.contacts))

    def find_document_type(self, name: str) -> DocumentTypeId:
        return DocumentTypeId(find("document type", name, self.document_types))

    def find_tag(self, name: str) -> TagId:
        return TagId(find("tag", name, self.tags))

    def find_topic(self, name: str) -> TagId:
        return TagId(find("topic", name, self.topics))

    def find_field(self, name: str) -> FieldDefinition:
        by_name: dict[UUID, str] = {id: definition.name for id, definition in self.fields.items()}
        return self.fields[FieldId(find("field", name, by_name))]


def find(kind: str, name: str, names: dict[UUID, str]) -> UUID:
    wanted = name_key(name)
    for id, existing in names.items():
        if name_key(existing) == wanted:
            return id
    similar = similar_names(name, names.values())
    hint = f"; similar: {', '.join(similar)}" if similar else ""
    raise ValidationError(f"no {kind} named {name!r}{hint}")


def similar_names(name: str, names: Iterable[str]) -> list[str]:
    """Up to `SIMILAR` of `names` like `name`: those it stands in or that stand in it ("Stadtwerk"
    in "Stadtwerke Musterstadt"), then those spelt alike."""
    wanted = name_key(name)
    keyed = {name_key(existing): existing for existing in names}
    containing = sorted(
        (
            existing
            for key, existing in keyed.items()
            if min(len(key), len(wanted)) >= _CONTAINED and (wanted in key or key in wanted)
        ),
        key=sort_key,
    )
    alike = [keyed[key] for key in difflib.get_close_matches(wanted, keyed, n=SIMILAR)]
    return list(dict.fromkeys(containing + alike))[:SIMILAR]
