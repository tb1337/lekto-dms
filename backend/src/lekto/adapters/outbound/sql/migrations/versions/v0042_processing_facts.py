"""The first run of each document and the verdicts per field

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-25 12:00:00.000000

The page "System" shows how documents went through their first run and how people judged what
the automation set (Tobi, 24. and 25.10.2026, `domain.first_runs`): `first_runs` keeps per
document when its receiving began, when its first run first stopped and how long each node
worked in it; `field_verdicts` per document and field the verdict at a person's first decision
on it, and per signal whether it named the person's value. Both go with their document.

The backfill reads both from the log, as far as it tells (Tobi, 25.10.2026: "okay machen").

First runs, for the documents whose first lane is known: the entries of run 1 the nodes wrote
(not those of people or changes, not a text read again), the first of each node. The run began
when its receiving began and stopped where filing ended (green), where the first node failed
(red), or where the last node of the run ended (yellow; a page catch-up that began an hour or
more after every other node of the run had ended is no part of it). Entries written after the
stop (a page catch-up, facts read again) are no part of it.

Verdicts, for the documents uploaded through the web or the API (a migrated document's changes
are mostly the migration's own alignment, which judges nothing, and the statistics leave them
out), walking the log in order with the field checks as the latest judge and fields node had
them (`domain.first_runs` tells how a verdict is judged):

- A confirmation in the inbox decides every field: accepted is `accepted`; kept is `taken`; an
  entered value or one changed with it is judged against the automation's value and
  suggestion, with the value the document holds now if nothing touched the field since (no
  later decision on it, no rule that set it, no later judge or fields node); otherwise
  `corrected` tells whether it differs from before. An entered value where there was a
  suggestion stays unjudged then (the web sends an accepted suggestion as an entered value). An
  untouched field is `taken`. The space is `taken` where it lay, judged with the signals
  against that space; one the automation neither chose nor suggested gets no verdict.
- A change in the document view that confirms (`rules:change` of a person) decides the fields
  it set, judged the same way, and those the automation had set (`taken`); not the space.
- A move decides the space: `accepted` if it went to the suggested space, else `corrected`. A
  space chosen on upload is decided before and gets no verdict, unless the automation asked
  about the space since (an open check at the confirmation).
- A change or a move in run 1 before its stop is `early`; where the stop is not known, only
  while the document is still in its first run.

The signals are judged where the person's value is known. Documents are read and written in
chunks, and only the entries the verdicts need (the model nodes, the rules, the decisions), so
a large log needs no more memory than one chunk's entries.

The downgrade drops both tables.
"""

import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import batched
from typing import Any

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOCUMENTS = sa.table(
    "documents",
    sa.column("id", sa.Uuid()),
    sa.column("channel", sa.Text()),
    sa.column("first_lane", sa.Text()),
    sa.column("contact_id", sa.Uuid()),
    sa.column("document_type_id", sa.Uuid()),
    sa.column("topic_id", sa.Uuid()),
    sa.column("document_date", sa.Date()),
    sa.column("space_id", sa.Uuid()),
)
_LOG = sa.table(
    "processing_log",
    sa.column("seq", sa.Integer()),
    sa.column("document_id", sa.Uuid()),
    sa.column("node", sa.Text()),
    sa.column("run", sa.Integer()),
    sa.column("outcome", sa.Text()),
    sa.column("model_version", sa.Text()),
    sa.column("input", types.json_type()),
    sa.column("output", types.json_type()),
    sa.column("started_at", types.UtcDateTime()),
    sa.column("duration_us", sa.BigInteger()),
)
_TAGS = sa.table("tags", sa.column("id", sa.Uuid()), sa.column("assignment", sa.Text()))
_DOCUMENT_TAGS = sa.table(
    "document_tags", sa.column("document_id", sa.Uuid()), sa.column("tag_id", sa.Uuid())
)
_DOCUMENT_FIELDS = sa.table(
    "document_fields",
    sa.column("document_id", sa.Uuid()),
    sa.column("field_id", sa.Uuid()),
    sa.column("kind", sa.Text()),
    sa.column("value_text", sa.Text()),
    sa.column("value_decimal", types.ExactDecimal()),
    sa.column("value_currency", sa.String(3)),
    sa.column("value_date", sa.Date()),
    sa.column("value_date_end", sa.Date()),
    sa.column("value_boolean", sa.Boolean()),
)
_FIRST_RUNS = sa.table(
    "first_runs",
    sa.column("document_id", sa.Uuid()),
    sa.column("started_at", types.UtcDateTime()),
    sa.column("stopped_at", types.UtcDateTime()),
    sa.column("steps", types.json_type()),
)
_SIGNALS = ("signal_llm", "signal_classifier", "signal_neighbours", "signal_facts")
_VERDICTS = sa.table(
    "field_verdicts",
    sa.column("document_id", sa.Uuid()),
    sa.column("field", sa.Text()),
    sa.column("verdict", sa.Text()),
    sa.column("decided_at", types.UtcDateTime()),
    sa.column("decision", sa.Text()),
    *(sa.column(signal, sa.Boolean()) for signal in _SIGNALS),
)

_PERSON, _PERSON_SPACE, _RULES_CHANGE = "person", "person:space", "rules:change"
_NOT_THE_RUN = (_PERSON, _PERSON_SPACE, _RULES_CHANGE, "rules:apply")
_MODEL_NODES = ("judge", "fields")
_CONTACT, _TYPE, _TOPIC, _DATE, _SPACE, _TAGS_FIELD = (
    "contact",
    "document_type",
    "topic",
    "document_date",
    "space",
    "tags",
)
_JUDGED = (_CONTACT, _TYPE, _TOPIC, _DATE, _SPACE, _TAGS_FIELD)
_NAMED = (_CONTACT, _TYPE, _TOPIC, _SPACE)  # the fields the signals name candidates for
_CUSTOM = "field:"
_MIGRATION = "migration"
# Documents read and written at a time: few enough bound parameters for any SQLite.
_CHUNK = 500


def upgrade() -> None:
    _create_tables()
    connection = op.get_bind()
    stops = _backfill_first_runs(connection)
    _backfill_verdicts(connection, stops)


def _create_tables() -> None:
    op.create_table(
        "first_runs",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", types.UtcDateTime(), nullable=False),
        sa.Column("stopped_at", types.UtcDateTime(), nullable=False),
        sa.Column("steps", types.json_type(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_first_runs_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", name="pk_first_runs"),
    )
    op.create_index("ix_first_runs_stopped_at", "first_runs", ["stopped_at"])
    op.create_table(
        "field_verdicts",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("decided_at", types.UtcDateTime(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("signal_llm", sa.Boolean(), nullable=True),
        sa.Column("signal_classifier", sa.Boolean(), nullable=True),
        sa.Column("signal_neighbours", sa.Boolean(), nullable=True),
        sa.Column("signal_facts", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_field_verdicts_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "field", name="pk_field_verdicts"),
    )
    op.create_index("ix_field_verdicts_decided_at", "field_verdicts", ["decided_at"])


# --- reading the log ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Entry:
    seq: int
    node: str
    run: int
    outcome: str
    version: str | None
    input: dict[str, Any]
    output: dict[str, Any]
    started_at: datetime
    duration_us: int

    @property
    def ended_at(self) -> datetime:
        return self.started_at + timedelta(microseconds=self.duration_us)


def _entries(
    connection: sa.Connection, documents: Collection[object], *, first_run: bool
) -> dict[object, list[_Entry]]:
    """The log entries of `documents` in the order they were written; of run 1 only with
    `first_run`, without their output then; otherwise only those the verdicts read: the model
    nodes, the rules and the decisions (an OCR entry holds the words of every page)."""
    output = sa.null() if first_run else _LOG.c.output
    query = sa.select(
        _LOG.c.seq,
        _LOG.c.document_id,
        _LOG.c.node,
        _LOG.c.run,
        _LOG.c.outcome,
        _LOG.c.model_version,
        _LOG.c.input,
        output.label("output"),
        _LOG.c.started_at,
        _LOG.c.duration_us,
    ).where(_LOG.c.document_id.in_(list(documents)))
    if first_run:
        query = query.where(_LOG.c.run == 1)
    else:
        query = query.where(
            sa.or_(
                _LOG.c.node.in_([*_MODEL_NODES, "apply_rules"]),
                _LOG.c.model_version.in_(_NOT_THE_RUN),
            )
        )
    found: dict[object, list[_Entry]] = {}
    for row in connection.execute(query.order_by(_LOG.c.seq)):
        found.setdefault(row.document_id, []).append(
            _Entry(
                seq=row.seq,
                node=row.node,
                run=row.run,
                outcome=row.outcome,
                version=row.model_version,
                input=_object(row.input),
                output=_object(row.output),
                started_at=row.started_at,
                duration_us=row.duration_us,
            )
        )
    return found


def _object(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


# --- first runs ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Run:
    started_at: datetime
    stopped_at: datetime
    steps: dict[str, int]
    stop: int  # the seq of the entry that stopped it


def _backfill_first_runs(connection: sa.Connection) -> dict[object, int]:
    """Write the first runs the log tells; returns where each stopped (its entry's seq)."""
    known = connection.execute(
        sa.select(_DOCUMENTS.c.id, _DOCUMENTS.c.first_lane).where(
            _DOCUMENTS.c.first_lane.is_not(None)
        )
    ).all()
    stops: dict[object, int] = {}
    for chunk in batched(known, _CHUNK, strict=False):
        lanes = {document: lane for document, lane in chunk}
        rows = []
        for document, entries in _entries(connection, lanes, first_run=True).items():
            run = _first_run(entries, lanes[document])
            if run is None:
                continue
            stops[document] = run.stop
            rows.append(
                {
                    "document_id": document,
                    "started_at": run.started_at,
                    "stopped_at": run.stopped_at,
                    "steps": run.steps,
                }
            )
        if rows:
            connection.execute(sa.insert(_FIRST_RUNS), rows)
    return stops


def _first_run(entries: Sequence[_Entry], first_lane: str) -> _Run | None:
    """The first run of a document whose first run stopped in `first_lane`, from the entries
    of its run 1; None if they do not tell."""
    own = [
        entry
        for entry in entries
        if entry.run == 1
        and entry.version not in _NOT_THE_RUN
        and not (entry.node == "parse" and entry.input.get("reparse") is True)
    ]
    firsts: dict[str, _Entry] = {}
    for entry in own:
        firsts.setdefault(entry.node, entry)
    receive = firsts.get("receive")
    if receive is None:
        return None
    stop: _Entry | None
    if first_lane == "green":
        stop = next((e for e in own if e.node == "file" and e.outcome == "ok"), None)
    elif first_lane == "red":
        stop = next((e for e in own if e.outcome == "failed"), None)
    else:
        stop = max(_without_catch_ups(firsts), key=lambda entry: entry.seq)
    if stop is None or stop.ended_at < receive.started_at:
        return None
    return _Run(
        started_at=receive.started_at,
        stopped_at=stop.ended_at,
        steps={node: e.duration_us for node, e in firsts.items() if e.seq <= stop.seq},
        stop=stop.seq,
    )


_CATCH_UP_GAP = timedelta(hours=1)
"""A page catch-up (`render-pages`, logged in the document's current run) is told from the run's
own pages node by this gap: pages are rendered beside the OCR, never this long after every other
node of the run ended."""


def _without_catch_ups(firsts: Mapping[str, _Entry]) -> list[_Entry]:
    """The first entries without a page catch-up that came after the run."""
    entries = list(firsts.values())
    pages = firsts.get("pages")
    if pages is not None and len(entries) > 1:
        others = max(entry.ended_at for entry in entries if entry is not pages)
        if pages.started_at >= others + _CATCH_UP_GAP:
            entries.remove(pages)
    return entries


# --- verdicts -----------------------------------------------------------------------------------

_UNKNOWN = object()
"""A value the log cannot tell."""


def _backfill_verdicts(connection: sa.Connection, stops: Mapping[object, int]) -> None:
    manual = {
        str(id)
        for id in connection.execute(
            sa.select(_TAGS.c.id).where(_TAGS.c.assignment == "manual")
        ).scalars()
    }
    decided = (
        connection.execute(
            sa.select(_LOG.c.document_id)
            .distinct()
            .select_from(_LOG.join(_DOCUMENTS, _DOCUMENTS.c.id == _LOG.c.document_id))
            .where(
                _LOG.c.model_version.in_([_PERSON, _PERSON_SPACE, _RULES_CHANGE]),
                _DOCUMENTS.c.channel != _MIGRATION,
            )
        )
        .scalars()
        .all()
    )
    running = set(
        connection.execute(
            sa.select(_DOCUMENTS.c.id).where(_DOCUMENTS.c.first_lane.is_(None))
        ).scalars()
    )  # still in their first run: a decision in it comes before the stop
    for chunk in batched(decided, _CHUNK, strict=False):
        current = _current_values(connection, chunk, manual)
        rows = []
        for document, entries in _entries(connection, chunk, first_run=False).items():
            walk = _Walk(
                document,
                entries,
                current.get(document, {}),
                manual,
                stop=stops.get(document),
                running=document in running,
            )
            rows.extend(walk.verdicts())
        if rows:
            connection.execute(sa.insert(_VERDICTS), rows)


def _current_values(
    connection: sa.Connection, documents: Sequence[object], manual: Collection[str]
) -> dict[object, dict[str, Any]]:
    """The values the documents hold now, as JSON as the checks have them (`values_of`)."""
    values: dict[object, dict[str, Any]] = {}
    for row in connection.execute(
        sa.select(
            _DOCUMENTS.c.id,
            _DOCUMENTS.c.contact_id,
            _DOCUMENTS.c.document_type_id,
            _DOCUMENTS.c.topic_id,
            _DOCUMENTS.c.document_date,
            _DOCUMENTS.c.space_id,
        ).where(_DOCUMENTS.c.id.in_(list(documents)))
    ):
        values[row.id] = {
            _CONTACT: _text(row.contact_id),
            _TYPE: _text(row.document_type_id),
            _TOPIC: _text(row.topic_id),
            _DATE: None if row.document_date is None else row.document_date.isoformat(),
            _SPACE: _text(row.space_id),
            _TAGS_FIELD: [],
        }
    for document, tag in connection.execute(
        sa.select(_DOCUMENT_TAGS.c.document_id, _DOCUMENT_TAGS.c.tag_id).where(
            _DOCUMENT_TAGS.c.document_id.in_(list(documents))
        )
    ):
        if document in values and str(tag) not in manual:
            values[document][_TAGS_FIELD].append(str(tag))
    for row in connection.execute(
        sa.select(_DOCUMENT_FIELDS).where(_DOCUMENT_FIELDS.c.document_id.in_(list(documents)))
    ):
        if row.document_id in values:
            values[row.document_id][f"{_CUSTOM}{row.field_id}"] = _field_json(row)
    for found in values.values():
        found[_TAGS_FIELD].sort()
    return values


def _field_json(row: Any) -> Any:
    """A stored field value as JSON (`fields.field_to_json`)."""
    match row.kind:
        case "text" | "url":
            return row.value_text
        case "decimal":
            return _decimal(row.value_decimal)
        case "money":
            return {"amount": _decimal(row.value_decimal), "currency": row.value_currency}
        case "date":
            return row.value_date.isoformat()
        case "period":
            return {"start": row.value_date.isoformat(), "end": row.value_date_end.isoformat()}
        case "boolean":
            return row.value_boolean
    return _UNKNOWN


def _decimal(value: Decimal) -> str:
    return format(value, "f")


class _Walk:
    """One document's log, walked in order: each decision of a person judged with the field
    checks as they were then."""

    def __init__(
        self,
        document: object,
        entries: Sequence[_Entry],
        current: Mapping[str, Any],
        manual: Collection[str],
        *,
        stop: int | None,
        running: bool,
    ) -> None:
        self.document = document
        self.entries = entries
        self.current = current
        self.manual = manual
        self.stop = stop
        self.running = running  # still in its first run (no first lane yet)
        self.latest: dict[str, list[dict[str, Any]]] = {}  # field checks by model node
        self.judged: dict[str, dict[str, Any]] = {}  # rows by field
        self.space_decided = False

    def verdicts(self) -> list[dict[str, Any]]:
        index = 0
        while index < len(self.entries):
            entry = self.entries[index]
            if entry.version == _PERSON:
                group = [entry]
                while (
                    index + len(group) < len(self.entries)
                    and (following := self.entries[index + len(group)]).version == _PERSON
                    and (following.run, following.started_at) == (entry.run, entry.started_at)
                ):
                    group.append(following)
                self._confirmed(group)
                index += len(group)
                continue
            if entry.version == _PERSON_SPACE:
                self._space_chosen(entry)
            elif entry.version == _RULES_CHANGE and entry.input.get("trigger") == "change":
                if entry.input.get("actor") is not None:
                    self._changed(entry)
            elif entry.node in _MODEL_NODES and entry.version not in (*_NOT_THE_RUN, "rules"):
                self.latest[entry.node] = _checks(entry.output)
            index += 1
        return list(self.judged.values())

    # --- the decisions --------------------------------------------------------------------------

    def _confirmed(self, group: Sequence[_Entry]) -> None:
        """A confirmation in the inbox: every field."""
        outputs = [entry.output for entry in group]
        accepted = _union(outputs, "accepted")
        entered = _union(outputs, "entered")
        kept = _union(outputs, "kept")
        changed = _union(outputs, "changed")
        recorded = [output for output in outputs if "corrected" in output]
        corrected = _union(recorded, "corrected") if recorded else None
        chosen = next((o["space_id"] for o in outputs if isinstance(o.get("space_id"), str)), None)
        checks = self._checks()
        last = group[-1]
        fields = set(_JUDGED) | {
            name
            for name in (*checks, *entered, *accepted, *kept, *changed, *self.current)
            if name.startswith(_CUSTOM)
        }
        for name in sorted(fields):
            if name in self.judged:
                continue
            check = checks.get(name)
            automatic, suggestion = _automatic(check)
            if name == _SPACE:
                open = check is not None and check.get("outcome") != "ok"
                if self.space_decided and not open:
                    continue  # chosen on upload, and the automation did not ask since
                if name in accepted:
                    self._keep(last, "inbox", name, "accepted", suggestion, check)
                elif chosen is not None:
                    self._keep(last, "inbox", name, _moved(suggestion, chosen), chosen, check)
                elif not open:
                    # Where it lay: the check's value where the automation chose it, else the
                    # space the document holds now (the signals are judged against that).
                    value = automatic if not _empty(automatic) else self._now(name, last)
                    self._keep(last, "inbox", name, "taken", value, check)
                elif not _empty(suggestion):
                    self._keep(last, "inbox", name, "corrected", _UNKNOWN, check)
                continue
            if name in accepted:
                self._keep(last, "inbox", name, "accepted", suggestion, check)
            elif name in kept:
                self._keep(last, "inbox", name, "taken", self._now(name, last), check)
            elif name in entered or name in changed:
                self._set_by_person(last, "inbox", name, check, corrected)
            elif check is None or check.get("outcome") == "ok":
                verdict = _verdict(automatic, None, automatic)
                if verdict is not None:
                    self._keep(last, "inbox", name, verdict, automatic, check)

    def _changed(self, entry: _Entry) -> None:
        """A person's change in the document view: the fields it set and those the automation
        had set, if it confirms."""
        given = set(_strings(entry.input.get("changed")))
        settable = {name for name in given if name in _JUDGED or name.startswith(_CUSTOM)}
        settable.discard(_SPACE)
        if not settable or (settable == {_TAGS_FIELD} and self._only_manual(entry)):
            return  # a title, or tags set by hand alone: no confirmation
        if self._early(entry):
            for name in sorted(settable):
                self._keep(entry, "change", name, "early", _UNKNOWN, None, judge_signals=False)
            return
        recorded = "corrected" in entry.input
        corrected = set(_strings(entry.input.get("corrected"))) if recorded else None
        checks = self._checks()
        held = {
            name
            for name, check in checks.items()
            if check.get("outcome") == "ok" and not _empty(check.get("value"))
        }
        for name in sorted((settable | held) - {_SPACE}):
            if name in self.judged or not (name in _JUDGED or name.startswith(_CUSTOM)):
                continue
            check = checks.get(name)
            if name in settable:
                self._set_by_person(entry, "change", name, check, corrected)
            else:
                automatic, _ = _automatic(check)
                self._keep(entry, "change", name, "taken", automatic, check)

    def _space_chosen(self, entry: _Entry) -> None:
        """A person chose the space: on upload (decided before any verdict) or by moving it."""
        trigger = entry.input.get("trigger")
        if trigger == "upload":
            self.space_decided = True
            return
        if trigger != "move" or _SPACE in self.judged or self.space_decided:
            return
        if self._early(entry):
            self._keep(entry, "move", _SPACE, "early", _UNKNOWN, None, judge_signals=False)
            return
        check = self._checks().get(_SPACE)
        _, suggestion = _automatic(check)
        chosen = entry.input.get("space_id")
        self._keep(entry, "move", _SPACE, _moved(suggestion, chosen), chosen, check)

    # --- judging --------------------------------------------------------------------------------

    def _set_by_person(
        self,
        entry: _Entry,
        decision: str,
        name: str,
        check: dict[str, Any] | None,
        corrected: set[str] | None,
    ) -> None:
        """A field the person set: judged with its value now, if nothing touched it since;
        otherwise by whether it differs from before (`corrected`), where that tells."""
        automatic, suggestion = _automatic(check)
        value = self._now(name, entry)
        if value is not _UNKNOWN:
            verdict = _verdict(automatic, suggestion, value)
            if verdict is not None:
                self._keep(entry, decision, name, verdict, value, check)
            return
        if corrected is None:
            return
        if name not in corrected:  # set as it was: the automation's value, or none
            verdict = _verdict(automatic, suggestion, automatic)
            if verdict is not None:
                self._keep(entry, decision, name, verdict, automatic, check)
        elif not _empty(automatic):
            self._keep(entry, decision, name, "corrected", _UNKNOWN, check)
        elif _empty(suggestion):
            self._keep(entry, decision, name, "added", _UNKNOWN, check)

    def _keep(
        self,
        entry: _Entry,
        decision: str,
        name: str,
        verdict: str,
        value: Any,
        check: dict[str, Any] | None,
        *,
        judge_signals: bool = True,
    ) -> None:
        signals: dict[str, bool] = {}
        if judge_signals and value is not _UNKNOWN and name in _NAMED and check is not None:
            signals = _signals(check, value)
        self.judged[name] = {
            "document_id": self.document,
            "field": name,
            "verdict": verdict,
            "decided_at": entry.started_at,
            "decision": decision,
            **{signal: signals.get(signal) for signal in _SIGNALS},
        }

    def _now(self, name: str, entry: _Entry) -> Any:
        """The field's value now, if nothing touched it after `entry`: no later decision on it,
        no later judge (its own fields) or fields node (custom fields)."""
        model = "fields" if name.startswith(_CUSTOM) else "judge"
        if name in _rule_effects(entry):  # the rules the decision set off set it themselves
            return _UNKNOWN
        for later in self.entries:
            if later.seq <= entry.seq:
                continue
            if later.node == model and later.version not in (*_NOT_THE_RUN, "rules"):
                return _UNKNOWN
            if later.version in (*_NOT_THE_RUN, "rules") and name in _named_in(later):
                return _UNKNOWN
        value = self.current.get(name)
        return value

    def _early(self, entry: _Entry) -> bool:
        """Whether `entry` came in run 1 before it stopped: before the stop where it is known,
        else only while the document is still in its first run."""
        if entry.run != 1:
            return False
        return self.running if self.stop is None else entry.seq < self.stop

    def _only_manual(self, entry: _Entry) -> bool:
        changed = {
            *_strings(entry.input.get("tags_added")),
            *_strings(entry.input.get("tags_removed")),
        }
        return changed <= set(self.manual)

    def _checks(self) -> dict[str, dict[str, Any]]:
        return {
            check["field"]: check
            for node in _MODEL_NODES
            for check in self.latest.get(node, [])
            if isinstance(check.get("field"), str)
        }


def _named_in(entry: _Entry) -> set[str]:
    """The fields a decision or change entry names, and those the rules of a rules entry set
    (`RulePlan.to_json`: the effects applied per rule)."""
    record = {**entry.input, **entry.output}
    names = {
        name
        for key in ("accepted", "entered", "kept", "changed")
        for name in _strings(record.get(key))
    }
    if record.get("tags_added") or record.get("tags_removed"):
        names.add(_TAGS_FIELD)
    if entry.version == _PERSON_SPACE or isinstance(record.get("space_id"), str):
        names.add(_SPACE)
    return names | _rule_effects(entry)


def _rule_effects(entry: _Entry) -> set[str]:
    """The fields the rules of a rules entry set (`RulePlan.to_json`: the effects applied per
    rule); none in other entries."""
    names = set()
    rules = entry.output.get("rules")
    for report in rules if isinstance(rules, list) else []:
        applied = report.get("applied") if isinstance(report, dict) else None
        for effect in applied if isinstance(applied, list) else []:
            if isinstance(effect, dict) and isinstance(effect.get("field"), str):
                names.add(effect["field"])
    return names


def _checks(output: Mapping[str, Any]) -> list[dict[str, Any]]:
    checks = output.get("fields")
    return (
        [check for check in checks if isinstance(check, dict)] if isinstance(checks, list) else []
    )


def _automatic(check: Mapping[str, Any] | None) -> tuple[Any, Any]:
    """The automation's value of a field by its check, and its suggestion (an OK check's
    beside its value: tags or a topic proposed but not set)."""
    if check is None:
        return None, None
    if check.get("outcome") == "ok":
        return check.get("value"), check.get("suggestion")
    return None, check.get("suggestion")


def _verdict(automatic: Any, suggestion: Any, value: Any) -> str | None:
    """As `first_runs._verdict`."""
    if not _empty(automatic):
        if _same(value, automatic):
            return "taken"
        if not _empty(suggestion) and _took(value, automatic, suggestion):
            return "accepted"
        return "corrected"
    if not _empty(suggestion):
        return "accepted" if _same(value, suggestion) else "corrected"
    return None if _empty(value) else "added"


def _took(value: Any, automatic: Any, suggestion: Any) -> bool:
    """As `first_runs._took`: the suggestion taken, or suggested tags added to the
    automation's, dropping none."""
    if isinstance(value, list) and isinstance(automatic, list) and isinstance(suggestion, list):
        kept, had, offered = (
            set(map(str, value)),
            set(map(str, automatic)),
            set(map(str, suggestion)),
        )
        return had < kept <= had | offered
    return _same(value, suggestion)


def _moved(suggestion: Any, chosen: Any) -> str:
    """A person put the document into the space `chosen`."""
    return "accepted" if not _empty(suggestion) and _same(chosen, suggestion) else "corrected"


def _signals(check: Mapping[str, Any], value: Any) -> dict[str, bool]:
    """As `first_runs._signals`."""
    named: dict[str, bool] = {}
    candidates = check.get("candidates")
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict) or candidate.get("value") is None:
            continue
        sources = candidate.get("sources")
        for source in sources if isinstance(sources, list) else []:
            if not isinstance(source, dict) or not source.get("names"):
                continue
            signal = source.get("signal")
            if signal in _SIGNALS and signal not in named:
                named[signal] = _same(value, candidate["value"])
    return named


def _union(records: Iterable[Mapping[str, Any]], key: str) -> set[str]:
    return {name for record in records for name in _strings(record.get(key))}


def _strings(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _empty(value: Any) -> bool:
    return value is None or value is _UNKNOWN or value == [] or value == ""


def _same(value: Any, other: Any) -> bool:
    if isinstance(value, list) and isinstance(other, list):
        return sorted(map(str, value)) == sorted(map(str, other))
    return bool(value == other)


def _text(id: object | None) -> str | None:
    return None if id is None else str(id)


def downgrade() -> None:
    op.drop_index("ix_field_verdicts_decided_at", table_name="field_verdicts")
    op.drop_table("field_verdicts")
    op.drop_index("ix_first_runs_stopped_at", table_name="first_runs")
    op.drop_table("first_runs")
