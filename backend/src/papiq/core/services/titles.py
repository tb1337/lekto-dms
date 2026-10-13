"""The title the machine gives a document: its type's title pattern rendered with the
document's values, or else the language model's proposal.

A title is the machine's as long as the document has it and the log shows the fields node
gave it (or it is the file name): the fields node may replace it. A title a person or a rule
gave stays.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import PurePath

from papiq.core.domain.classification import TITLE, checks_from_json
from papiq.core.domain.documents import Document
from papiq.core.domain.errors import ValidationError
from papiq.core.domain.fields import FieldDefinition, Money, Url
from papiq.core.domain.ids import FieldId
from papiq.core.domain.master_data import Contact, DocumentType
from papiq.core.domain.pipeline import Node, NodeRun
from papiq.core.domain.titles import TitleValues, render


def file_title(document: Document) -> str:
    """The title a document is received with: its file name without the extension."""
    return PurePath(document.original_filename).stem or document.original_filename


def machine_title(log: Sequence[NodeRun]) -> str | None:
    """The title the machine gave last: the fields node's title check."""
    for entry in reversed(log):
        if entry.node is not Node.FIELDS:
            continue
        try:
            checks = checks_from_json(entry.result.output.get("fields"))
        except ValidationError:
            continue
        for check in checks:
            if check.field == TITLE and isinstance(check.value, str):
                return check.value
    return None


def has_machine_title(document: Document, log: Sequence[NodeRun]) -> bool:
    """Whether the document's title is the file name or the one the machine gave last."""
    return document.title in (file_title(document), machine_title(log))


def pattern_title(
    document: Document,
    document_type: DocumentType | None,
    contact: Contact | None,
    definitions: Sequence[FieldDefinition],
    fields: Mapping[FieldId, object] | None = None,
) -> str | None:
    """The type's title pattern rendered with the document's values (`fields` over its own);
    None without a pattern, or if a value the pattern names is missing."""
    pattern = document_type.title_pattern if document_type is not None else None
    if document_type is None or not pattern:
        return None
    values = {**document.fields, **(fields or {})}
    return render(
        pattern,
        TitleValues(
            contact=None if contact is None else contact.name,
            document_type=document_type.name,
            document_date=document.document_date,
            filename=file_title(document),
            fields={
                definition.name: text
                for definition in definitions
                if (text := _text(values.get(definition.id))) is not None
            },
        ),
        complete=True,
    )


def _text(value: object) -> str | None:
    match value:
        case None | bool():
            return None
        case Money():
            return f"{value.amount} {value.currency}"
        case Url():
            return value.value
        case date():
            return value.isoformat()
        case _:
            return str(value)
