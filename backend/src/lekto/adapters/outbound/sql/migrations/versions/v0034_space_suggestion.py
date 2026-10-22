"""Lekto suggests the space

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-22 02:00:00.000000

A space describes what belongs in it, for the language model (`spaces.description`), and a
document keeps when a person last decided its space (`documents.space_confirmed_at`): such a
space trains the classifier, and the judge leaves it (Tobi, 21.10.2026).

The backfill takes a person's decisions on the space from before, at the latest one: a
confirmation in the inbox (log entries `person`: the person kept or chose the space), a move by
a person or a space chosen on upload (`person:space`), and a document taken over from another
system (channel `migration`, at `confirmed_at`: the source system's permissions placed it). A
person changing the metadata (`confirmed_at` alone) decided nothing about the space. If rules
filed the document into another space after that decision (a space in the effects of a later
`rules` or `rules:change` entry), its space is the rules' again: undecided. Every other
document stays undecided: green documents nobody placed.

The columns have no keys, so SQLite adds them in place. The downgrade drops them.
"""

import json
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOCUMENTS = sa.table(
    "documents",
    sa.column("id", sa.Uuid()),
    sa.column("channel", sa.Text()),
    sa.column("confirmed_at", types.UtcDateTime()),
    sa.column("space_confirmed_at", types.UtcDateTime()),
)
_LOG = sa.table(
    "processing_log",
    sa.column("document_id", sa.Uuid()),
    sa.column("model_version", sa.Text()),
    sa.column("started_at", types.UtcDateTime()),
    sa.column("output", sa.JSON()),
)
_DECISIONS = ("person", "person:space")
_RULES = ("rules", "rules:change")
_MIGRATION = "migration"


def upgrade() -> None:
    op.add_column("spaces", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("space_confirmed_at", types.UtcDateTime(), nullable=True))
    connection = op.get_bind()
    decided: dict[object, datetime] = {}
    for document, at in connection.execute(
        sa.select(_DOCUMENTS.c.id, _DOCUMENTS.c.confirmed_at).where(
            _DOCUMENTS.c.channel == _MIGRATION, _DOCUMENTS.c.confirmed_at.is_not(None)
        )
    ):
        decided[document] = at
    for document, at in connection.execute(
        sa.select(_LOG.c.document_id, sa.func.max(_LOG.c.started_at))
        .where(_LOG.c.model_version.in_(_DECISIONS))
        .group_by(_LOG.c.document_id)
    ):
        if document not in decided or decided[document] < at:
            decided[document] = at
    for document, at, output in connection.execute(
        sa.select(_LOG.c.document_id, _LOG.c.started_at, _LOG.c.output).where(
            _LOG.c.model_version.in_(_RULES)
        )
    ):
        if document in decided and at > decided[document] and _files(output):
            del decided[document]
    for document, at in decided.items():
        connection.execute(
            sa.update(_DOCUMENTS).where(_DOCUMENTS.c.id == document).values(space_confirmed_at=at)
        )


def _files(output: object) -> bool:
    """Whether a rules entry's output filed the document into a space (an applied effect on
    the field `space`)."""
    if isinstance(output, str):
        output = json.loads(output)
    if not isinstance(output, dict):
        return False
    reports = output.get("rules")
    return isinstance(reports, list) and any(
        isinstance(report, dict)
        and isinstance(report.get("applied"), list)
        and any(
            isinstance(effect, dict) and effect.get("field") == "space"
            for effect in report["applied"]
        )
        for report in reports
    )


def downgrade() -> None:
    # Not a batch operation: on SQLite, it would copy the table, which others refer to.
    op.drop_column("documents", "space_confirmed_at")
    op.drop_column("spaces", "description")
