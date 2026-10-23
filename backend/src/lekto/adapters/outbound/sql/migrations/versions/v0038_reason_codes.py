"""The reasons of a log entry with their codes

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-23 21:00:00.000000

A processing log entry keeps its reasons with their codes (`processing_log.reasons`, issue
#83) beside the English text (`reason`), so clients can give them in their language. Entries
written before have none: their text stays as it is, read as written (Tobi, 23.10.2026: no
translating back).

The column has no keys, so SQLite adds it in place. The downgrade drops it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("processing_log", sa.Column("reasons", types.json_type(), nullable=True))


def downgrade() -> None:
    # Not a batch operation: on SQLite, it would copy the table.
    op.drop_column("processing_log", "reasons")
