"""Documents know their page count once the page images are rendered

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-12 22:00:00.000000

`documents.page_count` is set by the pages node; it is empty for documents whose pages were
not rendered yet (`render-pages` catches up on them).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "page_count")
