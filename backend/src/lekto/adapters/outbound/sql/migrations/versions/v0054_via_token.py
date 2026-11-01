"""The API token a person decided through

Revision ID: 0054
Revises: 0053
Create Date: 2026-11-01 18:00:00.000000

A decision through an API token carries the token (Tobi, 01.11.2026, umsetzungsplan "MCP",
decision 11): a verdict through a script or an assistant stays apart from one in the web UI.
Each table that keeps who decided gets `via_token_id` and `via_token_name` beside it, without a
foreign key and the name as a copy, so both stay once the token is revoked. Rows from before
have none: they were decided in the web UI or through a token nobody can name any more.

The columns have no keys, so SQLite adds them in place. The downgrade drops them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "document_relations",
    "field_verdicts",
    "inbox_seen",
    "inbox_confirmations",
    "rule_applications",
    "bulk_operations",
)


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("via_token_id", sa.Uuid(), nullable=True))
        op.add_column(table, sa.Column("via_token_name", sa.Text(), nullable=True))


def downgrade() -> None:
    # Not a batch operation: on SQLite, it would copy the table.
    for table in TABLES:
        op.drop_column(table, "via_token_name")
        op.drop_column(table, "via_token_id")
