"""JSON-compatible values for log entries and job payloads, and reading them back: what a value
holds of the expected type, None (or nothing) for anything else."""

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
