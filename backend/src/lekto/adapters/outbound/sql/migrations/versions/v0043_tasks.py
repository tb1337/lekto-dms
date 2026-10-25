"""Tasks: requests through a webhook that expect an answer

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-25 18:00:00.000000

A rule step that asks a webhook hands its request to a task and waits for the answer (Tobi,
25.10.2026, `webhooks-und-auftraege.md`). `tasks` keeps them, without foreign keys: a task
outlives its webhook and its document. `webhooks.max_open_tasks`: how many tasks a webhook takes
at the same time (4 for existing webhooks).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "webhooks",
        sa.Column("max_open_tasks", sa.Integer(), nullable=False, server_default="4"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("node", sa.Text(), nullable=False),
        sa.Column("run", sa.Integer(), nullable=False),
        sa.Column("webhook_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("step", types.json_type(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=True),
        sa.Column("request", sa.LargeBinary(), nullable=True),
        sa.Column("answer", types.json_type(), nullable=True),
        sa.Column("producer", sa.Text(), nullable=True),
        sa.Column("reason", types.json_type(), nullable=True),
        sa.Column("created_at", types.UtcDateTime(), nullable=False),
        sa.Column("opened_at", types.UtcDateTime(), nullable=True),
        sa.Column("deadline", types.UtcDateTime(), nullable=True),
        sa.Column("settled_at", types.UtcDateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(op.f("ix_tasks_document_id_node_run"), "tasks", ["document_id", "node", "run"])
    op.create_index(
        op.f("ix_tasks_webhook_id_status_created_at"),
        "tasks",
        ["webhook_id", "status", "created_at"],
    )
    op.create_index(op.f("ix_tasks_settled_at"), "tasks", ["settled_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_tasks_settled_at"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_webhook_id_status_created_at"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_document_id_node_run"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_column("webhooks", "max_open_tasks")
