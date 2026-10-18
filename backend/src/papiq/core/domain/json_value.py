"""JSON-compatible values for log entries and job payloads, and reading them back: what a value
holds of the expected type, None (or nothing) for anything else. The `require_` readers are for
input that must fit: a ValidationError that names the place otherwise."""

from datetime import date
from uuid import UUID

from papiq.core.domain.errors import ValidationError

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]


def as_text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None


def as_int(value: JsonValue) -> int | None:
    """A whole number; a truth value is none, although Python counts `True` as 1."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def as_number(value: JsonValue) -> float | None:
    """A whole or decimal number as a float; a truth value is none."""
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def as_bool(value: JsonValue) -> bool | None:
    return value if isinstance(value, bool) else None


def as_list(value: JsonValue) -> list[JsonValue]:
    """A list; empty for anything else."""
    return value if isinstance(value, list) else []


def as_texts(value: JsonValue) -> tuple[str, ...]:
    """The texts of a list; empty for anything else."""
    return tuple(item for item in as_list(value) if isinstance(item, str))


def as_object(value: JsonValue) -> JsonObject | None:
    return value if isinstance(value, dict) else None


def as_date(value: JsonValue) -> date | None:
    """A date as ISO 8601 text (YYYY-MM-DD)."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def as_uuid(value: JsonValue) -> UUID | None:
    """An id as text."""
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def require_object(value: JsonValue, where: str) -> JsonObject:
    found = as_object(value)
    if found is None:
        raise ValidationError(f"{where}: expected an object")
    return found


def require_date(value: JsonValue, where: str) -> date:
    found = as_date(value)
    if found is None:
        raise ValidationError(f"{where}: {value!r} is no date (YYYY-MM-DD)")
    return found


def require_uuid(value: JsonValue, where: str) -> UUID:
    found = as_uuid(value)
    if found is None:
        raise ValidationError(f"{where}: {value!r} is no id")
    return found
