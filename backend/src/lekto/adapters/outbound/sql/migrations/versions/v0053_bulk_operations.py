"""Actions on many documents at once

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-29 16:00:00.000000

The documents list changes many documents at once (`.idea/umsetzungsplan.md`, "Massenaktionen
und Seiten in der Dokumentliste"): an action on the documents a person selected, worked through
in the background. `bulk_operations` keeps each with its documents and how far it is.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bulk_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("action", types.json_type(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("documents", types.json_type(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("changed", sa.Integer(), nullable=False),
        sa.Column("unchanged", sa.Integer(), nullable=False),
        sa.Column("skipped", types.json_type(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", types.UtcDateTime(), nullable=False),
        sa.Column("finished_at", types.UtcDateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_bulk_operations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bulk_operations")),
    )
    op.create_index(op.f("ix_bulk_operations_user_id"), "bulk_operations", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_bulk_operations_user_id"), table_name="bulk_operations")
    op.drop_table("bulk_operations")
