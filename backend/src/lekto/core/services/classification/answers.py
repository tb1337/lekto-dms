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

from lekto.core.domain.documents import MAX_TITLE
from lekto.core.domain.fields import FieldDefinition, FieldType
from lekto.core.domain.ids import FieldId
from lekto.core.domain.json_value import JsonObject, JsonValue, as_object, as_text, as_texts
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

    @classmethod
    def of(cls, answer: ProposeAnswer, keys: Mapping[str, FieldDefinition]) -> Self:
        """The answer, its fields (by the keys sent) by id."""
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
            fields={keys[key].id: value for key, value in answer.fields.items()},
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
) -> JsonObject:
    """Every field value is text, as written in the document; the fields come as a list of
    the keys the document shows (the model leaves the others out). `topics`: those of the
    listed contacts, one of them or null."""
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
        }
    )


def parse_propose(content: str, keys: Sequence[str]) -> ProposeAnswer:
    """Strict about the structure; a field entry with a key that is not listed is left out,
    and of two entries for one key the first counts."""
    data = _load(content)
    _require_fields(data, _PROPOSE_FIELDS, "the answer")
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
    )


# --- fields -------------------------------------------------------------------------------


def field_keys(definitions: Sequence[FieldDefinition]) -> dict[str, FieldDefinition]:
    """Short keys for the fields (`a1`, `a2`, ...): names may be any text, keys are safe
    as JSON property names in every provider's schema dialect."""
    return {f"a{index}": definition for index, definition in enumerate(definitions, start=1)}


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
