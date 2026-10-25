"""Webhooks: headers of their own, and a secret only if they sign

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-25 12:00:00.000000

A webhook may set headers of its own (`Authorization`, ...) and may go without a secret, unsigned
(Tobi, 25.10.2026, `webhooks-und-auftraege.md`): `webhooks.header_names` (a JSON list) and
`webhooks.headers` (the values, encrypted; NULL without headers), and `webhooks.secret` may be
NULL. Existing webhooks keep their secret and have no headers.

Postgres changes the table in place; SQLite builds `webhooks` anew, keeping its rows (migrations
run with foreign keys off, so the deliveries that refer to it stay). The downgrade drops the
headers; a webhook without a secret cannot get one back without the secret key, so it goes, with
its deliveries.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEPT = (
    "id",
    "owner_id",
    "name",
    "url",
    "event_types",
    "secret",
    "previous_secret",
    "previous_valid_until",
    "active",
    "disabled_reason",
    "failed_streak",
    "created_at",
    "updated_at",
    "version",
)
_webhooks = sa.table("webhooks", sa.column("id", sa.Uuid()), sa.column("secret", sa.LargeBinary()))
_deliveries = sa.table("webhook_deliveries", sa.column("webhook_id", sa.Uuid()))


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _rebuild(headers=True)
        return
    op.add_column(
        "webhooks",
        sa.Column("header_names", types.json_type(), nullable=False, server_default="[]"),
    )
    op.add_column("webhooks", sa.Column("headers", sa.LargeBinary(), nullable=True))
    op.alter_column("webhooks", "secret", existing_type=sa.LargeBinary(), nullable=True)


def downgrade() -> None:
    unsigned = sa.select(_webhooks.c.id).where(_webhooks.c.secret.is_(None))
    op.execute(sa.delete(_deliveries).where(_deliveries.c.webhook_id.in_(unsigned)))
    op.execute(sa.delete(_webhooks).where(_webhooks.c.secret.is_(None)))
    if op.get_bind().dialect.name == "sqlite":
        _rebuild(headers=False)
        return
    op.alter_column("webhooks", "secret", existing_type=sa.LargeBinary(), nullable=False)
    op.drop_column("webhooks", "headers")
    op.drop_column("webhooks", "header_names")


def _rebuild(*, headers: bool) -> None:
    """Build `webhooks` anew, with the header columns and a secret that may be NULL, or as
    before; its rows stay."""
    connection = op.get_bind()
    count = int(connection.exec_driver_sql("SELECT count(*) FROM webhooks").scalar() or 0)
    op.execute("CREATE TEMP TABLE _webhooks_0043 AS SELECT * FROM webhooks")
    op.drop_index(op.f("ix_webhooks_owner_id"), table_name="webhooks")
    op.drop_table("webhooks")
    columns: list[sa.schema.SchemaItem] = [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("event_types", types.json_type(), nullable=False),
        sa.Column("secret", sa.LargeBinary(), nullable=headers),
        sa.Column("previous_secret", sa.LargeBinary(), nullable=True),
        sa.Column("previous_valid_until", types.UtcDateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("failed_streak", sa.Integer(), nullable=False),
        sa.Column("created_at", types.UtcDateTime(), nullable=False),
        sa.Column("updated_at", types.UtcDateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    ]
    if headers:
        columns += [
            sa.Column("header_names", types.json_type(), nullable=False, server_default="[]"),
            sa.Column("headers", sa.LargeBinary(), nullable=True),
        ]
    op.create_table(
        "webhooks",
        *columns,
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_webhooks_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhooks")),
    )
    op.create_index(op.f("ix_webhooks_owner_id"), "webhooks", ["owner_id"])
    names = ", ".join(_KEPT)
    op.execute(f"INSERT INTO webhooks ({names}) SELECT {names} FROM _webhooks_0043")
    op.execute("DROP TABLE _webhooks_0043")
    copied = connection.exec_driver_sql("SELECT count(*) FROM webhooks").scalar()
    if copied != count:
        raise RuntimeError(f"revision 0043 copied {copied} of {count} webhooks")
