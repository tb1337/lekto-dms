"""Identifiers suggested as a user's that a person declined

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-28 14:00:00.000000

The open identifiers suggest an IBAN that a document's recipient holds for that person's
profile (`.idea/umsetzungsplan.md`, "Inhaber von IBANs und Gläubiger-IDs", PR 4b). One a person
declined is kept beside the profile, so it is not suggested again (`Profile.declined`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_declined_identifiers",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_declined_identifiers_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "kind", "value", name=op.f("pk_user_declined_identifiers")
        ),
    )


def downgrade() -> None:
    op.drop_table("user_declined_identifiers")
