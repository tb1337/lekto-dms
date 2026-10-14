"""The values a template sees: plain data, nested in mappings and lists. A value a document
does not have is left out, not given as None: the template tests it with `{% if %}` or
`| default`, and writing it is a missing value (`MissingValueError`)."""

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import PurePath

from papiq.core.domain.documents import Document
from papiq.core.domain.fields import FieldDefinition, FieldValue, Money, Url

type TemplateValue = (
    str
    | int
    | bool
    | Decimal
    | date
    | Money
    | Sequence[TemplateValue]
    | Mapping[str, TemplateValue]
)

type Render = Callable[[str, Mapping[str, TemplateValue]], str]
"""A template renderer's `render` (the port `TemplateRenderer`), as the rule planner takes it."""


# What a template can use; `field.<key>` names a field (`FieldDefinition.key`).
NAMES = (
    "title",
    "filename",
    "original_filename",
    "contact",
    "document_type",
    "document_date",
    "added",
    "tags",
    "drawer",
    "owner",
    "channel",
    "pages",
    "field",
)
FIELD = "field"


def template_values(
    document: Document,
    *,
    contact: str | None,
    document_type: str | None,
    drawer: str | None,
    owner: str | None,
    tags: Iterable[str],
    document_date: date | None,
    fields: Iterable[tuple[FieldDefinition, FieldValue | None]],
) -> dict[str, TemplateValue]:
    """The values of `document` as a template sees them, the names already resolved (as rules
    leave them); what the document does not have is left out."""
    ordered: list[str] = sorted(tags, key=str.casefold)
    names: list[TemplateValue] = [*ordered]
    given: dict[str, TemplateValue | None] = {
        "title": document.title,
        "filename": PurePath(document.original_filename).stem,
        "original_filename": document.original_filename,
        "contact": contact,
        "document_type": document_type,
        "document_date": document_date,
        "added": document.created_at.date(),
        "tags": names,
        "drawer": drawer,
        "owner": owner,
        "channel": document.channel.value,
        "pages": document.page_count,
        FIELD: {definition.key: _field(value) for definition, value in fields if value is not None},
    }
    return {name: value for name, value in given.items() if value is not None}


def _field(value: FieldValue) -> TemplateValue:
    return value.value if isinstance(value, Url) else value


def unknown_values(paths: Iterable[str], field_keys: Collection[str]) -> list[str]:
    """The paths of a template (`TemplateRenderer.check`) that name nothing a template can
    use: an unknown name, or a field that is not among `field_keys`."""
    unknown: list[str] = []
    for path in sorted(paths):
        name, _, rest = path.partition(".")
        known_field = name != FIELD or rest.partition(".")[0] in field_keys
        if name not in NAMES or not known_field:
            unknown.append(path)
    return unknown
