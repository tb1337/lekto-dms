"""Facts as values of a document

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-26 02:00:00.000000

The identifiers a document shows become its facts (issue #145, `.idea/fakten.md`):
`document_facts` keeps kind and normalised value as `document_identifiers` did, and adds the
fact's role, where it comes from, as written, where it stands first in the text and whether a
person decided it. The rows of `document_identifiers` are taken over with the role of their
kind, as found by the patterns of the text (whether a code held one is not known); as written
and where they stand come with the facts signal's next run. The downgrade keeps kind and value
of every fact but those a person rejected.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The role of each kind (`document_facts.ROLES` as 0047 knows it).
_PERSON_KINDS = ("tax_id", "social_security_number", "health_insurance_number", "email_address")


def upgrade() -> None:
    op.create_table(
        "document_facts",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("origins", sa.Text(), nullable=False),
        sa.Column("written", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False, server_default="found"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id", "kind", "value"),
    )
    op.create_index("ix_document_facts_kind_value", "document_facts", ["kind", "value"])
    identifiers = sa.table(
        "document_identifiers",
        sa.column("document_id", sa.Uuid()),
        sa.column("kind", sa.Text()),
        sa.column("value", sa.Text()),
    )
    role = sa.case(
        (identifiers.c.kind.in_(_PERSON_KINDS), sa.literal("person")), else_=sa.literal("contact")
    )
    op.execute(
        sa.insert(
            sa.table(
                "document_facts",
                sa.column("document_id", sa.Uuid()),
                sa.column("kind", sa.Text()),
                sa.column("value", sa.Text()),
                sa.column("role", sa.Text()),
                sa.column("origins", sa.Text()),
                sa.column("state", sa.Text()),
            )
        ).from_select(
            ["document_id", "kind", "value", "role", "origins", "state"],
            sa.select(
                identifiers.c.document_id,
                identifiers.c.kind,
                identifiers.c.value,
                role,
                sa.literal("pattern"),
                sa.literal("found"),
            ),
        )
    )
    op.drop_index("ix_document_identifiers_kind_value", table_name="document_identifiers")
    op.drop_table("document_identifiers")


def downgrade() -> None:
    op.create_table(
        "document_identifiers",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id", "kind", "value"),
    )
    op.create_index("ix_document_identifiers_kind_value", "document_identifiers", ["kind", "value"])
    facts = sa.table(
        "document_facts",
        sa.column("document_id", sa.Uuid()),
        sa.column("kind", sa.Text()),
        sa.column("value", sa.Text()),
        sa.column("state", sa.Text()),
    )
    op.execute(
        sa.insert(
            sa.table(
                "document_identifiers",
                sa.column("document_id", sa.Uuid()),
                sa.column("kind", sa.Text()),
                sa.column("value", sa.Text()),
            )
        ).from_select(
            ["document_id", "kind", "value"],
            sa.select(facts.c.document_id, facts.c.kind, facts.c.value).where(
                facts.c.state != "rejected"
            ),
        )
    )
    op.drop_index("ix_document_facts_kind_value", table_name="document_facts")
    op.drop_table("document_facts")
