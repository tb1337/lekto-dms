"""Relation targets

Revision ID: 0049
Revises: 0048
Create Date: 2026-10-26 10:00:00.000000

An admin marks a document type as a relation target (issue #145, `.idea/bezuege.md`, decision
8): a contract or customer number a document shares connects it only with documents of such a
type. No type is one yet. The column is added in place on both databases.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_types",
        sa.Column("relation_target", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("document_types", "relation_target")
