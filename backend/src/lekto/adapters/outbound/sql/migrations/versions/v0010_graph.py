"""The pipeline is a graph: the state of every node replaces the current node and the outcomes

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-12 21:00:00.000000

`documents.processing_node` and `processing_outcomes` become `processing_nodes`, the state of
every node of the graph in the current run: `{node: {status, outcome, started_at, finished_at}}`.
A node with an outcome is `done`; its start and end come from its latest processing log entry
(the document's `updated_at` if there is none). The current node of a processing or reviewed
document is `waiting`, as is every later node. The new node `pages` is `skipped` for every
existing document; the command `render-pages` catches up on it.

The downgrade derives the current node again: the running node of a processing document,
else its first waiting node, the failed node, `file` of a reviewed document, none of a
completed one. The state of `pages` is lost, and a document whose only open nodes are `pages`
and `file` (reprocessed from the pages) has no job for `file` under 0.1: reprocess it there.

Columns are added and dropped in place (SQLite 3.35 or newer drops columns), never by
recreating the table: with foreign keys enforced, dropping the old table would take the
documents' log entries, tags and field values with it.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The graph at this revision, in topological order.
_NODES = ("receive", "ocr", "pages", "parse", "classify", "extract_fields", "apply_rules", "file")
_NEW = "pages"
# Log entries that are no run of the node: written by rules outside processing or by a person.
_NOT_A_RUN = ("rules:change", "rules:apply", "person:drawer", "person")

_documents = sa.table(
    "documents",
    sa.column("id"),
    sa.column("processing_status", sa.Text()),
    sa.column("processing_node", sa.Text()),
    sa.column("processing_run", sa.Integer()),
    sa.column("processing_outcomes", types.json_type()),
    sa.column("processing_nodes", types.json_type()),
    sa.column("updated_at", types.UtcDateTime()),
)
_log = sa.table(
    "processing_log",
    sa.column("seq"),
    sa.column("document_id"),
    sa.column("node", sa.Text()),
    sa.column("model_version", sa.Text()),
    sa.column("started_at", types.UtcDateTime()),
    sa.column("duration_us", sa.BigInteger()),
)


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("processing_nodes", types.json_type(), nullable=False, server_default="{}"),
    )
    connection = op.get_bind()
    columns = [
        _documents.c.id,
        _documents.c.processing_status,
        _documents.c.processing_node,
        _documents.c.processing_outcomes,
        _documents.c.updated_at,
    ]
    for row in connection.execute(sa.select(*columns)).mappings():
        nodes = _nodes(
            row["processing_status"],
            row["processing_node"],
            row["processing_outcomes"] or {},
            _times(connection, row["id"]),
            row["updated_at"],
        )
        connection.execute(
            _documents.update().where(_documents.c.id == row["id"]).values(processing_nodes=nodes)
        )
    op.drop_column("documents", "processing_node")
    op.drop_column("documents", "processing_outcomes")


def downgrade() -> None:
    op.add_column("documents", sa.Column("processing_node", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("processing_outcomes", types.json_type(), nullable=False, server_default="{}"),
    )
    connection = op.get_bind()
    columns = [_documents.c.id, _documents.c.processing_status, _documents.c.processing_nodes]
    for row in connection.execute(sa.select(*columns)).mappings():
        nodes = row["processing_nodes"] or {}
        outcomes = {
            name: state["outcome"]
            for name, state in nodes.items()
            if name != _NEW and state.get("outcome") is not None
        }
        connection.execute(
            _documents.update()
            .where(_documents.c.id == row["id"])
            .values(
                processing_node=_current(row["processing_status"], nodes),
                processing_outcomes=outcomes,
            )
        )
    op.drop_column("documents", "processing_nodes")


def _nodes(
    status: str,
    current: str | None,
    outcomes: dict[str, Any],
    times: dict[str, tuple[datetime, datetime]],
    fallback: datetime,
) -> dict[str, Any]:
    nodes: dict[str, Any] = {}
    for name in _NODES:
        if name == _NEW:
            nodes[name] = _state("skipped")
        elif name in outcomes:
            started, finished = times.get(name, (fallback, fallback))
            nodes[name] = _state("done", outcomes[name], started, finished)
        elif status == "completed":
            nodes[name] = _state("skipped")
        else:
            nodes[name] = _state("waiting")
    if current is not None and status in ("processing", "review"):
        nodes[current] = _state("waiting")
    return nodes


def _state(
    status: str,
    outcome: str | None = None,
    started: datetime | None = None,
    finished: datetime | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "outcome": outcome,
        "started_at": None if started is None else started.isoformat(),
        "finished_at": None if finished is None else finished.isoformat(),
    }


def _times(connection: sa.Connection, document_id: Any) -> dict[str, tuple[datetime, datetime]]:
    """Start and end of the latest processing log entry of each node."""
    rows = connection.execute(
        sa.select(_log.c.node, _log.c.started_at, _log.c.duration_us)
        .where(_log.c.document_id == document_id)
        .where(_log.c.model_version.is_(None) | _log.c.model_version.not_in(_NOT_A_RUN))
        .order_by(_log.c.seq)
    )
    times = {}
    for node, started, duration_us in rows:
        times[node] = (started, started + timedelta(microseconds=duration_us))
    return times


def _current(status: str, nodes: dict[str, Any]) -> str | None:
    if status == "completed":
        return None
    if status == "review":
        return "file"
    if status == "failed":
        failed = [name for name in _NODES if nodes.get(name, {}).get("outcome") == "failed"]
        return failed[0] if failed else None
    for wanted in ("running", "waiting"):
        found = [
            name for name in _NODES if name != _NEW and nodes.get(name, {}).get("status") == wanted
        ]
        if found:
            return found[0]
    return None
