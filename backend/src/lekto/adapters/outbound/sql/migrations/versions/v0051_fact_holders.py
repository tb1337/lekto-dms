"""The holder of an IBAN or a creditor ID among a document's facts

Revision ID: 0051
Revises: 0050
Create Date: 2026-10-28 08:00:00.000000

A bank statement shows the payees' IBANs beside its own, and training learned them at the bank
(`.idea/umsetzungsplan.md`, "Inhaber von IBANs und Gläubiger-IDs"). A fact of either kind gets
whose it is where it stands: `holder` (sender, recipient, third party, unclear), the name the
document gives the holder and who told it (`holder_source`: the rule or the language model).
Existing facts have none until their facts are read again (`read-facts`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_facts", sa.Column("holder", sa.Text(), nullable=True))
    op.add_column("document_facts", sa.Column("holder_name", sa.Text(), nullable=True))
    op.add_column("document_facts", sa.Column("holder_source", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_facts", "holder_source")
    op.drop_column("document_facts", "holder_name")
    op.drop_column("document_facts", "holder")
