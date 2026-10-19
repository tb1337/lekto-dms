"""The identifiers each document shows

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-15 20:00:00.000000

The facts signal keeps the identifiers it found on a document (in its text or its codes) in
`document_identifiers`, so that Papiq can tell on how many contacts' confirmed documents a value
stands. Documents processed before get theirs when their signals run again, or with the command
`read-codes`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_identifiers",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id", "kind", "value"),
    )
    op.create_index("ix_document_identifiers_kind_value", "document_identifiers", ["kind", "value"])


def downgrade() -> None:
    op.drop_index("ix_document_identifiers_kind_value", table_name="document_identifiers")
    op.drop_table("document_identifiers")
