"""Lenses

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-20 12:00:00.000000

A user's saved looks at the documents (`lenses`): filter and card fields as JSON, names unique
per user regardless of case (the unique index serves the user's list too). They go with the
user. Nobody has one after the update. The downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("filter", types.json_type(), nullable=False),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("sort", sa.Text(), nullable=True),
        sa.Column("sort_field_id", sa.Uuid(), nullable=True),
        sa.Column("grouping", sa.Text(), nullable=False),
        sa.Column("layout", sa.Text(), nullable=False),
        sa.Column("card_field_ids", types.json_type(), nullable=False),
        sa.Column("due_field_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", types.UtcDateTime(), nullable=False),
        sa.Column("updated_at", types.UtcDateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_lenses_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lenses")),
    )
    op.create_index(
        op.f("ix_lenses_owner_id_name_key"), "lenses", ["owner_id", "name_key"], unique=True
    )


def downgrade() -> None:
    op.drop_table("lenses")
