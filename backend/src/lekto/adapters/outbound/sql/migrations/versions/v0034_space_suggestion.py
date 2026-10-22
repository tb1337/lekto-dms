"""Lekto suggests the space

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-22 02:00:00.000000

A space describes what belongs in it, for the language model (`spaces.description`), and a
document keeps when a person last decided its space (`documents.space_confirmed_at`): such a
space trains the classifier, and the judge leaves it (Tobi, 21.10.2026).

The backfill takes a person's decisions from before: a document confirmed in the inbox or
taken over from another system (`confirmed_at`) had its space confirmed with it; one a person
moved, or chose the space of on upload (log entries `person:space`), at the latest such entry.
Every other document stays undecided: green documents nobody placed.

The columns have no keys, so SQLite adds them in place. The downgrade drops them.
"""

from collections.abc import Sequence

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
    sa.column("confirmed_at", types.UtcDateTime()),
    sa.column("space_confirmed_at", types.UtcDateTime()),
)
_LOG = sa.table(
    "processing_log",
    sa.column("document_id", sa.Uuid()),
    sa.column("model_version", sa.Text()),
    sa.column("started_at", types.UtcDateTime()),
)
_PERSON_SPACE = "person:space"


def upgrade() -> None:
    op.add_column("spaces", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("space_confirmed_at", types.UtcDateTime(), nullable=True))
    connection = op.get_bind()
    connection.execute(
        sa.update(_DOCUMENTS)
        .where(_DOCUMENTS.c.confirmed_at.is_not(None))
        .values(space_confirmed_at=_DOCUMENTS.c.confirmed_at)
    )
    chosen = connection.execute(
        sa.select(_LOG.c.document_id, sa.func.max(_LOG.c.started_at))
        .where(_LOG.c.model_version == _PERSON_SPACE)
        .group_by(_LOG.c.document_id)
    ).all()
    for document, at in chosen:
        current = connection.execute(
            sa.select(_DOCUMENTS.c.space_confirmed_at).where(_DOCUMENTS.c.id == document)
        ).scalar_one_or_none()
        if current is None or current < at:
            connection.execute(
                sa.update(_DOCUMENTS)
                .where(_DOCUMENTS.c.id == document)
                .values(space_confirmed_at=at)
            )


def downgrade() -> None:
    # Not a batch operation: on SQLite, it would copy the table, which others refer to.
    op.drop_column("documents", "space_confirmed_at")
    op.drop_column("spaces", "description")
