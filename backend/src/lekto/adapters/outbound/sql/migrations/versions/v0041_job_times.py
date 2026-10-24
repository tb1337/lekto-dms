"""When a job started and finished, and what it did

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-24 21:00:00.000000

The page "System" shows the jobs with their state, how long they waited and how long they ran
(Tobi, 24.10.2026): a job keeps when its latest claim took it (`jobs.started_at`), when it was
done or given up (`jobs.finished_at`) and what a done job reports of its work (`jobs.result`,
JSON; the search index: how many sections it embedded). The durations of the jobs done lately
are read by `finished_at` (an index). Existing jobs have none of the three.

The columns have no keys, so SQLite adds them in place. The downgrade drops them and the index.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("started_at", types.UtcDateTime(), nullable=True))
    op.add_column("jobs", sa.Column("finished_at", types.UtcDateTime(), nullable=True))
    op.add_column("jobs", sa.Column("result", types.json_type(), nullable=True))
    op.create_index("ix_jobs_finished_at", "jobs", ["finished_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_finished_at", table_name="jobs")
    # Not batch operations: on SQLite, they would copy the table.
    op.drop_column("jobs", "result")
    op.drop_column("jobs", "finished_at")
    op.drop_column("jobs", "started_at")
