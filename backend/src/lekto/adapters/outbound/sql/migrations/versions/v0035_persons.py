"""Persons: display names and private profiles

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-22 04:00:00.000000

A user gets a display name (`users.display_name`, unique regardless of case through
`display_name_key`) and a private profile: birth date and e-mail (`user_profiles`), other names
(`user_aliases`, unique per user only: an alias is private) and their own identifiers
(`user_identifiers`). A contact's customer or
personnel number may name the user it belongs to (`contact_identifiers.user_id`). Nothing is
filled in: until a user or an admin enters it, a user is shown by their username
(Tobi, 21.10.2026).

On SQLite the users' columns have no keys and are added in place (the unique index apart);
`contact_identifiers` is built anew for its foreign key (no table refers to it). The downgrade
drops all of it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDENTIFIER_COLUMNS = ("contact_id", "kind", "value", "source", "topic_id")


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    op.add_column("users", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("display_name_key", sa.Text(), nullable=True))
    op.create_index(op.f("ix_users_display_name_key"), "users", ["display_name_key"], unique=True)
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_profiles")),
    )
    op.create_table(
        "user_aliases",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_aliases_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "name_key", name=op.f("pk_user_aliases")),
    )
    op.create_table(
        "user_identifiers",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_identifiers_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "kind", "value", name=op.f("pk_user_identifiers")),
    )
    op.create_index(op.f("ix_user_identifiers_kind_value"), "user_identifiers", ["kind", "value"])
    if sqlite:
        _rebuild_identifiers(with_user=True)
    else:
        op.add_column("contact_identifiers", sa.Column("user_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f("fk_contact_identifiers_user_id_users"),
            "contact_identifiers",
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        _rebuild_identifiers(with_user=False)
    else:
        op.drop_constraint(
            op.f("fk_contact_identifiers_user_id_users"), "contact_identifiers", type_="foreignkey"
        )
        op.drop_column("contact_identifiers", "user_id")
    op.drop_table("user_identifiers")
    op.drop_table("user_aliases")
    op.drop_table("user_profiles")
    op.drop_index(op.f("ix_users_display_name_key"), table_name="users")
    # Not a batch operation: on SQLite, it would copy the table, which others refer to.
    op.drop_column("users", "display_name_key")
    op.drop_column("users", "display_name")


def _rebuild_identifiers(*, with_user: bool) -> None:
    """Build `contact_identifiers` anew, with or without `user_id`, keeping its rows."""
    connection = op.get_bind()
    count = int(
        connection.exec_driver_sql("SELECT count(*) FROM contact_identifiers").scalar() or 0
    )
    op.execute("CREATE TEMP TABLE _contact_identifiers_0035 AS SELECT * FROM contact_identifiers")
    op.drop_table("contact_identifiers")
    columns: list[sa.schema.SchemaItem] = [
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
    ]
    keys: list[sa.schema.SchemaItem] = [
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_contact_identifiers_contact_id_contacts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"], ["tags.id"], name=op.f("fk_contact_identifiers_topic_id_tags")
        ),
        sa.PrimaryKeyConstraint("kind", "value", name=op.f("pk_contact_identifiers")),
    ]
    if with_user:
        columns.append(sa.Column("user_id", sa.Uuid(), nullable=True))
        keys.append(
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name=op.f("fk_contact_identifiers_user_id_users"),
                ondelete="SET NULL",
            )
        )
    op.create_table("contact_identifiers", *columns, *keys)
    op.create_index(
        op.f("ix_contact_identifiers_contact_id"), "contact_identifiers", ["contact_id"]
    )
    names = ", ".join(_IDENTIFIER_COLUMNS)
    op.execute(
        f"INSERT INTO contact_identifiers ({names}) SELECT {names} FROM _contact_identifiers_0035"
    )
    op.execute("DROP TABLE _contact_identifiers_0035")
    copied = connection.exec_driver_sql("SELECT count(*) FROM contact_identifiers").scalar()
    if copied != count:
        raise RuntimeError(f"revision 0035 copied {copied} of {count} contact identifiers")
