"""Small checks shared by the domain model."""

from datetime import UTC, datetime, timedelta

from lekto.core.domain.errors import ValidationError

MAX_NAME = 200
"""Characters of a name: contacts, types, tags, fields, spaces, rules, aliases, choices. The
REST schemas take their limit from here."""


def require_utc(value: datetime, what: str = "timestamp") -> datetime:
    """Timestamps are timezone-aware and in UTC; naive or offset times are rejected."""
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValidationError(f"{what} must be timezone-aware UTC, got {value.isoformat()}")
    return value.astimezone(UTC)


def require_name(value: str, what: str = "name", *, max_length: int | None = MAX_NAME) -> str:
    """Names are stripped, must not be empty and have at most `max_length` characters (None:
    no limit, for values that are not names of Lekto's own, such as file names)."""
    name = value.strip()
    if not name:
        raise ValidationError(f"{what} must not be empty")
    if max_length is not None and len(name) > max_length:
        raise ValidationError(f"{what} must have at most {max_length} characters")
    return name


MAX_URL_LENGTH = 2000
"""Characters of a URL or a path on this site: a webhook's target, where to go after signing
in."""


def has_control_characters(text: str) -> bool:
    """Whether `text` holds a space, a control character or DEL: nothing a URL or a path on
    this site may contain."""
    return any(ord(char) < 0x21 or ord(char) == 0x7F for char in text)


def name_key(name: str) -> str:
    """Comparison key for names that are unique regardless of case."""
    return name.strip().casefold()
