"""The node `relate` between `fields` and `apply_rules`

Revision ID: 0050
Revises: 0049
Create Date: 2026-10-26 12:00:00.000000

A new node finds the documents a document refers to, and those that refer to it (issue #145,
`.idea/bezuege.md`), before the rules see them. Every document gets its state: one whose rules
ran (or were skipped, or wait for a webhook) has it `skipped`, as revision 0016 did for the
signals; the command `relate` finds the relations of documents from before. One whose rules
still wait (or were running) gets it waiting: a queued job of its rules is dropped, as they are
no longer due, and once its fields are read, a job for `relate` takes its place.

The downgrade drops the node from the states, the log, the jobs and the undelivered events; a
document whose `relate` waits gets a job for its rules again once its fields are read.
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

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RELATE = "relate"
_RULES = "apply_rules"
_NODE_JOBS = ("pipeline.node", "pipeline.catch_up")
_NODE_EVENTS = ("document.node_started", "document.node_completed", "document.node_deferred")
_ACTIVE = ("queued", "running")
_READ = ("ok", "uncertain")

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
    waiting = []
    for row in connection.execute(sa.select(_documents)).mappings():
        nodes = dict(row["processing_nodes"] or {})
        if nodes.get(_RULES, {}).get("status") in ("waiting", "running"):
            nodes[_RULES] = _state("waiting")
            nodes[_RELATE] = _state("waiting")
            waiting.append((row["id"], row["processing_run"], nodes))
        else:
            nodes[_RELATE] = _state("skipped")
        _store(connection, row["id"], nodes)
    _drop_jobs(connection, {str(document) for document, _, _ in waiting}, _RULES)
    for document, run, nodes in waiting:
        if _satisfied(nodes.get("fields", {})):
            _queue(connection, document, run, _RELATE)


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.delete(_log).where(_log.c.node == _RELATE))
    # Finding relations outside processing is unknown before.
    connection.execute(sa.delete(_jobs).where(_jobs.c.kind == "pipeline.relate"))
    for row in connection.execute(
        sa.select(_jobs.c.id, _jobs.c.payload).where(_jobs.c.kind.in_(_NODE_JOBS))
    ).mappings():
        if _node_of(row["payload"]) == _RELATE:
            connection.execute(sa.delete(_jobs).where(_jobs.c.id == row["id"]))
    for row in connection.execute(
        sa.select(_outbox.c.seq, _outbox.c.payload).where(_outbox.c.type.in_(_NODE_EVENTS))
    ).mappings():
        if _node_of(row["payload"]) == _RELATE:
            connection.execute(sa.delete(_outbox).where(_outbox.c.seq == row["seq"]))
    waiting = []
    for row in connection.execute(sa.select(_documents)).mappings():
        nodes = dict(row["processing_nodes"] or {})
        relate = nodes.pop(_RELATE, {})
        if relate.get("status") in ("waiting", "running"):
            nodes[_RULES] = _state("waiting")
            waiting.append((row["id"], row["processing_run"], nodes))
        _store(connection, row["id"], nodes)
    for document, run, nodes in waiting:
        if _satisfied(nodes.get("fields", {})) and not _has_job(connection, document, run, _RULES):
            _queue(connection, document, run, _RULES)


def _state(status: str) -> dict[str, Any]:
    return {"status": status, "outcome": None, "started_at": None, "finished_at": None}


def _store(connection: sa.Connection, document: Any, nodes: dict[str, Any]) -> None:
    connection.execute(
        sa.update(_documents).where(_documents.c.id == document).values(processing_nodes=nodes)
    )


def _satisfied(state: dict[str, Any]) -> bool:
    """Whether the nodes after it may run: done without failing, or skipped."""
    status = state.get("status")
    return status == "skipped" or (status == "done" and state.get("outcome") in _READ)


def _node_of(payload: Any) -> str | None:
    node = payload.get("node") if isinstance(payload, dict) else None
    return node if isinstance(node, str) else None


def _drop_jobs(connection: sa.Connection, documents: set[str], node: str) -> None:
    """Queued and running node jobs of `documents` for `node`, in one pass over the jobs."""
    rows = connection.execute(
        sa.select(_jobs.c.id, _jobs.c.payload).where(
            _jobs.c.kind == "pipeline.node", _jobs.c.status.in_(_ACTIVE)
        )
    ).mappings()
    dropped = [
        row["id"]
        for row in rows
        if isinstance(row["payload"], dict)
        and row["payload"].get("document_id") in documents
        and row["payload"].get("node") == node
    ]
    for start in range(0, len(dropped), 500):
        connection.execute(sa.delete(_jobs).where(_jobs.c.id.in_(dropped[start : start + 500])))


def _has_job(connection: sa.Connection, document: Any, run: int, node: str) -> bool:
    found = connection.execute(
        sa.select(_jobs.c.id).where(
            _jobs.c.dedup_key == f"{document}:{run}:{node}", _jobs.c.status.in_(_ACTIVE)
        )
    ).first()
    return found is not None


def _queue(connection: sa.Connection, document: Any, run: int, node: str) -> None:
    connection.execute(
        sa.insert(_jobs).values(
            id=_new_id(),
            kind="pipeline.node",
            payload={"document_id": str(document), "node": node, "run": run},
            dedup_key=f"{document}:{run}:{node}",
            status="queued",
            attempts=0,
            releases=0,
            run_at=datetime.now(UTC),
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
