"""Which Paperless documents the plan takes over (`documents:` with `include` and `exclude`).
Pure functions over a document and the names of what it references."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from lekto_migration.mapping import select_options
from lekto_migration.paperless import Snapshot
from lekto_migration.plan import Selection, norm


@dataclass(frozen=True)
class Names:
    """The Paperless objects of a snapshot by id, to name what a document references."""

    users: Mapping[int, str]
    correspondents: Mapping[int, str]
    document_types: Mapping[int, str]
    storage_paths: Mapping[int, str]
    tags: Mapping[int, str]
    custom_fields: Mapping[int, dict[str, Any]]
    members: Mapping[int, frozenset[int]]  # group id -> user ids


def names_of(snapshot: Snapshot) -> Names:
    members: dict[int, set[int]] = {}
    for user in snapshot.users:
        for group in user.get("groups") or []:
            members.setdefault(int(group), set()).add(int(user["id"]))
    return Names(
        users={int(u["id"]): str(u["username"]) for u in snapshot.users},
        correspondents={int(c["id"]): str(c["name"]) for c in snapshot.correspondents},
        document_types={int(t["id"]): str(t["name"]) for t in snapshot.document_types},
        storage_paths={int(p["id"]): str(p["name"]) for p in snapshot.storage_paths},
        tags={int(t["id"]): str(t["name"]) for t in snapshot.tags},
        custom_fields={int(f["id"]): f for f in snapshot.custom_fields},
        members={group: frozenset(users) for group, users in members.items()},
    )


def selected(selection: Selection, document: dict[str, Any], names: Names) -> bool:
    """Every criterion of `include` holds and none of `exclude`."""
    included = all(
        _holds(key, wanted, document, names) for key, wanted in selection.include.items()
    )
    excluded = any(
        _holds(key, wanted, document, names) for key, wanted in selection.exclude.items()
    )
    return included and not excluded


def _holds(key: str, condition: Any, document: dict[str, Any], names: Names) -> bool:
    match key:
        case "id":
            return _number(document.get("id"), condition)
        case "asn":
            return _number(document.get("archive_serial_number"), condition)
        case "title" | "original_file_name":
            return _text(document.get(key), condition)
        case "mime_type":
            return _one_of(document.get("mime_type"), condition)
        case "correspondent" | "document_type" | "storage_path" | "owner":
            lookup = {
                "correspondent": names.correspondents,
                "document_type": names.document_types,
                "storage_path": names.storage_paths,
                "owner": names.users,
            }[key]
            reference = document.get(key)
            return _one_of(None if reference is None else lookup.get(reference), condition)
        case "tags":
            held = {norm(names.tags[t]) for t in document.get("tags") or [] if t in names.tags}
            return _set(held, condition)
        case "shared_with":
            return _set({norm(name) for name in _shared(document, names)}, condition)
        case "created" | "added" | "modified":
            return _when(document.get(key), condition)
        case "has_notes":
            return bool(document.get("notes")) is bool(condition)
        case "custom_fields":
            return isinstance(condition, Mapping) and all(
                _custom_field(str(name), wanted, document, names)
                for name, wanted in condition.items()
            )
    return False


def _one_of(value: str | None, condition: Any) -> bool:
    """A name (or None) is the given one or one of a list (`null` in it: none)."""
    options = condition if isinstance(condition, list) else [condition]
    if value is None:
        return any(option is None for option in options)
    return norm(value) in {norm(str(option)) for option in options if option is not None}


def _set(held: set[str], condition: Any) -> bool:
    """Tags: any of a name or list; or `{any: [...]}`, `{all: [...]}`, `{none: [...]}`."""
    if isinstance(condition, Mapping):
        checks: dict[str, Callable[[set[str]], bool]] = {
            "any": lambda wanted: bool(held & wanted),
            "all": lambda wanted: wanted <= held,
            "none": lambda wanted: not held & wanted,
        }
        return all(
            checks[mode]({norm(str(v)) for v in _list(values)})
            for mode, values in condition.items()
            if mode in checks
        )
    return bool(held & {norm(str(v)) for v in _list(condition)})


def _number(value: Any, condition: Any) -> bool:
    if value is None:
        return condition is None
    if isinstance(condition, Mapping):
        low, high = condition.get("from"), condition.get("to")
        return (low is None or value >= low) and (high is None or value <= high)
    return value in _list(condition)


def _text(value: Any, condition: Any) -> bool:
    """Contains the text (any case), or `{contains: ...}`, `{matches: <regular expression>}`."""
    text = str(value or "")
    if isinstance(condition, Mapping):
        if "matches" in condition:
            try:
                return re.search(str(condition["matches"]), text) is not None
            except re.error:
                return False
        condition = condition.get("contains", "")
    return str(condition).casefold() in text.casefold()


def _when(value: Any, condition: Any) -> bool:
    """A day within `{from: ..., to: ...}` (both included)."""
    if value is None or not isinstance(condition, Mapping):
        return False
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError:
        return False
    low, high = condition.get("from"), condition.get("to")
    return (low is None or day >= _day(low)) and (high is None or day <= _day(high))


def _day(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _shared(document: dict[str, Any], names: Names) -> set[str]:
    """The names of the users who may see or change the document besides its owner."""
    permissions = document.get("permissions") or {}
    ids: set[int] = set()
    for kind in ("view", "change"):
        part = permissions.get(kind) or {}
        ids |= {int(user) for user in part.get("users") or []}
        for group in part.get("groups") or []:
            ids |= names.members.get(int(group), frozenset())
    ids.discard(document.get("owner") or -1)
    return {names.users[user] for user in ids if user in names.users}


def _custom_field(name: str, wanted: Any, document: dict[str, Any], names: Names) -> bool:
    """`true`/`false`: has a value or not; a value or list of them; `{from, to}` for numbers
    and dates."""
    field = next((f for f in names.custom_fields.values() if norm(f["name"]) == norm(name)), None)
    value = None
    if field is not None:
        for item in document.get("custom_fields") or []:
            if int(item["field"]) == int(field["id"]) and item.get("value") not in (None, "", []):
                value = item["value"]
                if field["data_type"] == "select":
                    value = select_options(field).get(str(value), value)
    if isinstance(wanted, bool):
        return (value is not None) is wanted
    if value is None:
        return False
    if isinstance(wanted, Mapping):
        if field is not None and field["data_type"] == "date":
            return _when(value, wanted)
        try:
            number = Decimal(str(value).lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            low, high = wanted.get("from"), wanted.get("to")
            return (low is None or number >= Decimal(str(low))) and (
                high is None or number <= Decimal(str(high))
            )
        except InvalidOperation:
            return False
    return norm(str(value)) in {norm(str(option)) for option in _list(wanted)}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]
