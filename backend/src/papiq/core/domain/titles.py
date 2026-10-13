"""Titles from patterns, for the rule action "set title" and the title pattern of a document
type: text with placeholders for the document's values.

- `{contact}`, `{document_type}`: the names; `{filename}`: the original's name without
  extension;
- `{document_date}` (ISO) or `{document_date:FORMAT}` with the tokens `YYYY`, `YY`, `MM`, `DD`
  and any other characters as they are (`{document_date:YYYY}/{document_date:MM}`);
- in the pattern of a document type also `{field:NAME}`: the value of a field of the type.
"""

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import date

from papiq.core.domain.errors import ValidationError

MAX_PATTERN = 200
PLACEHOLDERS = ("contact", "document_type", "document_date", "filename")
FIELD = "field"

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_DATE_TOKEN = re.compile(r"YYYY|YY|MM|DD")


@dataclass(frozen=True)
class TitleValues:
    """What placeholders stand for; None (or a field left out) has no value."""

    contact: str | None = None
    document_type: str | None = None
    document_date: date | None = None
    filename: str = ""
    fields: Mapping[str, str] = field(default_factory=dict)  # by the field's name


def check_pattern(
    pattern: str, *, with_fields: bool = False, fields: Collection[str] | None = None
) -> str:
    """The pattern stripped, or ValidationError: an unknown placeholder, a date format without
    a token, a field placeholder unless `with_fields` (or `fields` is given), or one for a
    field not in `fields`."""
    pattern = pattern.strip()
    if not pattern:
        raise ValidationError("a title pattern must not be empty")
    if len(pattern) > MAX_PATTERN:
        raise ValidationError(f"a title pattern has at most {MAX_PATTERN} characters")
    for placeholder in _PLACEHOLDER.findall(pattern):
        name, _, argument = placeholder.partition(":")
        if name == FIELD and (with_fields or fields is not None):
            if not argument.strip() or (fields is not None and argument not in fields):
                raise ValidationError(f"{{{placeholder}}}: no such field of the type")
        elif name == "document_date" and argument:
            if not _DATE_TOKEN.search(argument):
                raise ValidationError(f"{{{placeholder}}}: a date format needs YYYY, YY, MM or DD")
        elif name not in PLACEHOLDERS or argument:
            known = [*PLACEHOLDERS, "document_date:FORMAT"]
            if with_fields or fields is not None:
                known.append("field:NAME")
            raise ValidationError(
                f"unknown placeholder {{{placeholder}}}; known: "
                + ", ".join(f"{{{item}}}" for item in known)
            )
    return pattern


def field_names(pattern: str) -> set[str]:
    """The fields a pattern refers to."""
    return {
        argument
        for name, _, argument in (item.partition(":") for item in _PLACEHOLDER.findall(pattern))
        if name == FIELD
    }


def rename_field(pattern: str, old: str, new: str) -> str:
    """The pattern with `{field:old}` written `{field:new}`."""
    return pattern.replace(f"{{{FIELD}:{old}}}", f"{{{FIELD}:{new}}}")


def render(pattern: str, values: TitleValues, *, complete: bool = False) -> str | None:
    """The title: placeholders replaced, runs of white space as one. A placeholder without a
    value is left empty, or, with `complete`, the result is None (a title missing a part is
    no title). None, too, if nothing is left."""
    missing = False

    def value(match: re.Match[str]) -> str:
        nonlocal missing
        name, _, argument = match.group(1).partition(":")
        text: str | None
        match name:
            case "contact":
                text = values.contact
            case "document_type":
                text = values.document_type
            case "filename":
                text = values.filename
            case "document_date":
                when = values.document_date
                text = None if when is None else _date(when, argument)
            case _ if name == FIELD:
                text = values.fields.get(argument)
            case _:
                text = None
        if not text:
            missing = True
            return ""
        return text

    title = " ".join(_PLACEHOLDER.sub(value, pattern).split())
    if not title or (complete and missing):
        return None
    return title


def _date(value: date, form: str) -> str:
    if not form:
        return value.isoformat()
    tokens = {
        "YYYY": f"{value.year:04d}",
        "YY": f"{value.year % 100:02d}",
        "MM": f"{value.month:02d}",
        "DD": f"{value.day:02d}",
    }
    return _DATE_TOKEN.sub(lambda match: tokens[match.group()], form)
