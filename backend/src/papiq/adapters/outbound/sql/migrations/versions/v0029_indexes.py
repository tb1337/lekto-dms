"""Indexes for list filters, field queries and the cleanup

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-18 12:00:00.000000

The list filters by lane, contact, type and tag, the queries by field (`field_in_use`, the field
filter and counts) and the deletion checks by them scanned `documents`, `document_tags` and
`document_fields`; the cleanup scanned `outbox`, `sessions` and `event_retries`, and claiming a
job whose lease ran out `jobs` (M13 review A-05; 0.3.0 review Q-03). Postgres makes no index for
a foreign key of its own.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("documents", ("lane",)),
    ("documents", ("contact_id",)),
    ("documents", ("document_type_id",)),
    ("document_tags", ("tag_id",)),
    ("document_fields", ("field_id",)),
    ("outbox", ("recorded_at",)),
    ("sessions", ("last_seen_at",)),
    ("sessions", ("expires_at",)),
    ("event_retries", ("retry_at",)),
    ("jobs", ("status", "locked_until")),
)


def _name(table: str, columns: tuple[str, ...]) -> str:
    return f"ix_{table}_{'_'.join(columns)}"


def upgrade() -> None:
    for table, columns in _INDEXES:
        op.create_index(_name(table, columns), table, list(columns))


def downgrade() -> None:
    for table, columns in reversed(_INDEXES):
        op.drop_index(_name(table, columns), table_name=table)
