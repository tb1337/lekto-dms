"""Reading a document with the vision language model

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-15 18:00:00.000000

A person can have a document read again with the vision language model (`POST
/documents/{id}/vision`). The processing run that does it keeps the request in
`documents.processing_vision`, so that a retry of the OCR node reads with the model too.
Documents processed before were read by Tesseract: false.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("processing_vision", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    # Not a batch operation: on SQLite, it would copy the table, which others refer to.
    op.drop_column("documents", "processing_vision")
