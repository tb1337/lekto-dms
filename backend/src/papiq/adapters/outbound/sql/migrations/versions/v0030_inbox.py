"""The inbox: new, seen and done

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-18 18:00:00.000000

A document that processing turns green without a person's decision is new in the inbox
(`documents.new_at`, with an index for the inbox queries); the current run keeps what decides
it (`processing_baseline`, `processing_decided`). `inbox_seen` keeps when each user saw a
document last (it goes with the user and the document; an index on the document for the
latter), `inbox_confirmations` who confirmed a document out of yellow or red last (with the
document; an index on the time for done and the cleanup, which removes it after 14 days).

Every document from before stays without: after the update nothing is new, and a run started
before makes no document new unless it is its first. Nothing is seen or confirmed yet.

The columns have no keys, so SQLite adds them in place. The downgrade drops tables and columns.
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
    op.create_table(
        "inbox_seen",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("seen_at", types.UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_inbox_seen_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_inbox_seen_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "document_id", name="pk_inbox_seen"),
    )
    op.create_index("ix_inbox_seen_document_id", "inbox_seen", ["document_id"])
    op.create_table(
        "inbox_confirmations",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=False),
        sa.Column("confirmed_at", types.UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_inbox_confirmations_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", name="pk_inbox_confirmations"),
    )
    op.create_index("ix_inbox_confirmations_confirmed_at", "inbox_confirmations", ["confirmed_at"])


def downgrade() -> None:
    op.drop_table("inbox_confirmations")
    op.drop_table("inbox_seen")
    op.drop_index("ix_documents_new_at", table_name="documents")
    # Not a batch operation: on SQLite, it would copy the table, which others refer to.
    for column in ("new_at", "processing_decided", "processing_baseline"):
        op.drop_column("documents", column)
