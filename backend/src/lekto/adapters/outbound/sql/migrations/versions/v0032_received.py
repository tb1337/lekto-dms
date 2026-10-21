"""When documents came in

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-21 12:00:00.000000

A document's `created_at` is when it came in, and may now be set: a migration takes over the
source system's date, a person corrects it (Tobi, 21.10.2026). Lists sorted by it page by it
and the id, no longer by the id alone, which stays the order documents reached Lekto. The
downgrade drops the index.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "ix_documents_created_at_id"


def upgrade() -> None:
    op.create_index(_NAME, "documents", ["created_at", "id"])


def downgrade() -> None:
    op.drop_index(_NAME, table_name="documents")
