"""What a document becomes, in terms of Lekto's ids: who uploads it, its space and metadata,
and the values to compare a migrated document with. Names that do not resolve mean `prepare`
has not run since the plan changed."""

import json
from dataclasses import dataclass, field
from typing import Any

from lekto_migration.directory import Directory
from lekto_migration.expect import Expected

METADATA_LIMIT = 45_000  # bytes of the metadata field (Lekto allows 48 KiB)
MAX_REVIEW_REASON = 500


@dataclass
class Resolved:
    """`values` are the metadata as a document's details show them: `title`, `contact_id`,
    `document_type_id`, `topic_id`, `tag_ids` (sorted), `document_date`, `fields` (by id),
    `created_at`; `review` the reasons for the upload."""

    uploader_id: str
    space_id: str | None  # None: the uploader's personal space
    values: dict[str, Any]
    review: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def metadata(self) -> dict[str, Any]:
        """The upload's metadata: everything but the topic (the upload knows none; the
        alignment after the pipeline sets it)."""
        body = {key: value for key, value in self.values.items() if key != "topic_id"}
        body["review"] = self.review
        return body


def resolve(item: Expected, directory: Directory) -> Resolved:
    missing: list[str] = []

    def id_of(to: str, name: str | None) -> str | None:
        if name is None:
            return None
        found = directory.find(to, name)
        if found is None:
            missing.append(f"{to.replace('_', ' ')} '{name}'")
            return None
        return str(found["id"])

    uploader = (
        directory.find("user", item.uploader) if item.uploader is not None else directory.admin
    )
    if uploader is None:
        missing.append(f"user '{item.uploader}'")
        uploader = directory.admin
    space_id = None
    if item.space is not None:
        space = directory.space(item.space)
        if space is None:
            missing.append(f"space '{item.space}'")
        else:
            space_id = str(space["id"])
    fields: dict[str, Any] = {}
    for name, value in item.fields.items():
        field_id = id_of("field", name)
        if field_id is not None:
            fields[field_id] = value
    tags = sorted(filter(None, (id_of("tag", name) for name in item.tags)))
    values: dict[str, Any] = {
        "title": item.title,
        "contact_id": id_of("contact", item.contact),
        "document_type_id": id_of("document_type", item.document_type),
        "topic_id": id_of("topic", item.topic),
        "tag_ids": tags,
        "document_date": item.document_date,
        "fields": fields,
        "created_at": item.created_at,
    }
    review: list[dict[str, Any]] = []
    for reason, field_name in item.review:
        check = field_name
        if field_name is not None and field_name.startswith("field:"):
            field_id = id_of("field", field_name.removeprefix("field:"))
            check = None if field_id is None else f"field:{field_id}"
        entry: dict[str, Any] = {"reason": reason.text[:MAX_REVIEW_REASON], "field": check}
        if reason.code is not None and directory.review_codes:
            entry |= {"code": reason.code, "params": {"name": reason.name}}
        review.append(entry)
    resolved = Resolved(str(uploader["id"]), space_id, values, review, missing)
    _fit(resolved)
    return resolved


def space_of(resolved: Resolved, directory: Directory) -> str | None:
    """The id of the space the document goes to: its own, else the uploader's personal space
    (None while Lekto has none)."""
    if resolved.space_id is not None:
        return resolved.space_id
    personal = directory.personal_space(resolved.uploader_id)
    return None if personal is None else str(personal["id"])


def _fit(resolved: Resolved) -> None:
    """Leave out the biggest field values until the metadata fits the upload."""
    fields = resolved.values["fields"]
    while len(json.dumps(resolved.metadata())) > METADATA_LIMIT and fields:
        biggest = max(fields, key=lambda key: len(json.dumps(fields[key])))
        del fields[biggest]
        resolved.notes.append("the metadata was too large: one value is not taken over")
