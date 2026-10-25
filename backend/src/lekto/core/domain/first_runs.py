"""What Lekto keeps of each document's processing for the page "System" (Tobi, 24. and
25.10.2026): its first run (when it began, when it first stopped, how long each step worked),
and per field how a person judged what the automation set, when they first decided on that
field. Both are kept as they happen and never changed afterwards: later changes, merged
contacts or new runs alter nothing.

The first run ends where it first stops: confirming, retrying and reprocessing each begin a new
run. The lane it stopped in is `Document.first_lane`.

A verdict compares three values of a field, as JSON (`values_of`): the automation's (what the
document held before the person decided, unless the check of the field was uncertain: that
value was not applied), the suggestion of an uncertain check, and the person's (what the
document holds after their decision):

- `TAKEN`: the automation's value stands.
- `ACCEPTED`: the automation had no value; the person took its suggestion.
- `CORRECTED`: the automation had a value or a suggestion; the person chose another, or none.
- `ADDED`: the automation had neither; the person gave a value.
- `EARLY`: the person decided before the first run stopped, when there was nothing to judge
  yet.

Without a value on any side, a field gets no verdict. Tags are compared as a set, without the
tags set by hand (status tags such as "to pay" say nothing about the automation). Per signal, a
verdict tells whether the signal named the person's value, another value or none, for the
fields with one value the signals name candidates for (contact, type, topic, space).
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from lekto.core.domain.classification import (
    CONTACT,
    DOCUMENT_DATE,
    DOCUMENT_TYPE,
    SPACE,
    TAGS,
    TOPIC,
    FieldCheck,
    field_id_of,
    field_key,
)
from lekto.core.domain.documents import Document
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.fields import field_to_json
from lekto.core.domain.ids import DocumentId, TagId
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.pipeline import OUTSIDE_PIPELINE, PERSON, Node, NodeRun
from lekto.core.domain.validation import require_utc

# --- the first run ------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class FirstRun:
    """A document's first processing run: from when its receiving began to when the run first
    stopped (green, yellow or red), and how long each node worked in it. The difference of the
    two is the time it took (`duration`), with the waits for a worker; the sum of the steps the
    time the nodes worked (`work`), parallel ones each counted."""

    document_id: DocumentId
    started_at: datetime
    stopped_at: datetime
    steps: Mapping[Node, timedelta] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", require_utc(self.started_at, "started_at"))
        object.__setattr__(self, "stopped_at", require_utc(self.stopped_at, "stopped_at"))
        if self.stopped_at < self.started_at:
            raise ValidationError("a first run stops after it started")
        if any(step < timedelta(0) for step in self.steps.values()):
            raise ValidationError("a step takes no negative time")

    @property
    def duration(self) -> timedelta:
        return self.stopped_at - self.started_at

    @property
    def work(self) -> timedelta:
        return sum(self.steps.values(), timedelta(0))

    @classmethod
    def of(cls, document_id: DocumentId, log: Iterable[NodeRun], stopped_at: datetime) -> Self:
        """The first run from the document's log up to the stop: the entries of run 1 that the
        nodes wrote (not those of people or changes, `OUTSIDE_PIPELINE`). It began when the
        receiving began."""
        entries = [
            entry
            for entry in log
            if entry.run == 1
            and entry.result.model_version != PERSON
            and entry.result.model_version not in OUTSIDE_PIPELINE
        ]
        if not entries:
            raise ValidationError(f"document {document_id} has no entries of its first run")
        received = [entry.started_at for entry in entries if entry.node is Node.RECEIVE]
        steps: dict[Node, timedelta] = {}
        for entry in entries:
            steps[entry.node] = steps.get(entry.node, timedelta(0)) + entry.duration
        return cls(
            document_id=document_id,
            started_at=min(received or [entry.started_at for entry in entries]),
            stopped_at=stopped_at,
            steps=steps,
        )


# --- verdicts -----------------------------------------------------------------------------------


class Verdict(StrEnum):
    """How a person judged what the automation set for a field (the module docstring)."""

    TAKEN = "taken"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    ADDED = "added"
    EARLY = "early"


class Decision(StrEnum):
    """Where a person decided: confirming in the inbox, changing the document, moving it (or
    handing it over)."""

    INBOX = "inbox"
    CHANGE = "change"
    MOVE = "move"


JUDGED_FIELDS: tuple[str, ...] = (CONTACT, DOCUMENT_TYPE, TOPIC, DOCUMENT_DATE, SPACE, TAGS)
"""The fields every document has that get verdicts; custom fields (`field:<id>`) as well."""
NAMED_FIELDS = frozenset({CONTACT, DOCUMENT_TYPE, TOPIC, SPACE})
"""The fields whose candidates the signals name (`FieldCheck.candidates`)."""
JUDGED_SIGNALS: tuple[Node, ...] = (
    Node.SIGNAL_LLM,
    Node.SIGNAL_CLASSIFIER,
    Node.SIGNAL_NEIGHBOURS,
    Node.SIGNAL_FACTS,
)


@dataclass(frozen=True, kw_only=True)
class FieldVerdict:
    """A person's verdict on one field of a document, at their first decision on it; per
    signal that named a value for it, whether it named the person's (`signals`)."""

    document_id: DocumentId
    field: str
    verdict: Verdict
    decided_at: datetime
    decision: Decision
    signals: Mapping[Node, bool] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "decided_at", require_utc(self.decided_at, "decided_at"))
        if self.field not in JUDGED_FIELDS and field_id_of(self.field) is None:
            raise ValidationError(f"no verdict on the field {self.field!r}")
        if not set(self.signals) <= set(JUDGED_SIGNALS):
            raise ValidationError("a verdict names the judged signals only")
        if self.signals and self.field not in NAMED_FIELDS:
            raise ValidationError(f"the signals name no candidates for {self.field}")


def values_of(document: Document, manual: Collection[TagId] = ()) -> dict[str, JsonValue]:
    """The document's values of the judged fields, as JSON as the checks have them: ids as
    text, the date in ISO form, the tags as sorted ids without those set by hand (`manual`),
    the custom fields as `field:<id>`. None or an empty list: no value."""
    values: dict[str, JsonValue] = {
        CONTACT: _text(document.contact_id),
        DOCUMENT_TYPE: _text(document.document_type_id),
        TOPIC: _text(document.topic_id),
        DOCUMENT_DATE: None
        if document.document_date is None
        else document.document_date.isoformat(),
        SPACE: str(document.space_id),
        TAGS: list[JsonValue](sorted(str(tag) for tag in document.tag_ids if tag not in manual)),
    }
    for id, value in document.fields.items():
        values[field_key(id)] = field_to_json(value)
    return values


def decided_fields(
    decision: Decision,
    *,
    before: Mapping[str, JsonValue],
    given: Collection[str],
    applying: Collection[str],
) -> frozenset[str]:
    """The fields a person's decision covers. `given`: the fields they set (named as in
    checks); `applying`: the custom fields that apply to the document after the decision (one
    a type change removed lapsed, the person did not judge it).

    Confirming in the inbox decides every field, the space as well. A change decides the
    fields it sets and those the automation had set (a person who changes a document confirms
    its metadata), not the space. A move decides the space."""
    custom = frozenset(applying)
    match decision:
        case Decision.INBOX:
            return frozenset(JUDGED_FIELDS) | custom
        case Decision.CHANGE:
            held = {name for name, value in before.items() if not _empty(value)}
            return frozenset((set(given) | held) - {SPACE}) & (frozenset(JUDGED_FIELDS) | custom)
        case Decision.MOVE:
            return frozenset({SPACE})


def judge_fields(
    document_id: DocumentId,
    decision: Decision,
    *,
    fields: Collection[str],
    before: Mapping[str, JsonValue],
    after: Mapping[str, JsonValue],
    checks: Mapping[str, FieldCheck],
    decided_at: datetime,
) -> list[FieldVerdict]:
    """The verdicts on `fields` (`decided_fields`): `before` and `after` the person's decision
    (`values_of`), `checks` the field checks of the latest run (`inbox.field_checks`). Fields
    without a value on any side are left out."""
    verdicts = []
    for name in sorted(fields):
        check = checks.get(name)
        automatic, suggestion = _automatic(name, check, before)
        value = after.get(name)
        verdict = _verdict(automatic, suggestion, value)
        if verdict is None:
            continue
        verdicts.append(
            FieldVerdict(
                document_id=document_id,
                field=name,
                verdict=verdict,
                decided_at=decided_at,
                decision=decision,
                signals=_signals(check, value) if name in NAMED_FIELDS else {},
            )
        )
    return verdicts


def early_verdicts(
    document_id: DocumentId, decision: Decision, fields: Collection[str], decided_at: datetime
) -> list[FieldVerdict]:
    """A person decided `fields` before the first run stopped: nothing to judge, ever."""
    return [
        FieldVerdict(
            document_id=document_id,
            field=name,
            verdict=Verdict.EARLY,
            decided_at=decided_at,
            decision=decision,
        )
        for name in sorted(fields)
    ]


def _automatic(
    name: str, check: FieldCheck | None, before: Mapping[str, JsonValue]
) -> tuple[JsonValue, JsonValue]:
    """The automation's value of field `name`, and its suggestion. An uncertain check's value
    was not applied: the document holds none then, or one a rule set; the space it lies in is
    where it landed, which the automation did not choose."""
    value = before.get(name)
    if check is None or check.ok:
        return value, None
    if name == SPACE:
        return None, check.suggestion
    return value, check.suggestion


def _verdict(automatic: JsonValue, suggestion: JsonValue, value: JsonValue) -> Verdict | None:
    if not _empty(automatic):
        return Verdict.TAKEN if _same(value, automatic) else Verdict.CORRECTED
    if not _empty(suggestion):
        return Verdict.ACCEPTED if _same(value, suggestion) else Verdict.CORRECTED
    return None if _empty(value) else Verdict.ADDED


def _signals(check: FieldCheck | None, value: JsonValue) -> dict[Node, bool]:
    """Per signal that named a candidate (the best it named, an existing value), whether it is
    `value`. A name that does not exist yet counts as no value named."""
    if check is None:
        return {}
    named: dict[Node, bool] = {}
    for candidate in check.candidates:
        if candidate.value is None:
            continue
        for source in candidate.sources:
            if not source.names:
                continue
            try:
                signal = Node(source.signal)
            except ValueError:
                continue
            if signal in JUDGED_SIGNALS and signal not in named:
                named[signal] = _same(value, candidate.value)
    return named


def _empty(value: JsonValue) -> bool:
    return value is None or value == [] or value == ""


def _same(value: JsonValue, other: JsonValue) -> bool:
    if isinstance(value, list) and isinstance(other, list):
        return sorted(map(str, value)) == sorted(map(str, other))
    return value == other


def _text(id: object | None) -> str | None:
    return None if id is None else str(id)
