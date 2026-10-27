"""Relations between documents

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-26 08:00:00.000000

A document refers to an older one (issue #145, `.idea/bezuege.md`): `document_relations` keeps
the newer document, the older one, where the relation comes from (a person, Lekto), whether it
is set, suggested or rejected, the evidence Lekto had, and who decided it last. A relation goes
with either of its documents.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_relations",
        sa.Column("newer_id", sa.Uuid(), nullable=False),
        sa.Column("older_id", sa.Uuid(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("evidence", types.json_type(), nullable=False, server_default="{}"),
        sa.Column("created_at", types.UtcDateTime(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", types.UtcDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["newer_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["older_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("newer_id", "older_id"),
    )
    op.create_index("ix_document_relations_older_id", "document_relations", ["older_id"])


def downgrade() -> None:
    op.drop_index("ix_document_relations_older_id", table_name="document_relations")
    op.drop_table("document_relations")
