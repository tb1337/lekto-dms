"""What a Paperless document becomes in Lekto by the plan, in terms of Lekto's names: owner,
shares and space, contact, type, topic, tags, groups, date, fields, the reviews it needs, and
where each value came from. Pure functions; `resolve` turns the names into ids.

Every Paperless object the document references contributes the targets of its entry. The
natural ones (a correspondent's contact, the date Paperless has, the space its permissions
need) set a value; a reinterpretation only fills what is empty, unless it has `override`.
Where several compete on equal terms, the value stays as it would be without them, with a
note.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from lekto_migration.directory import Directory
from lekto_migration.mapping import (
    READ_WRITE,
    access_of,
    convert_value,
    document_date,
    document_title,
    field_spec,
    received_at,
    select_options,
)
from lekto_migration.paperless import Snapshot
from lekto_migration.plan import ASN, NATURAL, SECTIONS, Entry, Plan, Target, norm

SUPPORTED = ("application/pdf", "image/jpeg", "image/png", "image/tiff")
NAME_LIMIT = 200
# The targets a document holds several of, by the attribute of `Expected`.
GROUPS = {"tag": "tags", "contact_group": "contact_groups", "type_group": "type_groups"}
NAMED = ("contact", "document_type", "topic", "space")
# The field of the inbox a review of a target opens (`ImportedReview.field`).
REVIEWED = {
    "contact": "contact",
    "document_type": "document_type",
    "topic": "topic",
    "tag": "tags",
    "document_date": "document_date",
}
PERMISSIONS = "the permissions in Paperless"
# Paperless' document attribute of the sections a document references once.
REFERENCES = {
    "correspondents": "correspondent",
    "document_types": "document_type",
    "storage_paths": "storage_path",
}


@dataclass(frozen=True)
class FieldInfo:
    """A Lekto field as it is or will be: its type, its options, the document types it is
    bound to (by name; None: global)."""

    name: str
    data_type: str
    choices: tuple[str, ...] = ()
    document_types: frozenset[str] | None = None


@dataclass
class Expected:
    id: int
    title: str
    filename: str
    media_type: str
    skip: str | None = None
    owner: str | None = None  # Lekto user name; None: the executing admin
    owner_source: str | None = None  # the Paperless owner's name
    shares: tuple[tuple[str, str], ...] = ()  # (Lekto user name, level), by name
    space: str | None = None  # a space of the owner; None: the owner's default space
    contact: str | None = None
    document_type: str | None = None
    topic: str | None = None
    tags: frozenset[str] = frozenset()
    contact_groups: frozenset[str] = frozenset()
    type_groups: frozenset[str] = frozenset()
    document_date: str | None = None
    created_at: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)  # Lekto field name -> value (JSON)
    review: tuple[tuple[str, str | None], ...] = ()  # (reason, `contact`, ..., `field:<name>`)
    sources: dict[str, str] = field(default_factory=dict)  # what -> where it came from
    notes: list[str] = field(default_factory=list)


@dataclass
class Context:
    """What `expect` needs besides the plan and the document."""

    plan: Plan
    snapshot: Snapshot
    fields: Mapping[str, FieldInfo]  # norm(Lekto field name) -> the field
    admin: str  # the executing admin's user name
    inactive: frozenset[str] = frozenset()  # norm(Lekto user names) that can neither own nor share
    now: datetime | None = None
    users: dict[int, dict[str, Any]] = field(init=False)
    custom_fields: dict[int, dict[str, Any]] = field(init=False)
    names: dict[str, dict[int, str]] = field(init=False)

    def __post_init__(self) -> None:
        snapshot = self.snapshot
        self.users = {int(u["id"]): u for u in snapshot.users}
        self.custom_fields = {int(f["id"]): f for f in snapshot.custom_fields}
        self.names = {
            "correspondents": {int(c["id"]): str(c["name"]) for c in snapshot.correspondents},
            "document_types": {int(t["id"]): str(t["name"]) for t in snapshot.document_types},
            "tags": {int(t["id"]): str(t["name"]) for t in snapshot.tags},
            "storage_paths": {int(p["id"]): str(p["name"]) for p in snapshot.storage_paths},
        }


def targets_of(plan: Plan) -> list[tuple[str, Entry, Target]]:
    """Every target in the plan with its section and entry, values tables included."""
    out = []
    for section, entries in [*plan.entries.items(), (ASN, {ASN: plan.asn})]:
        for entry in entries.values():
            for target in entry.targets:
                out.append((section, entry, target))
            for targets in entry.values.values():
                for target in targets:
                    out.append((section, entry, target))
    return out


def field_infos(plan: Plan, directory: Directory, snapshot: Snapshot) -> dict[str, FieldInfo]:
    """Every field the plan names, as Lekto has it or as `prepare` will create it: its type is
    the plan's, else the custom field's, else that of the plan's value."""
    types = {str(t["id"]): str(t["name"]) for t in directory.document_types.values()}
    out: dict[str, FieldInfo] = {}
    for section, entry, target in targets_of(plan):
        if target.to != "field" or target.name is None or norm(target.name) in out:
            continue
        found = directory.find("field", target.name)
        if found is not None:
            bound = found.get("document_type_ids")
            out[norm(target.name)] = FieldInfo(
                str(found["name"]),
                str(found.get("data_type") or "text"),
                tuple(found.get("choices") or ()),
                None if bound is None else frozenset(types.get(str(i), "") for i in bound),
            )
        else:
            data_type = target.type or _natural_type(section, entry, snapshot, target)
            out[norm(target.name)] = FieldInfo(target.name, data_type)
    return out


def _natural_type(section: str, entry: Entry, snapshot: Snapshot, target: Target) -> str:
    if section == ASN:
        return "number"
    if section == "custom_fields" and target in entry.targets:
        source = next(
            (f for f in snapshot.custom_fields if norm(str(f["name"])) == norm(entry.source)),
            None,
        )
        spec = field_spec(source)[0] if source is not None else None
        if spec is not None:
            return spec.data_type
    return _literal_type(target.value)


def _literal_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float | Decimal):
        return "number"
    return "text"


# --- one document -----------------------------------------------------------------------------


@dataclass
class _Candidate:
    value: Any
    source: str
    natural: bool
    override: bool


@dataclass
class _Collected:
    """The targets the objects of one document contribute."""

    single: dict[str, list[_Candidate]] = field(default_factory=dict)
    many: dict[str, set[str]] = field(default_factory=lambda: {k: set() for k in GROUPS.values()})
    reviews: dict[tuple[str, str | None], None] = field(default_factory=dict)

    def offer(self, kind: str, value: Any, source: str, natural: bool, override: bool) -> None:
        self.single.setdefault(kind, []).append(_Candidate(value, source, natural, override))


def expect(document: dict[str, Any], context: Context) -> Expected:
    plan = context.plan
    title, notes = document_title(document)
    expected = Expected(
        id=int(document["id"]),
        title=title,
        filename=str(document.get("original_file_name") or f"document-{document['id']}"),
        media_type=str(document.get("mime_type") or ""),
        notes=notes,
        skip=_skip(document),
    )
    if plan.settings.take_over_added:
        expected.created_at, received = received_at(document, context.now)
        expected.notes += received
    if document.get("notes"):
        count = len(document["notes"])
        expected.notes.append(f"{count} notes are not taken over (Lekto has no notes)")
    further = [v for v in document.get("versions") or [] if not v.get("is_root")]
    if further:
        expected.notes.append(f"{len(further)} further versions of the file are not taken over")

    collected = _Collected()
    _owner(document, context, expected)
    if expected.owner_source is not None:
        owner = plan.entry("users", expected.owner_source)
        if owner is not None:
            _contribute(owner, None, context, expected, collected)
    day = document_date(document)
    if day is not None:
        collected.offer("document_date", day, "Paperless", True, False)
    for section, attribute in REFERENCES.items():
        reference = document.get(attribute)
        if reference is None:
            continue
        name = context.names[section].get(int(reference))
        if name is None:
            expected.notes.append(f"{SECTIONS[section]} {reference} does not exist in Paperless")
        else:
            _from_entry(section, name, None, context, expected, collected)
    for tag in document.get("tags") or []:
        name = context.names["tags"].get(int(tag))
        if name is not None:
            _from_entry("tags", name, None, context, expected, collected)
    for item in document.get("custom_fields") or []:
        custom_field = context.custom_fields.get(int(item["field"]))
        if custom_field is None:
            expected.notes.append(f"custom field {item['field']} does not exist: not taken over")
            continue
        name = str(custom_field["name"]).strip()
        valued = (custom_field, item.get("value"))
        _from_entry("custom_fields", name, valued, context, expected, collected)
    asn = document.get("archive_serial_number")
    if asn is not None:
        _contribute(plan.asn, ({"data_type": "integer"}, asn), context, expected, collected)

    for kind, offered in collected.single.items():
        _apply(kind, offered, expected)
    expected.tags = frozenset(collected.many["tags"])
    expected.contact_groups = frozenset(collected.many["contact_groups"])
    expected.type_groups = frozenset(collected.many["type_groups"])
    _bound_fields(expected, context)
    expected.review = tuple(collected.reviews)
    return expected


def _skip(document: dict[str, Any]) -> str | None:
    mime = str(document.get("mime_type") or "")
    if document.get("deleted_at"):
        return "the document is in Paperless' trash"
    if document.get("root_document") not in (None, document["id"]):
        return f"the file is a version of document {document['root_document']}"
    if mime not in SUPPORTED:
        return f"Lekto takes PDF, JPEG, PNG and TIFF; this file is {mime or 'of unknown type'}"
    return None


def _lekto_user(context: Context, paperless: str) -> str | None:
    """The Lekto user name a Paperless user becomes; None if the plan does not take it over."""
    entry = context.plan.entry("users", paperless)
    if entry is None or entry.dropped:
        return None
    return next((t.name for t in entry.targets if t.to == "user"), None)


def _owner(document: dict[str, Any], context: Context, expected: Expected) -> None:
    """Owner and shares by the plan's users; the fallback owner where there is none."""
    settings = context.plan.settings
    access = access_of(document, context.users)
    expected.notes += access.notes
    owner = None
    if access.owner is not None:
        expected.owner_source = access.owner
        owner = _lekto_user(context, access.owner)
        if owner is None:
            expected.notes.append(f"user '{access.owner}' is not taken over: the fallback owns it")
    if owner is not None and norm(owner) in context.inactive:
        expected.notes.append(f"{owner} is not an active user in Lekto: the fallback owns it")
        owner = None
    expected.owner = owner or settings.fallback_owner
    final = norm(expected.owner or context.admin)
    shares: dict[str, tuple[str, str]] = {}  # norm(name) -> (name, level); writers win
    for name, level in access.shares:
        target = _lekto_user(context, name)
        if target is None:
            expected.notes.append(f"shared with {name}, who is not taken over: not shared")
        elif norm(target) in context.inactive:
            expected.notes.append(f"shared with {name}, not an active user in Lekto: not shared")
        elif norm(target) == final:
            expected.notes.append(f"shared with {name}, who owns the document in Lekto: not shared")
        elif shares.get(norm(target), ("", ""))[1] != READ_WRITE:
            shares[norm(target)] = (target, level)
    expected.shares = tuple(sorted(shares.values(), key=lambda item: norm(item[0])))
    if expected.shares:
        users = ", ".join(
            f"{user} ({'schreiben' if level == READ_WRITE else 'lesen'})"
            for user, level in expected.shares
        )
        expected.space = settings.space_name.replace("{shares}", users)[:NAME_LIMIT]
        expected.sources["space"] = PERMISSIONS


def _from_entry(
    section: str,
    name: str,
    valued: tuple[dict[str, Any], Any] | None,
    context: Context,
    expected: Expected,
    collected: _Collected,
) -> None:
    entry = context.plan.entry(section, name)
    empty = valued is not None and valued[1] in (None, "", [])
    if entry is None:
        if not empty:
            expected.notes.append(f"{SECTIONS[section]} '{name}' is not in the plan")
        return
    if valued is not None and valued[0]["data_type"] == "documentlink":
        if not empty:
            expected.notes.append(f"'{name}': link to documents {valued[1]} is not taken over")
        return
    _contribute(entry, valued, context, expected, collected)


def _contribute(
    entry: Entry,
    valued: tuple[dict[str, Any], Any] | None,
    context: Context,
    expected: Expected,
    collected: _Collected,
) -> None:
    """The targets of one entry for this document, and its review."""
    section = entry.section
    label = f"{SECTIONS.get(section, 'archive serial number')} '{entry.source}'"
    if section == ASN:
        label = "archive serial number"
    value: Any = None
    if valued is not None:
        custom_field, value = valued
        if value in (None, "", []):
            return  # an empty value takes nothing over and asks nothing
        if custom_field.get("data_type") == "select":
            option = select_options(custom_field).get(str(value))
            if option is None:
                expected.notes.append(f"'{entry.source}': option {value!r} does not exist")
                return
            value = option
    reason = entry.review_reason()
    if reason is not None:
        first = entry.targets[0] if entry.targets else None
        collected.reviews[(reason, _reviewed(first, section))] = None
    targets = entry.targets
    if entry.values:
        chosen = next((t for key, t in entry.values.items() if norm(key) == norm(str(value))), None)
        if chosen is None:
            expected.notes.append(f"'{entry.source}': {value!r} is not among the plan's values")
        targets = (*targets, *(chosen or ()))
    for target in targets:
        if target.to == "user":
            continue  # the owner is set apart
        naming = target.to in GROUPS or target.to in NAMED
        if naming and valued is not None and value is False and not target.by_value:
            continue  # a "no" takes nothing that only names something
        natural = NATURAL.get(section) == target.to and target in entry.targets
        name = _name(value) if target.by_value else target.name
        if target.to in GROUPS and name is not None:
            collected.many[GROUPS[target.to]].add(name)
        elif target.to in NAMED and name is not None:
            collected.offer(target.to, name, label, natural, target.override)
        elif target.to == "document_date":
            day = _date(value if valued is not None else target.value)
            if day is None:
                expected.notes.append(f"{label}: {_show(value)} is no date")
            else:
                collected.offer("document_date", day, label, False, target.override)
        elif target.to == "field" and target.name is not None:
            info = context.fields.get(norm(target.name))
            if info is None:
                continue
            converted, note = _field_value(entry, valued, target, info, context)
            if note is not None:
                expected.notes.append(f"'{entry.source}': {note}")
            if converted is not None:
                collected.offer(f"field:{info.name}", converted, label, natural, target.override)


def _reviewed(target: Target | None, section: str) -> str | None:
    """The field of the inbox a review opens: the target's, or the section's natural one."""
    if target is None:
        return None if section in ("custom_fields", ASN) else REVIEWED.get(NATURAL[section] or "")
    if target.to == "field" and target.name is not None:
        return f"field:{target.name}"
    return REVIEWED.get(target.to)


def _apply(kind: str, offered: list[_Candidate], expected: Expected) -> None:
    chosen = _choose(kind, offered, expected)
    if chosen is None:
        return
    if kind == "space" and chosen.source != PERMISSIONS and expected.shares:
        expected.notes.append(
            f"space '{chosen.value}' ({chosen.source}) wins: the permissions are not taken over"
        )
        expected.shares = ()
    expected.sources[kind] = chosen.source
    if kind.startswith("field:"):
        expected.fields[kind.removeprefix("field:")] = chosen.value
    else:
        setattr(expected, kind, chosen.value)


def _choose(kind: str, offered: list[_Candidate], expected: Expected) -> _Candidate | None:
    """The value of a single-valued target: one override; else the natural one; else one
    reinterpretation. Competing ones on equal terms leave it as it would be without them."""
    what = kind.removeprefix("field:").replace("_", " ")
    if kind == "space" and expected.space is not None:
        offered = [*offered, _Candidate(expected.space, PERMISSIONS, True, False)]
    overrides = _distinct([c for c in offered if c.override])
    naturals = _distinct([c for c in offered if c.natural and not c.override])
    others = _distinct([c for c in offered if not c.natural and not c.override])
    if len(overrides) == 1:
        return overrides[0]
    if overrides:
        expected.notes.append(_competing(what, overrides, "the value without them stays"))
    if len(naturals) == 1:
        for other in others:
            if _key(other.value) != _key(naturals[0].value):
                expected.notes.append(
                    f"{what}: {other.source} ({_show(other.value)}) gives way to "
                    f"{naturals[0].source} ({_show(naturals[0].value)})"
                )
        return naturals[0]
    if naturals:
        expected.notes.append(_competing(what, naturals, "none is taken"))
        return None
    if len(others) == 1:
        return others[0]
    if others:
        expected.notes.append(_competing(what, others, "none is taken"))
    return None


def _distinct(candidates: list[_Candidate]) -> list[_Candidate]:
    seen: dict[str, _Candidate] = {}
    for candidate in candidates:
        seen.setdefault(_key(candidate.value), candidate)
    return list(seen.values())


def _key(value: Any) -> str:
    return norm(value) if isinstance(value, str) else repr(value)


def _competing(what: str, candidates: list[_Candidate], outcome: str) -> str:
    named = ", ".join(f"{c.source} ({_show(c.value)})" for c in candidates)
    return f"{what}: {named} compete; {outcome}"


def _bound_fields(expected: Expected, context: Context) -> None:
    """A field bound to document types gets its value only on a document of one of them."""
    for name in list(expected.fields):
        info = context.fields.get(norm(name))
        if info is None or info.document_types is None:
            continue
        kinds = {norm(t) for t in info.document_types}
        if expected.document_type is None or norm(expected.document_type) not in kinds:
            del expected.fields[name]
            expected.notes.append(
                f"'{name}' applies only to some document types: its value is not taken over"
            )


def _field_value(
    entry: Entry,
    valued: tuple[dict[str, Any], Any] | None,
    target: Target,
    info: FieldInfo,
    context: Context,
) -> tuple[Any, str | None]:
    """The value for a Lekto field: the custom field's converted to its type, the serial
    number, or the plan's value."""
    currency = context.plan.settings.currency
    if valued is None or target not in entry.targets:
        return coerce(target.value, _literal_type(target.value), info.data_type, currency)
    custom_field, raw = valued
    if entry.section == ASN:
        return coerce(str(raw), "number", info.data_type, currency)
    converted = convert_value(custom_field, raw, currency)
    if converted.value is None:
        return None, converted.note
    spec = field_spec(custom_field)[0]
    return coerce(converted.value, spec.data_type if spec else "text", info.data_type, currency)


def coerce(value: Any, source: str, data_type: str, currency: str) -> tuple[Any, str | None]:
    """A value of the Lekto type `source` (as JSON) as one of `data_type`; None with a note if
    it does not fit."""
    if value is None:
        return None, None
    if source == data_type and source != "number":
        return value, None
    try:
        return _coerced(value, data_type, currency), None
    except (ValueError, InvalidOperation, TypeError):
        return None, f"{_show(value)} does not fit a field of type {data_type}: not taken over"


def _coerced(value: Any, data_type: str, currency: str) -> Any:
    match data_type:
        case "text" | "choice":
            if isinstance(value, dict):
                return f"{value.get('amount')} {value.get('currency')}"
            if isinstance(value, bool):
                return "yes" if value else "no"
            return str(value).strip() or None
        case "number":
            amount = value.get("amount") if isinstance(value, dict) else value
            if isinstance(amount, bool):
                raise ValueError(amount)
            number = Decimal(str(amount).strip())
            if not number.is_finite():
                raise ValueError(amount)
            return format(number, "f")
        case "amount":
            if isinstance(value, dict):
                return value
            if isinstance(value, bool):
                raise ValueError(value)
            return {"amount": format(Decimal(str(value).strip()), "f"), "currency": currency}
        case "date":
            return date.fromisoformat(str(value).strip()[:10]).isoformat()
        case "boolean":
            if isinstance(value, bool):
                return value
        case "link":
            text = str(value).strip()
            parts = urlsplit(text)
            if parts.scheme in ("http", "https") and parts.hostname and " " not in text:
                return text
    raise ValueError(value)


def _date(value: Any) -> str | None:
    try:
        return date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError:
        return None


def _name(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:NAME_LIMIT] or None


def _show(value: Any) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


__all__ = [
    "GROUPS",
    "NAMED",
    "SUPPORTED",
    "Context",
    "Expected",
    "FieldInfo",
    "coerce",
    "expect",
    "field_infos",
    "targets_of",
]
