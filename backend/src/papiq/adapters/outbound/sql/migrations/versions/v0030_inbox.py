"""The inbox: new documents

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-18 18:00:00.000000

A document that processing turns green without a person's decision is new in the inbox
(`documents.new_at`, with an index for the inbox queries); the current run keeps what decides
it (`processing_baseline`, `processing_decided`). Every document from before stays without:
after the update nothing is new, and a run started before makes no document new unless it is
its first.

Plain columns without keys: SQLite adds them in place. The downgrade drops them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from papiq.adapters.outbound.sql import types

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("processing_baseline", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("processing_decided", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("documents", sa.Column("new_at", types.UtcDateTime(), nullable=True))
    op.create_index("ix_documents_new_at", "documents", ["new_at"])


def downgrade() -> None:
    op.drop_index("ix_documents_new_at", table_name="documents")
    # Not a batch operation: on SQLite, it would copy the table, which others refer to.
    for column in ("new_at", "processing_decided", "processing_baseline"):
        op.drop_column("documents", column)
