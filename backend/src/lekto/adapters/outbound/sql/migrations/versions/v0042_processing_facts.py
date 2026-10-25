"""The first run of each document and the verdicts per field

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-25 12:00:00.000000

The page "System" shows how documents went through their first run and how people judged what
the automation set (Tobi, 24. and 25.10.2026, `domain.first_runs`): `first_runs` keeps per
document when its receiving began, when its first run first stopped and how long each node
worked in it; `field_verdicts` per document and field the verdict at a person's first decision
on it, and per signal whether it named the person's value. Both go with their document.

The downgrade drops both tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "first_runs",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", types.UtcDateTime(), nullable=False),
        sa.Column("stopped_at", types.UtcDateTime(), nullable=False),
        sa.Column("steps", types.json_type(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_first_runs_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", name="pk_first_runs"),
    )
    op.create_index("ix_first_runs_stopped_at", "first_runs", ["stopped_at"])
    op.create_table(
        "field_verdicts",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("decided_at", types.UtcDateTime(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("signal_llm", sa.Boolean(), nullable=True),
        sa.Column("signal_classifier", sa.Boolean(), nullable=True),
        sa.Column("signal_neighbours", sa.Boolean(), nullable=True),
        sa.Column("signal_facts", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_field_verdicts_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "field", name="pk_field_verdicts"),
    )
    op.create_index("ix_field_verdicts_decided_at", "field_verdicts", ["decided_at"])


def downgrade() -> None:
    op.drop_index("ix_field_verdicts_decided_at", table_name="field_verdicts")
    op.drop_table("field_verdicts")
    op.drop_index("ix_first_runs_stopped_at", table_name="first_runs")
    op.drop_table("first_runs")
