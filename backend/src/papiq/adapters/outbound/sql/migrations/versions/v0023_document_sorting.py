"""Lists sorted by title and date

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-16 10:00:00.000000

The document list sorts by document date, by when a document came in, or by title. The title
sorts by `title_key` (`sort_key`: case and accents aside), which this revision fills for every
document; the two sorted lists page by an index each.
"""

import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sort_key(text: str) -> str:
    """As `papiq.core.domain.sorting.sort_key` today (a revision keeps its own copy)."""
    decomposed = unicodedata.normalize("NFKD", text)
    letters = "".join(char for char in decomposed if not unicodedata.combining(char))
    return letters.casefold().strip()


def upgrade() -> None:
    # Not a batch operation: on SQLite, it would copy the table, which others refer to.
    op.add_column("documents", sa.Column("title_key", sa.Text(), nullable=False, server_default=""))
    documents = sa.table(
        "documents", sa.column("id", sa.Uuid()), sa.column("title"), sa.column("title_key")
    )
    connection = op.get_bind()
    for id_, title in connection.execute(sa.select(documents.c.id, documents.c.title)).all():
        connection.execute(
            documents.update().where(documents.c.id == id_).values(title_key=_sort_key(title))
        )
    op.create_index("ix_documents_document_date_id", "documents", ["document_date", "id"])
    op.create_index("ix_documents_title_key_id", "documents", ["title_key", "id"])


def downgrade() -> None:
    op.drop_index("ix_documents_title_key_id", table_name="documents")
    op.drop_index("ix_documents_document_date_id", table_name="documents")
    op.drop_column("documents", "title_key")
