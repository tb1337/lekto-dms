"""Trained classifiers

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-13 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classifier_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("trained_at", types.UtcDateTime(), nullable=False),
        sa.Column("examples", sa.Integer(), nullable=False),
        sa.Column("examples_until", types.UtcDateTime(), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("summary", types.json_type(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classifier_models")),
        sa.UniqueConstraint("number", name=op.f("uq_classifier_models_number")),
    )


def downgrade() -> None:
    op.drop_table("classifier_models")
