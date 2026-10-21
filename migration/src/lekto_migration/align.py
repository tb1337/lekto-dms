"""A migrated document against its source, from three states of each value: what the migration
set last (the state file; for a document migrated before, the metadata of its upload in
Lekto's log), what Lekto has now, and what the plan gives now. A value changes only where
Lekto still has the migration's; what a person or a rule changed since stays and is reported.
Fields and tags the migration never set are not touched."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

SCALARS = ("title", "contact_id", "document_type_id", "topic_id", "document_date", "created_at")
UPDATE, KEPT = "update", "kept"
RECEIPT_SLACK = timedelta(minutes=2)  # a receipt Lekto set itself is the moment of the upload


@dataclass(frozen=True)
class Difference:
    """A value in which Lekto and the plan differ: `update` (the alignment sets the plan's) or
    `kept` (changed in Lekto since the migration set it: it stays)."""

    what: str  # a key of SCALARS, `tag:<id>`, `field:<id>`, `space`
    lekto: Any
    plan: Any
    action: str


@dataclass
class Alignment:
    changes: dict[str, Any] = field(default_factory=dict)  # the body of the PATCH
    move: str | None = None  # the space to move the document to
    differences: list[Difference] = field(default_factory=list)
    applied: dict[str, Any] = field(default_factory=dict)  # what the migration set, afterwards

    @property
    def needed(self) -> bool:
        return bool(self.changes) or self.move is not None


def current(details: Mapping[str, Any]) -> dict[str, Any]:
    """A document's details as values to compare."""
    return {
        **{key: details.get(key) for key in SCALARS},
        "tag_ids": sorted(details.get("tag_ids") or []),
        "fields": dict(details.get("fields") or {}),
        "space_id": details.get("space_id"),
    }


def uploaded(log: list[dict[str, Any]], space_id: str | None) -> dict[str, Any] | None:
    """What the migration set at the upload, from the `receive` entry of the log (documents
    migrated before the state file recorded it); None if it holds no metadata. A receipt it
    did not set is the moment of the upload."""
    entry = next((e for e in log if e.get("node") == "receive"), None)
    if entry is None:
        return None
    imported = (entry.get("output") or {}).get("imported")
    if not isinstance(imported, dict):
        return None
    values = {key: imported.get(key) for key in SCALARS}
    values["topic_id"] = None
    values["created_at"] = imported.get("created_at") or entry.get("started_at")
    values["tag_ids"] = sorted(imported.get("tag_ids") or [])
    values["fields"] = dict(imported.get("fields") or {})
    values["space_id"] = space_id
    return values


def align(
    base: Mapping[str, Any],
    now: Mapping[str, Any],
    want: Mapping[str, Any],
    *,
    parents: Mapping[str, str | None],
    types: Mapping[str, str],
    unmanaged: Collection[str] = (),
) -> Alignment:
    """What to change so that Lekto has the plan's values where it still has the migration's.
    `parents`: the tag above each tag (Lekto keeps a child set with its parent as the child
    alone); `types`: the data type of each field; `unmanaged`: fields left alone."""
    result = Alignment(applied={**base, "fields": dict(base.get("fields") or {})})
    for key in SCALARS:
        wanted = want.get(key)
        if key == "created_at" and wanted is None:
            continue  # not taken over: Lekto's receipt stays
        have, had = now.get(key), base.get(key)
        same = _moment if key == "created_at" else _equal
        if same(have, wanted):
            result.applied[key] = wanted
            continue
        if same(have, had) or (key == "created_at" and _near(have, had)):
            result.changes[key] = wanted
            result.applied[key] = wanted
            result.differences.append(Difference(key, have, wanted, UPDATE))
        else:
            result.differences.append(Difference(key, have, wanted, KEPT))
    _tags(base, now, want, parents, result)
    _fields(base, now, want, types, unmanaged, result)
    space, before, wanted_space = now.get("space_id"), base.get("space_id"), want.get("space_id")
    if wanted_space is not None and space == wanted_space:
        result.applied["space_id"] = wanted_space
    elif wanted_space is not None:
        if before is None or space == before:
            result.move = wanted_space
            result.applied["space_id"] = wanted_space
            result.differences.append(Difference("space", space, wanted_space, UPDATE))
        else:
            result.differences.append(Difference("space", space, wanted_space, KEPT))
    return result


def _tags(
    base: Mapping[str, Any],
    now: Mapping[str, Any],
    want: Mapping[str, Any],
    parents: Mapping[str, str | None],
    result: Alignment,
) -> None:
    held = set(now.get("tag_ids") or [])
    had, wanted = set(base.get("tag_ids") or []), set(want.get("tag_ids") or [])
    held_all, had_all, wanted_all = (_with_ancestors(s, parents) for s in (held, had, wanted))
    add = {t for t in wanted if t not in held_all and t not in had_all}
    remove = {t for t in had if t in held and t not in wanted_all}
    for tag in sorted(wanted - held_all - add):
        result.differences.append(Difference(f"tag:{tag}", None, tag, KEPT))  # removed in Lekto
    for tag in sorted(add):
        result.differences.append(Difference(f"tag:{tag}", None, tag, UPDATE))
    for tag in sorted(remove):
        result.differences.append(Difference(f"tag:{tag}", tag, None, UPDATE))
    if add or remove:
        result.changes["tag_ids"] = sorted((held - remove) | add)
    result.applied["tag_ids"] = sorted((had - remove) | add)


def _fields(
    base: Mapping[str, Any],
    now: Mapping[str, Any],
    want: Mapping[str, Any],
    types: Mapping[str, str],
    unmanaged: Collection[str],
    result: Alignment,
) -> None:
    have, had = now.get("fields") or {}, base.get("fields") or {}
    wanted = want.get("fields") or {}
    changes: dict[str, Any] = {}
    applied = result.applied["fields"]
    for field_id in sorted(set(wanted) | set(had)):
        if field_id in unmanaged:
            continue
        data_type = types.get(field_id, "text")
        value, before, target = have.get(field_id), had.get(field_id), wanted.get(field_id)
        if same_value(value, target, data_type):
            _set(applied, field_id, target)
        elif same_value(value, before, data_type):
            changes[field_id] = target
            _set(applied, field_id, target)
            result.differences.append(Difference(f"field:{field_id}", value, target, UPDATE))
        else:
            result.differences.append(Difference(f"field:{field_id}", value, target, KEPT))
    if changes:
        result.changes["fields"] = changes


def _set(values: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        values.pop(key, None)
    else:
        values[key] = value


def _with_ancestors(ids: set[str], parents: Mapping[str, str | None]) -> set[str]:
    found: set[str] = set()
    for id in ids:
        current: str | None = id
        while current is not None and current not in found:
            found.add(current)
            current = parents.get(current)
    return found


def _equal(have: Any, want: Any) -> bool:
    return (have or None) == (want or None)


def _moment(have: Any, want: Any) -> bool:
    if have is None or want is None:
        return have is None and want is None
    try:
        return datetime.fromisoformat(str(have)) == datetime.fromisoformat(str(want))
    except ValueError:
        return False


def _near(have: Any, had: Any) -> bool:
    """A receipt within moments of the upload: Lekto set it, nobody changed it."""
    try:
        return abs(datetime.fromisoformat(str(have)) - datetime.fromisoformat(str(had))) <= (
            RECEIPT_SLACK
        )
    except (TypeError, ValueError):
        return False


def same_value(have: Any, want: Any, data_type: str) -> bool:
    """Field values are equal; numbers and amounts by value (`12` and `1.2E+1`)."""
    if have is None or want is None:
        return have is None and want is None
    try:
        if data_type == "amount" and isinstance(have, dict) and isinstance(want, dict):
            return have.get("currency") == want.get("currency") and Decimal(
                str(have.get("amount"))
            ) == Decimal(str(want.get("amount")))
        if data_type == "number":
            return Decimal(str(have)) == Decimal(str(want))
    except InvalidOperation:
        return False
    return bool(have == want)
