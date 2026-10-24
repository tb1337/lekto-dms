"""Where a learned identifier was learned; a user's numbers go with them

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-24 12:00:00.000000

Who sees a contact's identifier follows where it comes from (issue #82): a learned one keeps
the spaces of the documents it was learned from (`contact_identifiers.learned_in`, a JSON list
of space ids), and only their members see it. Rows learned before have none: until the next
training only admins see them. A customer or personnel number that names a user is theirs, and
it goes with them: `contact_identifiers.user_id` is `ON DELETE CASCADE` instead of `SET NULL`
(a deleted user's number would otherwise be everyone's to see).

Postgres changes the key and adds the column in place; SQLite builds `contact_identifiers` anew
for the key (no table refers to it), keeping its rows. The downgrade goes back to `SET NULL`
and drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("contact_id", "kind", "value", "source", "topic_id", "user_id")
_USER_KEY = "fk_contact_identifiers_user_id_users"


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _rebuild(learned_in=True, on_user_delete="CASCADE")
        return
    op.add_column("contact_identifiers", sa.Column("learned_in", types.json_type(), nullable=True))
    _replace_user_key("CASCADE")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _rebuild(learned_in=False, on_user_delete="SET NULL")
        return
    _replace_user_key("SET NULL")
    op.drop_column("contact_identifiers", "learned_in")


def _replace_user_key(on_delete: str) -> None:
    op.drop_constraint(op.f(_USER_KEY), "contact_identifiers", type_="foreignkey")
    op.create_foreign_key(
        op.f(_USER_KEY), "contact_identifiers", "users", ["user_id"], ["id"], ondelete=on_delete
    )


def _rebuild(*, learned_in: bool, on_user_delete: str) -> None:
    """Build `contact_identifiers` anew, with or without `learned_in`, keeping its rows."""
    connection = op.get_bind()
    count = int(
        connection.exec_driver_sql("SELECT count(*) FROM contact_identifiers").scalar() or 0
    )
    op.execute("CREATE TEMP TABLE _contact_identifiers_0040 AS SELECT * FROM contact_identifiers")
    op.drop_table("contact_identifiers")
    columns: list[sa.schema.SchemaItem] = [
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
    ]
    if learned_in:
        columns.append(sa.Column("learned_in", types.json_type(), nullable=True))
    op.create_table(
        "contact_identifiers",
        *columns,
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_contact_identifiers_contact_id_contacts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"], ["tags.id"], name=op.f("fk_contact_identifiers_topic_id_tags")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f(_USER_KEY), ondelete=on_user_delete
        ),
        sa.PrimaryKeyConstraint("kind", "value", name=op.f("pk_contact_identifiers")),
    )
    op.create_index(
        op.f("ix_contact_identifiers_contact_id"), "contact_identifiers", ["contact_id"]
    )
    names = ", ".join(_COLUMNS)
    op.execute(
        f"INSERT INTO contact_identifiers ({names}) SELECT {names} FROM _contact_identifiers_0040"
    )
    op.execute("DROP TABLE _contact_identifiers_0040")
    copied = connection.exec_driver_sql("SELECT count(*) FROM contact_identifiers").scalar()
    if copied != count:
        raise RuntimeError(f"revision 0040 copied {copied} of {count} contact identifiers")
