"""Jobs that coalesce while queued

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-23 15:30:00.000000

A job may carry a coalesce key (`jobs.coalesce_key`): while one job with the key is queued,
enqueueing another does nothing, and claiming the job clears the key. The search index uses it:
every event of a document queued an index job of its own, a dozen per document while it is
processed, and they kept the worker from the pipeline (Tobi's migration into Lekto prod,
23.10.2026). Existing jobs have none.

The column has no keys, so SQLite adds it in place; the unique index comes after it. The
downgrade drops both.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("coalesce_key", sa.Text(), nullable=True))
    op.create_index("uq_jobs_coalesce_key", "jobs", ["coalesce_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_jobs_coalesce_key", table_name="jobs")
    # Not a batch operation: on SQLite, it would copy the table.
    op.drop_column("jobs", "coalesce_key")
