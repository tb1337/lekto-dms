"""The first migration plan from what Paperless and Lekto hold, and what changed in Paperless
since: new objects get their default entry, gone ones a note. A person's entries and comments
stay as they are."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ruamel.yaml.comments import CommentedMap

from lekto_migration.directory import Directory
from lekto_migration.mapping import field_spec
from lekto_migration.paperless import Snapshot
from lekto_migration.plan import ASN, SECTIONS, norm

HEADER = """\
Lekto migration plan: what is taken over from Paperless-ngx, and how (migration/README.md).
Every Paperless object has an entry under its name: {to: <target>, name: <Lekto name>}, a list
of such targets, or drop. Targets: user, contact, document_type, topic, tag, contact_group,
type_group, field (with value: from a name alone), space, document_date.
create: true lets `prepare` create what Lekto lacks (without it, a missing target is an error);
review: true, or a reason, has a person look at every document with it in Lekto;
override: true lets a reinterpretation win over what the document has anyway.
A custom field may map its values: values: {<value>: <target>}, or by_value: true (the value
is the name). `plan` adds what is new in Paperless and marks what is gone; it asks first."""

SETTINGS: tuple[tuple[str, Any, str], ...] = (
    ("currency", "EUR", "for amounts without a currency"),
    ("fallback_owner", None, "Lekto user name for documents without an owner; empty: you"),
    ("deactivate_inactive_users", True, "users inactive in Paperless, at the end of a run"),
    ("take_over_added", True, "when a document came in at Paperless becomes its receipt"),
    ("space_name", "Geteilt: {shares}", "the space of shared documents; {shares}: the users"),
    ("text_threshold", 0.8, "check lists documents Lekto read fewer words of than this share"),
)
COMMENTS = {
    "documents": "Which documents: include (every criterion holds), exclude (one is enough).",
    "storage_paths": "Lekto has no storage paths; drop, or a tag or space each.",
    ASN: "The archive serial number.",
}
NEW, GONE = "new in Paperless", "not in Paperless"


@dataclass
class Changes:
    """What `merge` changed: entries added, entries marked as gone (`section.name`)."""

    added: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.added or self.gone)


def flow(**items: Any) -> CommentedMap:
    """A target in one line: `{to: tag, name: tax}`."""
    target = CommentedMap((key, value) for key, value in items.items() if value is not None)
    target.fa.set_flow_style()
    return target


def defaults(snapshot: Snapshot, directory: Directory) -> dict[str, dict[str, Any]]:
    """The default entry of every Paperless object, by section and name; the first spelling
    of a name stands for all (Lekto's names are unique regardless of case)."""
    out: dict[str, dict[str, Any]] = {section: {} for section in SECTIONS}

    def put(section: str, name: str, entry: Any) -> None:
        if all(norm(other) != norm(name) for other in out[section]):
            out[section][name] = entry

    def missing(to: str, name: str) -> bool | None:
        return True if directory.find(to, name) is None else None

    for user in snapshot.users:
        name = str(user["username"])
        put("users", name, flow(to="user", name=name, create=missing("user", name)))
    for section, items, to in (
        ("correspondents", snapshot.correspondents, "contact"),
        ("document_types", snapshot.document_types, "document_type"),
    ):
        for item in items:
            name = str(item["name"]).strip()
            put(section, name, flow(to=to, name=name, create=missing(to, name)))
    tags = {int(tag["id"]): str(tag["name"]).strip() for tag in snapshot.tags}
    for tag in snapshot.tags:
        name = str(tag["name"]).strip()
        parent = tags.get(int(tag["parent"])) if tag.get("parent") else None
        put("tags", name, flow(to="tag", name=name, parent=parent, create=missing("tag", name)))
    for custom_field in snapshot.custom_fields:
        name = str(custom_field["name"]).strip()
        spec, _ = field_spec(custom_field)
        if spec is None:
            put("custom_fields", name, "drop")
            continue
        found = directory.find("field", name)
        put(
            "custom_fields",
            name,
            flow(
                to="field",
                name=name,
                type=None if found else spec.data_type,
                create=None if found else True,
            ),
        )
    for path in snapshot.storage_paths:
        put("storage_paths", str(path["name"]).strip(), "drop")
    return out


def asn_default(snapshot: Snapshot, directory: Directory) -> Any:
    if not any(d.get("archive_serial_number") is not None for d in snapshot.documents):
        return "drop"
    found = directory.find("field", "ASN")
    return flow(
        to="field",
        name="ASN",
        type=None if found else "number",
        create=None if found else True,
    )


def draft(snapshot: Snapshot, directory: Directory, *, source: str, target: str) -> CommentedMap:
    """The first plan: settings, an empty selection and every object's default entry."""
    document = CommentedMap()
    document.yaml_set_start_comment(HEADER)
    document["source"] = source
    document["target"] = target
    settings = CommentedMap()
    for key, value, comment in SETTINGS:
        settings[key] = value
        settings.yaml_add_eol_comment(comment, key)
    document["settings"] = settings
    selection = CommentedMap()
    selection["include"] = flow()
    selection["exclude"] = flow()
    document["documents"] = selection
    entries = defaults(snapshot, directory)
    for section in SECTIONS:
        block = CommentedMap()
        for name, entry in entries[section].items():
            block[name] = entry
        if not block:
            block = flow()
        document[section] = block
        _unsupported(snapshot, section, block)
    document[ASN] = asn_default(snapshot, directory)
    for key, comment in COMMENTS.items():
        document.yaml_set_comment_before_after_key(key, before="\n" + comment)
    for section in SECTIONS:
        if section not in COMMENTS:
            document.yaml_set_comment_before_after_key(section, before="\n")
    return document


def merge(document: CommentedMap, snapshot: Snapshot, directory: Directory, today: date) -> Changes:
    """Add the default entry of every Paperless object the plan lacks and mark the entries of
    objects Paperless no longer has; everything else stays."""
    changes = Changes()
    entries = defaults(snapshot, directory)
    for section in SECTIONS:
        block = document.get(section)
        if not isinstance(block, CommentedMap):
            block = CommentedMap()
            document[section] = block
        if block.fa.flow_style() and not block:
            block.fa.set_block_style()
        known = {norm(str(name)) for name in block}
        for name, entry in entries[section].items():
            if norm(name) not in known:
                block[name] = entry
                block.yaml_add_eol_comment(f"{NEW} ({today.isoformat()})", name)
                changes.added.append(f"{section}.{name}")
        present = {norm(name) for name in entries[section]}
        for name in list(block):
            if norm(str(name)) in present or _comment(block, name).startswith(GONE):
                continue
            block.yaml_add_eol_comment(f"{GONE} ({today.isoformat()})", name)
            changes.gone.append(f"{section}.{name}")
        _unsupported(snapshot, section, block)
    if ASN not in document:
        document[ASN] = asn_default(snapshot, directory)
        changes.added.append(ASN)
    return changes


def _unsupported(snapshot: Snapshot, section: str, block: CommentedMap) -> None:
    """Say why a custom field without a counterpart is dropped."""
    if section != "custom_fields":
        return
    for custom_field in snapshot.custom_fields:
        name = str(custom_field["name"]).strip()
        spec, notes = field_spec(custom_field)
        if spec is None and block.get(name) == "drop" and not _comment(block, name):
            block.yaml_add_eol_comment(notes[0].split(":")[0], name)


def _comment(block: CommentedMap, key: Any) -> str:
    """The end-of-line comment of an entry, without '#'."""
    tokens = block.ca.items.get(key)
    if not tokens:
        return ""
    texts = [token.value for token in _flat(tokens) if hasattr(token, "value")]
    return " ".join(text.strip().lstrip("#").strip() for text in texts if text.strip())


def _flat(items: Any) -> Iterator[Any]:
    for item in items:
        if isinstance(item, list):
            yield from _flat(item)
        elif item is not None:
            yield item


__all__ = ["Changes", "defaults", "draft", "flow", "merge"]
