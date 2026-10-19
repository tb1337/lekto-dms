"""Signals before the judge: `classify` is `judge`, `extract_fields` is `fields`

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-13 22:00:00.000000

The two nodes are renamed wherever a node's name is stored: the state of every node
(`documents.processing_nodes`), the processing log, the payload and dedup key of node and
catch-up jobs, and the payload of events not yet delivered.

The four signals are new nodes before the judge. A document whose judge ran or was skipped
has them `skipped`, as revision 0010 did for the pages; reprocessing it from the judge runs
them. A document whose judge still waits (or was running) gets them waiting: a queued job of
its judge is dropped, as it is no longer due, and once its text is parsed, jobs for the
signals take its place.

The downgrade renames back and drops the signals from the states, the log, the jobs and the
undelivered events; a document whose judge waits gets a job for `classify` again once its
text is parsed.
"""

import os
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RENAMED = {"classify": "judge", "extract_fields": "fields"}
_SIGNALS = ("signal_llm", "signal_classifier", "signal_neighbours", "signal_facts")
_NODE_JOBS = ("pipeline.node", "pipeline.catch_up")
_NODE_EVENTS = ("document.node_started", "document.node_completed", "document.node_deferred")
_ACTIVE = ("queued", "running")
_PARSED = ("ok", "uncertain")

_documents = sa.table(
    "documents",
    sa.column("id", sa.Uuid()),
    sa.column("processing_run", sa.Integer()),
    sa.column("processing_nodes", types.json_type()),
)
_log = sa.table("processing_log", sa.column("node", sa.Text()))
_jobs = sa.table(
    "jobs",
    sa.column("id", sa.Uuid()),
    sa.column("kind", sa.Text()),
    sa.column("payload", types.json_type()),
    sa.column("dedup_key", sa.Text()),
    sa.column("status", sa.Text()),
    sa.column("attempts", sa.Integer()),
    sa.column("releases", sa.Integer()),
    sa.column("run_at", types.UtcDateTime()),
)
_outbox = sa.table(
    "outbox",
    sa.column("seq"),
    sa.column("type", sa.Text()),
    sa.column("payload", types.json_type()),
)


def upgrade() -> None:
    connection = op.get_bind()
    _rename_everywhere(connection, _RENAMED)
    waiting_judges = []
    for row in connection.execute(sa.select(_documents)).mappings():
        nodes = dict(row["processing_nodes"] or {})
        judge = nodes.get("judge", {})
        if judge.get("status") in ("waiting", "running"):
            nodes["judge"] = _state("waiting")
            nodes.update({signal: _state("waiting") for signal in _SIGNALS})
            waiting_judges.append((row["id"], row["processing_run"], nodes))
        else:
            nodes.update({signal: _state("skipped") for signal in _SIGNALS})
        _store(connection, row["id"], nodes)
    for document, run, nodes in waiting_judges:
        _drop_jobs(connection, document, ["judge"])
        if _parsed(nodes):
            _queue(connection, document, run, _SIGNALS)


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.delete(_log).where(_log.c.node.in_(_SIGNALS)))
    for row in connection.execute(
        sa.select(_jobs.c.id, _jobs.c.payload).where(_jobs.c.kind.in_(_NODE_JOBS))
    ).mappings():
        if _node_of(row["payload"]) in _SIGNALS:
            connection.execute(sa.delete(_jobs).where(_jobs.c.id == row["id"]))
    for row in connection.execute(
        sa.select(_outbox.c.seq, _outbox.c.payload).where(_outbox.c.type.in_(_NODE_EVENTS))
    ).mappings():
        if _node_of(row["payload"]) in _SIGNALS:
            connection.execute(sa.delete(_outbox).where(_outbox.c.seq == row["seq"]))
    waiting_judges = []
    for row in connection.execute(sa.select(_documents)).mappings():
        nodes = {
            name: state
            for name, state in (row["processing_nodes"] or {}).items()
            if name not in _SIGNALS
        }
        if nodes.get("judge", {}).get("status") == "waiting":
            waiting_judges.append((row["id"], row["processing_run"], nodes))
        _store(connection, row["id"], nodes)
    _rename_everywhere(connection, {new: old for old, new in _RENAMED.items()})
    for document, run, nodes in waiting_judges:
        if _parsed(nodes) and not _has_job(connection, document, run, "classify"):
            _queue(connection, document, run, ["classify"])


def _rename_everywhere(connection: sa.Connection, names: dict[str, str]) -> None:
    """In the states of the nodes, the log, the node jobs and the node events."""
    for row in connection.execute(sa.select(_documents)).mappings():
        nodes = row["processing_nodes"] or {}
        if any(name in nodes for name in names):
            _store(connection, row["id"], {names.get(name, name): s for name, s in nodes.items()})
    for old, new in names.items():
        connection.execute(sa.update(_log).where(_log.c.node == old).values(node=new))
    jobs = sa.select(_jobs.c.id, _jobs.c.payload, _jobs.c.dedup_key).where(
        _jobs.c.kind.in_(_NODE_JOBS)
    )
    for row in connection.execute(jobs).mappings():
        node = _node_of(row["payload"])
        if node in names:
            connection.execute(
                sa.update(_jobs)
                .where(_jobs.c.id == row["id"])
                .values(
                    payload={**row["payload"], "node": names[node]},
                    dedup_key=_renamed_key(row["dedup_key"], names),
                )
            )
    events = sa.select(_outbox.c.seq, _outbox.c.payload).where(_outbox.c.type.in_(_NODE_EVENTS))
    for row in connection.execute(events).mappings():
        node = _node_of(row["payload"])
        if node in names:
            connection.execute(
                sa.update(_outbox)
                .where(_outbox.c.seq == row["seq"])
                .values(payload={**row["payload"], "node": names[node]})
            )


def _renamed_key(key: str | None, names: dict[str, str]) -> str | None:
    """`<document>:<run>:<node>[:catch-up]` with the node renamed."""
    if key is None:
        return None
    parts = key.split(":")
    if len(parts) >= 3 and parts[2] in names:
        parts[2] = names[parts[2]]
    return ":".join(parts)


def _state(status: str) -> dict[str, Any]:
    return {"status": status, "outcome": None, "started_at": None, "finished_at": None}


def _store(connection: sa.Connection, document: Any, nodes: dict[str, Any]) -> None:
    connection.execute(
        sa.update(_documents).where(_documents.c.id == document).values(processing_nodes=nodes)
    )


def _parsed(nodes: dict[str, Any]) -> bool:
    parse = nodes.get("parse", {})
    return parse.get("status") == "done" and parse.get("outcome") in _PARSED


def _node_of(payload: Any) -> str | None:
    node = payload.get("node") if isinstance(payload, dict) else None
    return node if isinstance(node, str) else None


def _drop_jobs(connection: sa.Connection, document: Any, nodes: Sequence[str]) -> None:
    """Queued and running node jobs of the document for `nodes`."""
    rows = connection.execute(
        sa.select(_jobs.c.id, _jobs.c.payload).where(
            _jobs.c.kind == "pipeline.node", _jobs.c.status.in_(_ACTIVE)
        )
    ).mappings()
    for row in rows:
        payload = row["payload"]
        if (
            isinstance(payload, dict)
            and payload.get("document_id") == str(document)
            and payload.get("node") in nodes
        ):
            connection.execute(sa.delete(_jobs).where(_jobs.c.id == row["id"]))


def _has_job(connection: sa.Connection, document: Any, run: int, node: str) -> bool:
    found = connection.execute(
        sa.select(_jobs.c.id).where(
            _jobs.c.dedup_key == f"{document}:{run}:{node}", _jobs.c.status.in_(_ACTIVE)
        )
    ).first()
    return found is not None


def _queue(connection: sa.Connection, document: Any, run: int, nodes: Sequence[str]) -> None:
    now = datetime.now(UTC)
    for node in nodes:
        connection.execute(
            sa.insert(_jobs).values(
                id=_new_id(),
                kind="pipeline.node",
                payload={"document_id": str(document), "node": node, "run": run},
                dedup_key=f"{document}:{run}:{node}",
                status="queued",
                attempts=0,
                releases=0,
                run_at=now,
            )
        )


def _new_id() -> uuid.UUID:
    """A UUIDv7, as `lekto.core.domain.ids.new_id` makes it today (a revision keeps its own
    copy)."""
    milliseconds = time.time_ns() // 1_000_000 & ((1 << 48) - 1)
    random = int.from_bytes(os.urandom(10))
    value = milliseconds << 80 | random
    value = value & ~(0xF << 76) | 0x7 << 76  # version 7
    value = value & ~(0x3 << 62) | 0x2 << 62  # variant RFC 9562
    return uuid.UUID(int=value)
