"""Webhooks as model calls, and what a task's node needs to read its answer

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-25 22:00:00.000000

An admin's webhook may take over a request to the language model (Tobi, 25.10.2026,
`webhooks-und-auftraege.md`): `webhooks.model_call` names it (`propose` or `extract`, NULL for
none), `webhooks.model_call_timeout_seconds` the consumer's time to answer. `tasks.context`
keeps what the node sent and needs to read the answer (the keys of a model call's fields and
spaces).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("webhooks", sa.Column("model_call", sa.Text(), nullable=True))
    op.add_column("webhooks", sa.Column("model_call_timeout_seconds", sa.Integer(), nullable=True))
    op.add_column(
        "tasks", sa.Column("context", types.json_type(), nullable=False, server_default="{}")
    )


def downgrade() -> None:
    op.drop_column("tasks", "context")
    op.drop_column("webhooks", "model_call_timeout_seconds")
    op.drop_column("webhooks", "model_call")
