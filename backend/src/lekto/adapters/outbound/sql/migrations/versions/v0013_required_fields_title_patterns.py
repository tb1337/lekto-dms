"""Required and optional fields, title patterns of document types

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-13 19:00:00.000000

A field bound to document types was required before: extraction turned the document yellow
when it found no value. Its assignments stay required; global fields were optional and stay so.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "field_definitions",
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "field_document_types",
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("document_types", sa.Column("title_pattern", sa.Text(), nullable=True))


def downgrade() -> None:
    # Not batch operations: on SQLite, they would copy the tables, which others refer to.
    op.drop_column("document_types", "title_pattern")
    op.drop_column("field_document_types", "required")
    op.drop_column("field_definitions", "required")
