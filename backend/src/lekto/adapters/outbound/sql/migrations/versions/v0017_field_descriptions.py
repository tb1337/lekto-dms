"""Descriptions of fields

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-14 16:00:00.000000

A field's name is often an internal one no document shows; its description tells the language
model what belongs in it. Fields had none before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("field_definitions", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    # Not a batch operation: on SQLite, it would copy the table, which others refer to.
    op.drop_column("field_definitions", "description")
