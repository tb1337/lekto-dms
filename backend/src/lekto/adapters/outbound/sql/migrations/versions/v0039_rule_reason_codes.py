"""Why a rule was disabled, with its code

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-24 03:00:00.000000

A rule disabled automatically keeps why with its code (`rules.disabled_reasons`, issue #83)
beside the English text (`disabled_reason`), so clients can give it in their language. Rules
disabled before have none: their text stays as it is, read as written.

The column has no keys, so SQLite adds it in place. The downgrade drops it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rules", sa.Column("disabled_reasons", types.json_type(), nullable=True))


def downgrade() -> None:
    # Not a batch operation: on SQLite, it would copy the table.
    op.drop_column("rules", "disabled_reasons")
