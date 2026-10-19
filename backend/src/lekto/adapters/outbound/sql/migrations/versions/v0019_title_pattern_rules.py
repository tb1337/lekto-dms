"""Title patterns of document types in Liquid, each as a rule of its type

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-14 23:00:00.000000

A document type's title pattern had placeholders of its own (`{contact}`, `{field:Name}`) and
was rendered by the fields node; it is a Liquid template now, carried out by a global rule the
type keeps (`title_pattern_rules`): "document type is X → set title". A pattern gave no title
when a value was missing; so does its template (`{{ contact }}`). `{field:Name}` becomes
`{{ field.<key> }}` with the field's key (`template_key`). Two things read differently: an
amount is written in the locale (`3.650,00 EUR`, it was `3650.00 EUR`), and a yes/no field is
written (`true`), where it counted as missing.

Two fields whose names give the same key stop the upgrade: one of them is to be renamed first.
The downgrade removes the rules and writes the forms written here as the old placeholders.
"""

import os
import re
import time
import unicodedata
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_TOKEN = re.compile(r"YYYY|YY|MM|DD")
_STRFTIME = {"YYYY": "%Y", "YY": "%y", "MM": "%m", "DD": "%d"}
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})
_NOT_KEY = re.compile(r"[^a-z0-9]+")

_types = sa.table(
    "document_types",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.Text()),
    sa.column("title_pattern", sa.Text()),
)
_fields = sa.table("field_definitions", sa.column("name", sa.Text()))
_rules = sa.table(
    "rules",
    sa.column("id", sa.Uuid()),
    sa.column("scope", sa.Text()),
    sa.column("owner_id", sa.Uuid()),
    sa.column("current_version", sa.Integer()),
    sa.column("enabled", sa.Boolean()),
    sa.column("created_at", types.UtcDateTime()),
    sa.column("updated_at", types.UtcDateTime()),
    sa.column("version", sa.Integer()),
)
_versions = sa.table(
    "rule_versions",
    sa.column("rule_id", sa.Uuid()),
    sa.column("number", sa.Integer()),
    sa.column("name", sa.Text()),
    sa.column("priority", sa.Integer()),
    sa.column("triggers", types.json_type()),
    sa.column("conditions", types.json_type()),
    sa.column("actions", types.json_type()),
    sa.column("created_at", types.UtcDateTime()),
    sa.column("created_by", sa.Uuid()),
)
_applications = sa.table("rule_applications", sa.column("rule_id", sa.Uuid()))


def upgrade() -> None:
    op.create_table(
        "title_pattern_rules",
        sa.Column("document_type_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_type_id"],
            ["document_types.id"],
            name=op.f("fk_title_pattern_rules_document_type_id_document_types"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["rules.id"],
            name=op.f("fk_title_pattern_rules_rule_id_rules"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_type_id", name=op.f("pk_title_pattern_rules")),
        sa.UniqueConstraint("rule_id", name=op.f("uq_title_pattern_rules_rule_id")),
    )
    connection = op.get_bind()
    keys = _field_keys(connection)
    links = sa.table(
        "title_pattern_rules",
        sa.column("document_type_id", sa.Uuid()),
        sa.column("rule_id", sa.Uuid()),
    )
    now = datetime.now(UTC)
    for row in connection.execute(sa.select(_types).where(_types.c.title_pattern.is_not(None))):
        template = _liquid(row.title_pattern, keys)
        connection.execute(
            _types.update().where(_types.c.id == row.id).values(title_pattern=template)
        )
        rule = _new_id()
        connection.execute(
            sa.insert(_rules).values(
                id=rule,
                scope="global",
                owner_id=None,
                current_version=1,
                enabled=True,
                created_at=now,
                updated_at=now,
                version=1,
            )
        )
        connection.execute(
            sa.insert(_versions).values(
                rule_id=rule,
                number=1,
                name=row.name,
                priority=0,
                triggers=["change", "ingest"],
                conditions={"all": [{"field": "document_type", "op": "is", "value": str(row.id)}]},
                actions=[{"type": "set_title", "template": template}],
                created_at=now,
                created_by=None,
            )
        )
        connection.execute(sa.insert(links).values(document_type_id=row.id, rule_id=rule))


def downgrade() -> None:
    connection = op.get_bind()
    links = sa.table("title_pattern_rules", sa.column("rule_id", sa.Uuid()))
    rules = [row.rule_id for row in connection.execute(sa.select(links))]
    if rules:
        connection.execute(sa.delete(_applications).where(_applications.c.rule_id.in_(rules)))
        connection.execute(sa.delete(_versions).where(_versions.c.rule_id.in_(rules)))
        connection.execute(sa.delete(links))
        connection.execute(sa.delete(_rules).where(_rules.c.id.in_(rules)))
    op.drop_table("title_pattern_rules")
    names = {key: name for name, key in _field_keys(connection).items()}
    for row in connection.execute(sa.select(_types).where(_types.c.title_pattern.is_not(None))):
        connection.execute(
            _types.update()
            .where(_types.c.id == row.id)
            .values(title_pattern=_placeholders(row.title_pattern, names))
        )


def _field_keys(connection: sa.Connection) -> dict[str, str]:
    """The key of every field by its name; two names with one key stop the upgrade."""
    keys: dict[str, str] = {}
    by_key: dict[str, str] = {}
    for (name,) in connection.execute(sa.select(_fields.c.name)):
        key = _key(name)
        if key in by_key:
            raise RuntimeError(
                f"the fields '{by_key[key]}' and '{name}' would both be field.{key} in "
                "templates: rename one before upgrading"
            )
        keys[name], by_key[key] = key, name
    return keys


def _key(name: str) -> str:
    """As `domain.fields.template_key` has it at this revision."""
    folded = unicodedata.normalize("NFKC", name).casefold().translate(_UMLAUTS)
    plain = "".join(
        char for char in unicodedata.normalize("NFKD", folded) if not unicodedata.combining(char)
    )
    key = _NOT_KEY.sub("_", plain).strip("_") or "field"
    return f"f_{key}" if key[0].isdigit() else key


def _liquid(pattern: str, keys: dict[str, str]) -> str:
    def replace(found: re.Match[str]) -> str:
        name, _, argument = found.group(1).partition(":")
        if name == "field":
            return f"{{{{ field.{keys.get(argument) or _key(argument)} }}}}"
        if name == "document_date" and argument:
            strftime = _TOKEN.sub(
                lambda token: _STRFTIME[token.group()], argument.replace("%", "%%")
            )
            quote = '"' if "'" in strftime else "'"
            return f"{{{{ document_date | date: {quote}{strftime}{quote} }}}}"
        return f"{{{{ {name} }}}}"

    return _PLACEHOLDER.sub(replace, pattern)


def _placeholders(template: str, names: dict[str, str]) -> str:
    tokens = {strftime: token for token, strftime in _STRFTIME.items()}

    def date(found: re.Match[str]) -> str:
        format = re.sub(r"%[Yymd]", lambda part: tokens[part.group()], found.group(2))
        return f"{{document_date:{format.replace('%%', '%')}}}"

    template = re.sub(r"\{\{ document_date \| date: (['\"])(.*?)\1 \}\}", date, template)
    template = re.sub(
        r"\{\{ field\.([a-z0-9_]+) \}\}",
        lambda found: f"{{field:{names.get(found.group(1), found.group(1))}}}",
        template,
    )
    return re.sub(r"\{\{ (contact|document_type|document_date|filename) \}\}", r"{\1}", template)


def _new_id() -> uuid.UUID:
    """A UUIDv7, as `lekto.core.domain.ids.new_id` makes it today (a revision keeps its own
    copy)."""
    milliseconds = time.time_ns() // 1_000_000 & ((1 << 48) - 1)
    random = int.from_bytes(os.urandom(10))
    value = milliseconds << 80 | random
    value = value & ~(0xF << 76) | 0x7 << 76  # version 7
    value = value & ~(0x3 << 62) | 0x2 << 62  # variant RFC 9562
    return uuid.UUID(int=value)
