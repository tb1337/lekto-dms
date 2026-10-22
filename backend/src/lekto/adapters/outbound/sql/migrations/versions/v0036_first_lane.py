"""The lane of the first run

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-23 00:30:00.000000

A document keeps the lane its first processing run ended in (`documents.first_lane`), whatever
a person or a later run made of it since: reports can tell how many documents went through
without a person (Tobi, 22.10.2026).

The backfill reads it back. A document still in its first run has none yet; one whose first
run stopped has it as its lane, which nothing changes before the next run. For a document
that ran again, the log of its first run tells. Filing made it green: the file node runs only
when nothing before it is uncertain or failed, whatever earlier entries of the run still say
(the rules may have settled an uncertain judge, a page catch-up may have failed afterwards).
Otherwise a failed node made it red, an uncertain result yellow. Entries a person or a change
set off (`person`, `person:space`, `rules:change`, `rules:apply`) are no part of the run's own
result, and neither is a text read again later (`reparse`), which changes no lane. Where the
log tells nothing, the lane stays unknown. The documents that ran again are read and updated
in chunks, so a large log needs no more memory than one chunk's entries.

The column has no keys, so SQLite adds it in place. The downgrade drops it.
"""

import json
from collections.abc import Iterable, Sequence
from itertools import batched

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOCUMENTS = sa.table(
    "documents",
    sa.column("id", sa.Uuid()),
    sa.column("lane", sa.Text()),
    sa.column("first_lane", sa.Text()),
    sa.column("processing_status", sa.Text()),
    sa.column("processing_run", sa.Integer()),
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
)
_NOT_THE_RUN = ("person", "person:space", "rules:change", "rules:apply")
_PROCESSING = "processing"
# Documents read and updated at a time: few enough bound parameters for any SQLite.
_CHUNK = 500


def upgrade() -> None:
    op.add_column("documents", sa.Column("first_lane", sa.Text(), nullable=True))
    connection = op.get_bind()
    connection.execute(
        sa.update(_DOCUMENTS)
        .where(_DOCUMENTS.c.processing_run == 1, _DOCUMENTS.c.processing_status != _PROCESSING)
        .values(first_lane=_DOCUMENTS.c.lane)
    )
    # Only the ids, read before the updates start: the entries come a chunk at a time.
    ran_again = (
        connection.execute(sa.select(_DOCUMENTS.c.id).where(_DOCUMENTS.c.processing_run > 1))
        .scalars()
        .all()
    )
    for chunk in batched(ran_again, _CHUNK, strict=False):
        lanes: dict[str, list[object]] = {}
        for document, lane in _first_lanes(connection, chunk).items():
            lanes.setdefault(lane, []).append(document)
        for lane, documents in lanes.items():
            connection.execute(
                sa.update(_DOCUMENTS).where(_DOCUMENTS.c.id.in_(documents)).values(first_lane=lane)
            )


def _first_lanes(connection: sa.Connection, documents: Sequence[object]) -> dict[object, str]:
    """The lanes the first runs of `documents` ended in, by their log, where it tells."""
    first_run = sa.and_(_LOG.c.run == 1, _LOG.c.document_id.in_(documents))
    reparsed = {
        seq
        for seq, input in connection.execute(
            sa.select(_LOG.c.seq, _LOG.c.input).where(
                first_run, _LOG.c.node == "parse", _LOG.c.outcome != "ok"
            )
        )
        if _reparse(input)
    }
    entries: dict[object, list[tuple[str, str]]] = {}
    for seq, document, node, outcome, version in connection.execute(
        sa.select(
            _LOG.c.seq, _LOG.c.document_id, _LOG.c.node, _LOG.c.outcome, _LOG.c.model_version
        ).where(first_run)
    ):
        if version not in _NOT_THE_RUN and seq not in reparsed:
            entries.setdefault(document, []).append((node, outcome))
    return {
        document: lane
        for document, results in entries.items()
        if (lane := _lane(results)) is not None
    }


def _lane(results: Iterable[tuple[str, str]]) -> str | None:
    """The lane a first run ended in by its nodes' results (`(node, outcome)`), if they tell:
    filed means green, whatever else the run logged."""
    found = list(results)
    if ("file", "ok") in found:
        return "green"
    outcomes = {outcome for _, outcome in found}
    if "failed" in outcomes:
        return "red"
    if "uncertain" in outcomes:
        return "yellow"
    return None


def _reparse(input: object) -> bool:
    """Whether a parse entry's input marks the text read again (`PipelineService`)."""
    if isinstance(input, str):
        input = json.loads(input)
    return isinstance(input, dict) and input.get("reparse") is True


def downgrade() -> None:
    # Not a batch operation: on SQLite, it would copy the table, which others refer to.
    op.drop_column("documents", "first_lane")
