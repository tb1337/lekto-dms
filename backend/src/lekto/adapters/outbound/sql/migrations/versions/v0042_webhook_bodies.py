"""Webhooks: a full body or one of their own template

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-25 14:00:00.000000

What a webhook's requests carry (Tobi, 25.10.2026, `webhooks-und-auftraege.md`):
`webhooks.body` is `thin` (the event, as before), `full` (the document too) or `template` (what
`webhooks.body_template`, Liquid, makes of them). Existing webhooks stay thin.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("webhooks", sa.Column("body", sa.Text(), nullable=False, server_default="thin"))
    op.add_column("webhooks", sa.Column("body_template", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("webhooks", "body_template")
    op.drop_column("webhooks", "body")
