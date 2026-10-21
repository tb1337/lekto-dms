"""The migration plan (`migration-plan.yaml`): what is taken over from Paperless-ngx, and how.

A person edits it; `plan` writes the first one and adds to it later. It is YAML, read and
written with ruamel.yaml, which keeps comments and order. Every Paperless object has an entry
under its name: one target, a list of targets, `drop`, or, for a custom field, a table of its
values. Names are compared without case, as Lekto does.
"""

import io
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

# The sections of Paperless objects, each with what one of them is called in reasons and notes.
SECTIONS: Mapping[str, str] = {
    "users": "user",
    "correspondents": "correspondent",
    "document_types": "document type",
    "tags": "tag",
    "custom_fields": "custom field",
    "storage_paths": "storage path",
}
ASN = "asn"  # the archive serial number: one entry of its own
VALUED = frozenset({"custom_fields", ASN})  # sources that carry a value, not only a name
# Where a section's objects go unless the plan says otherwise: the "natural" target. A
# reinterpretation (any other target) only fills what is empty (`override` aside).
NATURAL: Mapping[str, str | None] = {
    "users": "user",
    "correspondents": "contact",
    "document_types": "document_type",
    "tags": "tag",
    "custom_fields": "field",
    "storage_paths": None,
    ASN: "field",
}

TARGETS = frozenset(
    {
        "user",
        "contact",
        "document_type",
        "topic",
        "tag",
        "contact_group",
        "type_group",
        "field",
        "space",
        "document_date",
    }
)
# Targets that are Lekto tags, by their scope; they can nest (`parent`).
TAG_SCOPES: Mapping[str, str] = {
    "tag": "document",
    "topic": "topic",
    "contact_group": "contact",
    "type_group": "document_type",
}
BY_VALUE = frozenset({"contact", "document_type", "topic", "tag", "contact_group", "type_group"})
DATA_TYPES = frozenset({"text", "number", "amount", "date", "boolean", "choice", "link", "period"})
_TARGET_KEYS = frozenset(
    {"to", "name", "value", "type", "parent", "create", "override", "by_value", "review"}
)
_ENTRY_KEYS = _TARGET_KEYS | {"values"}
_SETTING_KEYS = frozenset(
    {
        "currency",
        "fallback_owner",
        "deactivate_inactive_users",
        "take_over_added",
        "space_name",
        "text_threshold",
    }
)
CRITERIA = frozenset(
    {
        "id",
        "title",
        "correspondent",
        "document_type",
        "storage_path",
        "tags",
        "owner",
        "shared_with",
        "custom_fields",
        "asn",
        "created",
        "added",
        "modified",
        "mime_type",
        "original_file_name",
        "has_notes",
    }
)
_TOP_KEYS = frozenset({"source", "target", "settings", "documents", ASN, *SECTIONS})
MEMBERS = "{members}"  # in `space_name`: every member of a shared space with their role
SHARES = "{shares}"  # before 0.5, when a space had an owner; now an error


def norm(name: str) -> str:
    """Names are compared without case and surrounding space, as Lekto does."""
    return name.strip().casefold()


class PlanError(Exception):
    """The plan cannot be used; `problems` says where and why, one line each."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Target:
    """Where a Paperless object goes in Lekto.

    - `name`: the Lekto object (a user name for `user`); none for `document_date` and with
      `by_value`, where the value of a custom field is the name.
    - `value`: what a field gets from a source without a value of its own (a tag, ...).
    - `type`, `parent`: the data type of a field and the tag above a tag, for `prepare`.
    - `create`: `prepare` creates the object if Lekto lacks it; without, a missing one is an
      error, so that a typing error creates nothing.
    - `override`: a reinterpretation that wins over the natural value of the document.
    """

    to: str
    name: str | None = None
    value: Any = None
    type: str | None = None
    parent: str | None = None
    create: bool = False
    override: bool = False
    by_value: bool = False

    @property
    def scope(self) -> str | None:
        """The Lekto tag scope of a tag-like target."""
        return TAG_SCOPES.get(self.to)


@dataclass(frozen=True)
class Entry:
    """What becomes of one Paperless object. No targets: it is not taken over (`drop`).
    `review`: a reason to have a person look at every document with it ("" for the default
    one), or None."""

    section: str
    source: str
    targets: tuple[Target, ...] = ()
    values: Mapping[str, tuple[Target, ...]] = field(default_factory=dict)
    review: str | None = None

    @property
    def dropped(self) -> bool:
        return not self.targets and not self.values

    def review_reason(self) -> str | None:
        if self.review is None:
            return None
        kind = SECTIONS.get(self.section, "archive serial number")
        return self.review or f"Paperless {kind} '{self.source}': to be checked in Lekto"


@dataclass(frozen=True)
class Settings:
    currency: str = "EUR"  # for amounts without a currency
    # Lekto user name who uploads documents without a (taken over) Paperless owner; None: the
    # executing admin
    fallback_owner: str | None = None
    deactivate_inactive_users: bool = True
    take_over_added: bool = True
    space_name: str = "Geteilt: " + MEMBERS
    text_threshold: float = 0.8  # Lekto's words below this share of Paperless' are listed


@dataclass(frozen=True)
class Selection:
    """Which documents are taken over: `include` (every criterion holds) and `exclude` (one
    is enough), by the attributes of a Paperless document (`select.matches`)."""

    include: Mapping[str, Any] = field(default_factory=dict)
    exclude: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    source: str
    target: str
    settings: Settings
    selection: Selection
    entries: dict[str, dict[str, Entry]]  # section -> norm(Paperless name) -> entry
    asn: Entry

    def entry(self, section: str, name: str) -> Entry | None:
        if section == ASN:
            return self.asn
        return self.entries.get(section, {}).get(norm(name))


# --- reading ----------------------------------------------------------------------------------


def yaml() -> YAML:
    """The YAML of the plan: round trip (comments and order stay), 100 columns."""
    document = YAML()
    document.width = 100
    document.indent(mapping=2, sequence=4, offset=2)
    document.preserve_quotes = True
    return document


def load(path: Path) -> tuple[Plan, CommentedMap]:
    """The plan in `path` and its YAML (to write it back with comments)."""
    try:
        data = yaml().load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise PlanError([f"{path}: {error.strerror}"]) from None
    except Exception as error:  # ruamel.yaml raises several of its own
        raise PlanError([f"{path}: not valid YAML ({type(error).__name__}: {error})"]) from None
    if not isinstance(data, CommentedMap):
        raise PlanError([f"{path}: the plan is a mapping of settings and sections"])
    return parse(data), data


def parse(data: Mapping[str, Any]) -> Plan:
    problems: list[str] = []
    for key in data:
        if key not in _TOP_KEYS:
            problems.append(f"unknown section '{key}'")
    source, target = data.get("source"), data.get("target")
    if not isinstance(source, str) or not source.strip():
        problems.append("source: the address of Paperless")
    if not isinstance(target, str) or not target.strip():
        problems.append("target: the address of Lekto")
    settings = _settings(data.get("settings"), problems)
    selection = _selection(data.get("documents"), problems)
    entries: dict[str, dict[str, Entry]] = {}
    for section in SECTIONS:
        raw = data.get(section)
        entries[section] = {}
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            problems.append(f"{section}: a mapping from Paperless names to their targets")
            continue
        for key, value in raw.items():
            name = str(key).strip()
            if norm(name) in entries[section]:
                problems.append(f"{section}.{name}: the name is in the plan twice")
                continue
            entry = _entry(section, name, value, problems)
            if entry is not None:
                entries[section][norm(name)] = entry
    asn = _entry(ASN, "ASN", data.get(ASN, "drop"), problems) or Entry(ASN, "ASN")
    if problems:
        raise PlanError(problems)
    assert isinstance(source, str) and isinstance(target, str)
    return Plan(source.rstrip("/"), target.rstrip("/"), settings, selection, entries, asn)


def _settings(raw: Any, problems: list[str]) -> Settings:
    if raw is None:
        return Settings()
    if not isinstance(raw, Mapping):
        problems.append("settings: a mapping")
        return Settings()
    for key in raw:
        if key not in _SETTING_KEYS:
            problems.append(f"settings.{key}: unknown setting")
    defaults = Settings()
    currency = raw.get("currency", defaults.currency)
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency):
        problems.append("settings.currency: an ISO 4217 code such as EUR")
        currency = defaults.currency
    owner = raw.get("fallback_owner")
    if owner is not None and (not isinstance(owner, str) or not owner.strip()):
        problems.append("settings.fallback_owner: a Lekto user name, or empty")
        owner = None
    space_name = raw.get("space_name", defaults.space_name)
    if isinstance(space_name, str) and SHARES in space_name:
        problems.append(
            f"settings.space_name: {SHARES} is now {MEMBERS}, which names every member of the "
            "space, the uploader too"
        )
        space_name = defaults.space_name
    elif not isinstance(space_name, str) or MEMBERS not in space_name:
        problems.append(f"settings.space_name: a name with {MEMBERS} for the members")
        space_name = defaults.space_name
    threshold = raw.get("text_threshold", defaults.text_threshold)
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, int | float)
        or not 0 <= threshold <= 1
    ):
        problems.append("settings.text_threshold: a share between 0 and 1")
        threshold = defaults.text_threshold
    flags = {}
    for key in ("deactivate_inactive_users", "take_over_added"):
        value = raw.get(key, getattr(defaults, key))
        if not isinstance(value, bool):
            problems.append(f"settings.{key}: true or false")
            value = getattr(defaults, key)
        flags[key] = value
    return Settings(
        currency=currency.upper(),
        fallback_owner=owner.strip() if isinstance(owner, str) else None,
        space_name=space_name,
        text_threshold=float(threshold),
        **flags,
    )


def _selection(raw: Any, problems: list[str]) -> Selection:
    if raw is None:
        return Selection()
    if not isinstance(raw, Mapping):
        problems.append("documents: a mapping with include and exclude")
        return Selection()
    parts: dict[str, Mapping[str, Any]] = {}
    for key, value in raw.items():
        if key not in ("include", "exclude"):
            problems.append(f"documents.{key}: only include and exclude")
            continue
        if value is None:
            value = {}
        if not isinstance(value, Mapping):
            problems.append(f"documents.{key}: a mapping of criteria")
            continue
        for criterion in value:
            if criterion not in CRITERIA:
                problems.append(f"documents.{key}.{criterion}: unknown criterion")
        parts[key] = dict(value)
    return Selection(include=parts.get("include", {}), exclude=parts.get("exclude", {}))


def _entry(section: str, name: str, raw: Any, problems: list[str]) -> Entry | None:
    where = f"{section}.{name}" if section != ASN else ASN
    if raw is None or raw == "drop":
        return Entry(section, name)
    review = None
    targets: list[Target] = []
    values: dict[str, tuple[Target, ...]] = {}
    if isinstance(raw, Mapping):
        for key in raw:
            if key not in _ENTRY_KEYS:
                problems.append(f"{where}: unknown key '{key}'")
        review = _review(raw.get("review"), where, problems)
        if "to" in raw:
            target = _target(section, where, raw, problems)
            if target is not None:
                targets.append(target)
        elif any(key in raw for key in _TARGET_KEYS - {"to", "review"}):
            problems.append(f"{where}: a target needs 'to'")
        if "values" in raw:
            values = _values(section, where, raw["values"], problems)
    elif isinstance(raw, list):
        for index, item in enumerate(raw):
            if not isinstance(item, Mapping) or "to" not in item:
                problems.append(f"{where}[{index}]: a target with 'to'")
                continue
            for key in item:
                if key not in _TARGET_KEYS:
                    problems.append(f"{where}[{index}]: unknown key '{key}'")
            review = review if review is not None else _review(item.get("review"), where, problems)
            target = _target(section, f"{where}[{index}]", item, problems)
            if target is not None:
                targets.append(target)
    else:
        problems.append(f"{where}: a target, a list of targets or drop")
        return None
    if section == "users" and (targets or values):
        users = [t for t in targets if t.to == "user"]
        if len(users) != 1:
            problems.append(f"{where}: a user goes to exactly one Lekto user (to: user)")
    return Entry(section, name, tuple(targets), values, review)


def _review(raw: Any, where: str, problems: list[str]) -> str | None:
    if raw is None or raw is False:
        return None
    if raw is True:
        return ""
    if isinstance(raw, str) and raw.strip() and len(raw) <= 500:
        return raw.strip()
    problems.append(f"{where}.review: true, or a reason of up to 500 characters")
    return None


def _values(
    section: str, where: str, raw: Any, problems: list[str]
) -> dict[str, tuple[Target, ...]]:
    if section != "custom_fields":
        problems.append(f"{where}.values: only a custom field has values")
        return {}
    if not isinstance(raw, Mapping):
        problems.append(f"{where}.values: a mapping from values to targets")
        return {}
    values: dict[str, tuple[Target, ...]] = {}
    for key, item in raw.items():
        spot = f"{where}.values.{key}"
        items = [] if item in (None, "drop") else item if isinstance(item, list) else [item]
        targets = []
        for target in items:
            if not isinstance(target, Mapping) or "to" not in target:
                problems.append(f"{spot}: a target with 'to', a list of them or drop")
                continue
            # The value is the source here: what a valueless source may do, it may.
            made = _target("tags", spot, target, problems)
            if made is not None:
                targets.append(made)
        values[str(key)] = tuple(targets)
    return values


def _target(section: str, where: str, raw: Mapping[str, Any], problems: list[str]) -> Target | None:
    to = raw.get("to")
    if to not in TARGETS:
        problems.append(f"{where}.to: one of {', '.join(sorted(TARGETS))}")
        return None
    if to == "user" and section != "users":
        problems.append(f"{where}: only a Paperless user goes to a Lekto user")
        return None
    name = raw.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        problems.append(f"{where}.name: a name")
        return None
    by_value = raw.get("by_value", False) is True
    valued = section in VALUED
    if by_value and (not valued or to not in BY_VALUE):
        problems.append(f"{where}.by_value: a custom field's value names a {_by_value_targets()}")
        return None
    if name is None and to != "document_date" and not by_value:
        problems.append(f"{where}: 'name' says which Lekto object")
        return None
    if name is not None and (to == "document_date" or by_value):
        problems.append(f"{where}: no 'name' here")
        return None
    value = raw.get("value")
    if isinstance(value, datetime | date):
        value = value.isoformat()
    if to in ("field", "document_date") and not valued and value is None:
        problems.append(f"{where}: 'value' says what the {to.replace('_', ' ')} gets")
        return None
    if value is not None and (valued or to not in ("field", "document_date")):
        problems.append(f"{where}.value: only for a field or the date from a name alone")
        return None
    if to == "document_date" and value is not None and not _is_date(value):
        problems.append(f"{where}.value: a date such as 2024-01-31")
        return None
    data_type = raw.get("type")
    if data_type is not None and (to != "field" or data_type not in DATA_TYPES):
        problems.append(f"{where}.type: for a field, one of {', '.join(sorted(DATA_TYPES))}")
        return None
    parent = raw.get("parent")
    if parent is not None and (to not in TAG_SCOPES or not isinstance(parent, str)):
        problems.append(f"{where}.parent: the name of the tag above, for a tag, topic or group")
        return None
    flags = {}
    for key in ("create", "override"):
        flag = raw.get(key, False)
        if not isinstance(flag, bool):
            problems.append(f"{where}.{key}: true or false")
            flag = False
        flags[key] = flag
    return Target(
        to=to,
        name=name.strip() if isinstance(name, str) else None,
        value=value,
        type=data_type,
        parent=parent.strip() if isinstance(parent, str) else None,
        by_value=by_value,
        **flags,
    )


def _by_value_targets() -> str:
    return ", ".join(sorted(BY_VALUE))


def _is_date(value: Any) -> bool:
    try:
        date.fromisoformat(str(value))
    except ValueError:
        return False
    return True


# --- writing ----------------------------------------------------------------------------------


def dump(document: CommentedMap, path: Path) -> None:
    """Write the plan; a crash leaves the old file, not half a new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".migration-plan-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            yaml().dump(document, out)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def text(document: CommentedMap) -> str:
    """The plan as YAML text."""
    out = io.StringIO()
    yaml().dump(document, out)
    return out.getvalue()


__all__ = [
    "ASN",
    "NATURAL",
    "SECTIONS",
    "TAG_SCOPES",
    "TARGETS",
    "Entry",
    "Plan",
    "PlanError",
    "Selection",
    "Settings",
    "Target",
    "dump",
    "load",
    "norm",
    "parse",
    "text",
    "yaml",
]
