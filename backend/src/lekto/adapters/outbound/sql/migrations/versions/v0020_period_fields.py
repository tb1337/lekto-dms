"""Fields of the type period

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-15 12:00:00.000000

A period (`FieldType.PERIOD`: a day, a week, a month, any span) keeps its start in
`document_fields.value_date` and its end in the new `value_date_end`.

The downgrade makes every period field a date field and every period its start: the code
before knows neither the type nor the kind of value. The ends are lost; rules that compare a
period are disabled by the code before, which cannot read their values.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_fields", sa.Column("value_date_end", sa.Date(), nullable=True))


def downgrade() -> None:
    values = sa.table("document_fields", sa.column("kind"), sa.column("value_date_end"))
    op.execute(values.update().where(values.c.kind == "period").values(kind="date"))
    fields = sa.table("field_definitions", sa.column("data_type"))
    op.execute(fields.update().where(fields.c.data_type == "period").values(data_type="date"))
    # Not a batch operation: on SQLite, it would copy the table, which others refer to.
    op.drop_column("document_fields", "value_date_end")
