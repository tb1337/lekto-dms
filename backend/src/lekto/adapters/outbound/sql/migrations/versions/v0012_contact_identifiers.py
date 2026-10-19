"""Identifiers of contacts

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-13 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_identifiers",
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_contact_identifiers_contact_id_contacts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("kind", "value", name=op.f("pk_contact_identifiers")),
    )
    op.create_index(
        op.f("ix_contact_identifiers_contact_id"),
        "contact_identifiers",
        ["contact_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_contact_identifiers_contact_id"), table_name="contact_identifiers")
    op.drop_table("contact_identifiers")
