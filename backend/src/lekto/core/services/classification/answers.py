"""JSON Schemas of the model's answers, and checking an answer's structure.

The schemas are built per document from the master data (lists as `enum`); every property is
required, nothing else is allowed, "not found" is `null`. They keep to what strict validators
accept (Claude's too): one of a list or null as `anyOf`, no limits on arrays. The check is
strict about structure (an answer with a missing or an extra field is invalid, since an extra
field may be an instruction from the document at work) and lenient about values: a document
type outside the list counts as a proposed new type, unknown tags as proposed new tags, and a
value that cannot be read makes only its field uncertain. The one exception is a field's
`label` (`propose-4`, `extract-5`): an entry without it reads as without a label, as an answer
to the prompts before did, and so does one whose label is no text.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Self
from uuid import UUID

from lekto.core.domain.document_facts import MODEL_HOLDER_KINDS, HolderKind, ReadFact
from lekto.core.domain.documents import MAX_TITLE
from lekto.core.domain.fields import FieldDefinition, FieldType
from lekto.core.domain.holders import ReadHolder
from lekto.core.domain.ids import FieldId
from lekto.core.domain.json_value import (
    JsonObject,
    JsonValue,
    as_object,
    as_text,
    as_texts,
    as_uuid,
)
from lekto.core.domain.master_data import one_line

# Characters of a quoted passage that are kept: more than the prompt asks for
# (`prompts.EVIDENCE_CHARACTERS`), so a long quote is cut, not lost.
_EVIDENCE_LENGTH = 500
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)

_TEXT_OR_NULL: JsonObject = {"type": ["string", "null"]}


class AnswerError(ValueError):
    """The answer is not JSON or does not have the structure of the schema."""


@dataclass(frozen=True, kw_only=True)
class Proposal:
    """A proposed value with the passage the model quoted for it and, for a field, the label
    of the value as it stands in the document (None for none, and for sender and date)."""

    value: JsonValue
    evidence: str | None
    label: str | None = None

    def to_json(self) -> JsonObject:
        """The label only where there is one."""
        data: JsonObject = {"value": self.value, "evidence": self.evidence}
        if self.label is not None:
            data["label"] = self.label
        return data

    @classmethod
    def from_json(cls, data: JsonValue) -> Self:
        """Lenient: what is missing (or no text, for the evidence and the label) is None."""
        if not isinstance(data, dict):
            return cls(value=None, evidence=None)
        evidence, label = data.get("evidence"), data.get("label")
        return cls(
            value=data.get("value"),
            evidence=evidence if isinstance(evidence, str) else None,
            label=label if isinstance(label, str) else None,
        )


# --- the proposal (`signal_llm`) --------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ProposeAnswer:
    sender: Proposal  # value: the name, or None
    recipient: str | None
    document_type: str | None
    new_document_type: str | None
    topic: str | None
    tags: list[str]
    new_tags: list[str]
    document_date: Proposal  # value: the date as written, or None
    title: str | None
    language: str | None
    fields: dict[str, Proposal]  # by key; only the fields the model gave
    raw: JsonObject
    space: str | None = None  # the key of a listed space (`propose-5`, only with spaces listed)


@dataclass(frozen=True, kw_only=True)
class StoredProposal:
    """The proposal as `signal_llm` keeps it in its output, the fields by id (so a renamed
    field or a new key order does not mix them up). Read leniently: what a stored proposal
    lacks, or holds of another type, counts as not proposed."""

    sender: Proposal
    recipient: str | None
    document_type: str | None
    new_document_type: str | None
    topic: str | None
    tags: tuple[str, ...]
    new_tags: tuple[str, ...]
    document_date: Proposal
    title: str | None
    language: str | None
    fields: Mapping[FieldId, Proposal]
    space: UUID | None = None  # the space the model chose among those listed

    @classmethod
    def of(
        cls,
        answer: ProposeAnswer,
        keys: Mapping[str, FieldId],
        spaces: Mapping[str, UUID] | None = None,
    ) -> Self:
        """The answer, its fields (by the keys sent) by id, its space (by the keys of the
        spaces sent) by id."""
        return cls(
            sender=answer.sender,
            recipient=answer.recipient,
            document_type=answer.document_type,
            new_document_type=answer.new_document_type,
            topic=answer.topic,
            tags=tuple(answer.tags),
            new_tags=tuple(answer.new_tags),
            document_date=answer.document_date,
            title=answer.title,
            language=answer.language,
            fields={keys[key]: value for key, value in answer.fields.items()},
            space=None if answer.space is None else (spaces or {}).get(answer.space),
        )

    def to_json(self) -> JsonObject:
        return {
            "sender": self.sender.to_json(),
            "recipient": self.recipient,
            "document_type": self.document_type,
            "new_document_type": self.new_document_type,
            "topic": self.topic,
            "tags": list[JsonValue](self.tags),
            "new_tags": list[JsonValue](self.new_tags),
            "document_date": self.document_date.to_json(),
            "title": self.title,
            "language": self.language,
            "fields": {str(id): value.to_json() for id, value in self.fields.items()},
            "space": None if self.space is None else str(self.space),
        }

    @classmethod
    def from_json(cls, data: JsonValue) -> Self | None:
        """None for anything but an object."""
        if not isinstance(data, dict):
            return None
        fields = data.get("fields")
        return cls(
            sender=Proposal.from_json(data.get("sender")),
            recipient=as_text(data.get("recipient")),
            document_type=as_text(data.get("document_type")),
            new_document_type=as_text(data.get("new_document_type")),
            topic=as_text(data.get("topic")),
            tags=as_texts(data.get("tags")),
            new_tags=as_texts(data.get("new_tags")),
            document_date=Proposal.from_json(data.get("document_date")),
            title=as_text(data.get("title")),
            language=as_text(data.get("language")),
            fields={
                id: Proposal.from_json(value)
                for key, value in (as_object(fields) or {}).items()
                if (id := _stored_id(key)) is not None
            },
            space=as_uuid(data.get("space")),
        )


def _stored_id(value: str) -> FieldId | None:
    try:
        return FieldId(UUID(value))
    except ValueError:
        return None


_PROPOSE_FIELDS = (
    "sender",
    "recipient",
    "document_type",
    "new_document_type",
    "topic",
    "tags",
    "new_tags",
    "document_date",
    "title",
    "language",
    "fields",
)
_FIELD_ENTRY = ("key", "value", "evidence")
_LABEL = "label"  # of a field's entry; one without it reads as without a label (`_parse_proposal`)


def propose_schema(
    document_types: Sequence[str],
    tags: Sequence[str],
    keys: Sequence[str],
    topics: Sequence[str] = (),
    spaces: Sequence[str] = (),
) -> JsonObject:
    """Every field value is text, as written in the document; the fields come as a list of
    the keys the document shows (the model leaves the others out). `topics`: those of the
    listed contacts, one of them or null. `spaces`: the keys of the listed spaces; only with
    spaces listed does the answer have a `space`, one of them or null."""
    # Without tags or fields to list, anything given is left out or proposed as new.
    tag_items: JsonObject = {"type": "string"}
    if tags:
        tag_items["enum"] = list(tags)
    key: JsonObject = {"type": "string"}
    if keys:
        key["enum"] = list(keys)
    entry = _object(
        {
            "key": key,
            "value": dict(_TEXT_OR_NULL),
            "evidence": dict(_TEXT_OR_NULL),
            _LABEL: dict(_TEXT_OR_NULL),
        }
    )
    space: JsonObject = {"space": _one_of_or_null(spaces)} if spaces else {}
    return _object(
        {
            "sender": _proposal(dict(_TEXT_OR_NULL)),
            "recipient": dict(_TEXT_OR_NULL),
            "document_type": _one_of_or_null(document_types),
            "new_document_type": dict(_TEXT_OR_NULL),
            "topic": _one_of_or_null(topics),
            "tags": {"type": "array", "items": tag_items},
            "new_tags": {"type": "array", "items": {"type": "string"}},
            "document_date": _proposal(dict(_TEXT_OR_NULL)),
            "title": dict(_TEXT_OR_NULL),
            "language": dict(_TEXT_OR_NULL),
            "fields": {"type": "array", "items": entry},
            **space,
        }
    )


def parse_propose(content: str, keys: Sequence[str], spaces: Sequence[str] = ()) -> ProposeAnswer:
    """Strict about the structure; a field entry with a key that is not listed is left out,
    and of two entries for one key the first counts. A `space` is read only with `spaces`
    listed; one that is none of them counts as none."""
    data = _load(content)
    # The space is read only with spaces listed; one left out counts as none.
    _require_fields(data, _PROPOSE_FIELDS, "the answer", optional=["space"] if spaces else [])
    entries = data["fields"]
    if not isinstance(entries, list):
        raise AnswerError("fields: expected a list")
    fields: dict[str, Proposal] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise AnswerError(f"fields[{index}]: expected an object")
        _require_fields(entry, _FIELD_ENTRY, f"fields[{index}]", optional=(_LABEL,))
        key = entry["key"]
        if isinstance(key, str) and key in keys and key not in fields:
            fields[key] = _parse_proposal(
                {name: value for name, value in entry.items() if name != "key"},
                f"fields[{index}]",
                labelled=True,
            )
    # The title becomes the document's: on one line, without control characters, not too long.
    title = _text_or_null(data["title"], "title")
    title = one_line(title)[:MAX_TITLE].strip() or None if title else None
    return ProposeAnswer(
        sender=_parse_proposal(data["sender"], "sender", text=True),
        recipient=_text_or_null(data["recipient"], "recipient"),
        document_type=_text_or_null(data["document_type"], "document_type"),
        new_document_type=_text_or_null(data["new_document_type"], "new_document_type"),
        topic=_text_or_null(data["topic"], "topic"),
        tags=_texts(data["tags"], "tags"),
        new_tags=_texts(data["new_tags"], "new_tags"),
        document_date=_parse_proposal(data["document_date"], "document_date", text=True),
        title=title,
        language=_text_or_null(data["language"], "language"),
        fields=fields,
        raw=data,
        space=_space(data, spaces),
    )


def _space(data: JsonObject, spaces: Sequence[str]) -> str | None:
    if not spaces:
        return None
    key = _text_or_null(data.get("space"), "space")
    return key if key in spaces else None


# --- fields -------------------------------------------------------------------------------


def field_keys(definitions: Sequence[FieldDefinition]) -> dict[str, FieldDefinition]:
    """Short keys for the fields (`a1`, `a2`, ...): names may be any text, keys are safe
    as JSON property names in every provider's schema dialect."""
    return {f"a{index}": definition for index, definition in enumerate(definitions, start=1)}


def key_ids(keys: Mapping[str, FieldDefinition]) -> dict[str, FieldId]:
    """The fields' ids by their keys."""
    return {key: definition.id for key, definition in keys.items()}


def extract_schema(keys: dict[str, FieldDefinition]) -> JsonObject:
    return _object(
        {
            "fields": _object(
                {
                    key: _proposal(_value_schema(definition), labelled=True)
                    for key, definition in keys.items()
                }
            )
        }
    )


def parse_extract(content: str, keys: Sequence[str]) -> dict[str, Proposal]:
    data = _load(content)
    _require_fields(data, ("fields",), "the answer")
    fields = data["fields"]
    if not isinstance(fields, dict):
        raise AnswerError("fields: expected an object")
    _require_fields(fields, keys, "fields")
    return {key: _parse_proposal(fields[key], f"fields.{key}", labelled=True) for key in keys}


def _value_schema(definition: FieldDefinition) -> JsonObject:
    match definition.data_type:
        case FieldType.AMOUNT:
            amount: JsonObject = {
                "type": "object",
                "properties": {"amount": {"type": "string"}, "currency": {"type": "string"}},
                "required": ["amount", "currency"],
                "additionalProperties": False,
            }
            return {"anyOf": [amount, {"type": "null"}]}
        case FieldType.PERIOD:
            period: JsonObject = {
                "type": "object",
                "properties": {"start": {"type": "string"}, "end": {"type": "string"}},
                "required": ["start", "end"],
                "additionalProperties": False,
            }
            return {"anyOf": [period, {"type": "null"}]}
        case FieldType.BOOLEAN:
            return {"type": ["boolean", "null"]}
        case FieldType.CHOICE:
            return _one_of_or_null(definition.choices)
        case _:
            return dict(_TEXT_OR_NULL)


def described(schema: JsonObject, descriptions: Mapping[str, str]) -> JsonObject:
    """`schema` with a `description` at each path of `descriptions`: property names apart by
    dots, through the items of a list (`fields.key`); the empty path is the schema itself. A
    path the schema does not have is left out."""
    copied: JsonObject = json.loads(json.dumps(schema))
    for path, text in descriptions.items():
        node: JsonValue = copied
        for name in path.split(".") if path else ():
            item = as_object(node) or {}
            if "items" in item:
                item = as_object(item["items"]) or {}
            node = (as_object(item.get("properties")) or {}).get(name)
        if isinstance(node, dict):
            node["description"] = text
    return copied


# --- helpers ----------------------------------------------------------------------------------


def _object(properties: JsonObject) -> JsonObject:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _one_of_or_null(names: Sequence[str]) -> JsonObject:
    """One of `names`, or null; any text without names."""
    if not names:
        return dict(_TEXT_OR_NULL)
    return {"anyOf": [{"type": "string", "enum": list(names)}, {"type": "null"}]}


def _proposal(value: JsonObject, *, labelled: bool = False) -> JsonObject:
    """A value with its evidence; a field's (`labelled`) also with its label."""
    properties: JsonObject = {"value": value, "evidence": dict(_TEXT_OR_NULL)}
    if labelled:
        properties[_LABEL] = dict(_TEXT_OR_NULL)
    return _object(properties)


def _load(content: str) -> JsonObject:
    fenced = _FENCE.match(content)
    text = fenced.group(1) if fenced else content
    try:
        data = json.loads(text)
    except ValueError:
        raise AnswerError("the answer is not JSON") from None
    if not isinstance(data, dict):
        raise AnswerError("the answer is not a JSON object")
    return data


def _require_fields(
    data: JsonObject, fields: Sequence[str], where: str, *, optional: Sequence[str] = ()
) -> None:
    """`data` has `fields` and nothing else but the `optional` ones."""
    missing = [name for name in fields if name not in data]
    extra = sorted(set(data) - set(fields) - set(optional))
    if missing:
        raise AnswerError(f"{where}: missing {', '.join(missing)}")
    if extra:
        raise AnswerError(f"{where}: unexpected {', '.join(extra)}")


def _parse_proposal(
    data: JsonValue, where: str, *, text: bool = False, labelled: bool = False
) -> Proposal:
    """A value with its evidence; a field's (`labelled`) may also have its label, as text on
    one line (anything else counts as no label)."""
    if not isinstance(data, dict):
        raise AnswerError(f"{where}: expected an object with value and evidence")
    _require_fields(data, ("value", "evidence"), where, optional=(_LABEL,) if labelled else ())
    value = data["value"]
    if text:
        value = _text_or_null(value, f"{where}.value")
    evidence = _text_or_null(data["evidence"], f"{where}.evidence")
    # Recorded only (the label check changes no outcome): one that is no text counts as none.
    given = data.get(_LABEL)
    label = given.strip() or None if isinstance(given, str) else None
    return Proposal(
        value=value,
        evidence=evidence[:_EVIDENCE_LENGTH] if evidence else None,
        label=one_line(label)[:_EVIDENCE_LENGTH].strip() or None if label else None,
    )


def _text_or_null(value: JsonValue, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AnswerError(f"{where}: expected text or null")
    return value.strip() or None


def _texts(value: JsonValue, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AnswerError(f"{where}: expected a list of texts")
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


# --- facts with their role (`facts-1`) ----------------------------------------------------

_FACT_ENTRY = ("kind", "value", "role", "evidence", _LABEL)


def facts_schema(kinds: Sequence[str], roles: Sequence[str]) -> JsonObject:
    """A list of facts, each of one of `kinds` in one of `roles`, the value as written, the
    passage that shows it and its label."""
    entry = _object(
        {
            "kind": {"type": "string", "enum": list(kinds)},
            "value": {"type": "string"},
            "role": {"type": "string", "enum": list(roles)},
            "evidence": dict(_TEXT_OR_NULL),
            _LABEL: dict(_TEXT_OR_NULL),
        }
    )
    holder = _object(
        {
            "kind": {"type": "string", "enum": [kind.value for kind in sorted(MODEL_HOLDER_KINDS)]},
            "value": {"type": "string"},
            "holder": {"type": "string", "enum": [kind.value for kind in HolderKind]},
            "name": dict(_TEXT_OR_NULL),
            "evidence": dict(_TEXT_OR_NULL),
        }
    )
    return _object(
        {
            "facts": {"type": "array", "items": entry},
            "holders": {"type": "array", "items": holder},
        }
    )


def parse_facts(content: str) -> list[ReadFact]:
    """Strict about the structure (an entry with a field missing or more is invalid); a fact of
    a kind or role not listed, or without a value, is kept for the check to refuse
    (`document_facts.checked_read`)."""
    data = _load(content)
    _require_fields(data, ("facts",), "the answer", optional=("holders",))
    entries = data["facts"]
    if not isinstance(entries, list):
        raise AnswerError("facts: expected a list")
    facts: list[ReadFact] = []
    for index, entry in enumerate(entries):
        where = f"facts[{index}]"
        if not isinstance(entry, dict):
            raise AnswerError(f"{where}: expected an object")
        _require_fields(entry, _FACT_ENTRY[:4], where, optional=(_LABEL,))
        kind, value, role = (entry[name] for name in ("kind", "value", "role"))
        if not (isinstance(kind, str) and isinstance(value, str) and isinstance(role, str)):
            raise AnswerError(f"{where}: kind, value and role are texts")
        evidence = _text_or_null(entry["evidence"], f"{where}.evidence")
        label = entry.get(_LABEL)
        if not value.strip():
            continue
        facts.append(
            ReadFact(
                kind=kind.strip(),
                value=value.strip()[:_EVIDENCE_LENGTH],
                role=role.strip(),
                evidence=evidence[:_EVIDENCE_LENGTH] if evidence else None,
                label=one_line(label)[:_EVIDENCE_LENGTH].strip() or None
                if isinstance(label, str) and label.strip()
                else None,
            )
        )
    return facts


def parse_holders(content: str) -> list[ReadHolder]:
    """The holders the facts call tells (`facts-2`), strict about each entry's structure; an
    answer without them (an earlier prompt) tells none. A holder or number not listed is kept
    for the check to refuse (`holders.checked_holder`)."""
    data = _load(content)
    entries = data.get("holders", [])
    if not isinstance(entries, list):
        raise AnswerError("holders: expected a list")
    holders: list[ReadHolder] = []
    for index, entry in enumerate(entries):
        where = f"holders[{index}]"
        if not isinstance(entry, dict):
            raise AnswerError(f"{where}: expected an object")
        _require_fields(entry, ("kind", "value", "holder", "name", "evidence"), where)
        kind, value, holder = (entry[name] for name in ("kind", "value", "holder"))
        if not (isinstance(kind, str) and isinstance(value, str) and isinstance(holder, str)):
            raise AnswerError(f"{where}: kind, value and holder are texts")
        name = _text_or_null(entry["name"], f"{where}.name")
        evidence = _text_or_null(entry["evidence"], f"{where}.evidence")
        holders.append(
            ReadHolder(
                kind=kind.strip(),
                value=value.strip()[:_EVIDENCE_LENGTH],
                holder=holder.strip(),
                name=(one_line(name)[:_EVIDENCE_LENGTH].strip() or None) if name else None,
                evidence=evidence[:_EVIDENCE_LENGTH] if evidence else None,
            )
        )
    return holders


def read_holder_to_json(holder: ReadHolder) -> JsonObject:
    return {
        "kind": holder.kind,
        "value": holder.value,
        "holder": holder.holder,
        "name": holder.name,
        "evidence": holder.evidence,
    }


def read_holder_from_json(data: JsonValue) -> ReadHolder | None:
    """A holder as the log keeps it; None for what is no such entry."""
    item = as_object(data)
    if item is None:
        return None
    kind, value, holder = (as_text(item.get(name)) for name in ("kind", "value", "holder"))
    if kind is None or value is None or holder is None:
        return None
    return ReadHolder(
        kind=kind,
        value=value,
        holder=holder,
        name=as_text(item.get("name")),
        evidence=as_text(item.get("evidence")),
    )


def read_fact_to_json(fact: ReadFact) -> JsonObject:
    return {
        "kind": fact.kind,
        "value": fact.value,
        "role": fact.role,
        "evidence": fact.evidence,
        "label": fact.label,
    }


def read_fact_from_json(data: JsonValue) -> ReadFact | None:
    """A fact as the log keeps it; None for what is no such entry."""
    item = as_object(data)
    if item is None:
        return None
    kind, value, role = (as_text(item.get(name)) for name in ("kind", "value", "role"))
    if kind is None or value is None or role is None:
        return None
    return ReadFact(
        kind=kind,
        value=value,
        role=role,
        evidence=as_text(item.get("evidence")),
        label=as_text(item.get(_LABEL)),
    )
