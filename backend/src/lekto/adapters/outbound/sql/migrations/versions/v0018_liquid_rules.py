"""Templates of rules in Liquid

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-14 22:00:00.000000

The action "set title" had placeholders of its own (`{contact}`, `{document_date:YYYY-MM}`);
it takes a Liquid template now, as do the value of a text field and a review's reason. Every
stored version is rewritten so it does what it did: a missing value leaves its gap empty
(`{{ contact | default: '' }}`), and text values and reasons that hold `{{` or `{%` stay as
written (`{% raw %}`).

The downgrade turns the forms written here back; a template written in Liquid since stays as it
is (the code before cannot render it).
"""

import re
from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_TOKEN = re.compile(r"YYYY|YY|MM|DD")
_STRFTIME = {"YYYY": "%Y", "YY": "%y", "MM": "%m", "DD": "%d"}
_RAW = ("{% raw %}", "{% endraw %}")

_FILENAME = "{{ filename }}"
_OPTIONAL = re.compile(r"\{\{ (contact|document_type|document_date) \| default: '' \}\}")
_DATE = re.compile(
    r"\{% if document_date %\}\{\{ document_date \| date: (?P<quote>['\"])(?P<format>.*?)"
    r"(?P=quote) \}\}\{% endif %\}"
)


def upgrade() -> None:
    _rewrite(_liquid, _kept)


def downgrade() -> None:
    _rewrite(_placeholders, _unkept)


def _rewrite(title: Callable[[str], str], text: Callable[[str], str]) -> None:
    connection = op.get_bind()
    fields = sa.table("field_definitions", sa.column("id", sa.Uuid()), sa.column("data_type"))
    texts = {
        str(row.id)
        for row in connection.execute(sa.select(fields).where(fields.c.data_type == "text"))
    }
    versions = sa.table(
        "rule_versions",
        sa.column("rule_id", sa.Uuid()),
        sa.column("number", sa.Integer()),
        sa.column("actions", types.json_type()),
    )
    for row in connection.execute(sa.select(versions)).mappings().all():
        actions = [_action(action, texts, title, text) for action in row["actions"]]
        if actions != row["actions"]:
            connection.execute(
                versions.update()
                .where(versions.c.rule_id == row["rule_id"], versions.c.number == row["number"])
                .values(actions=actions)
            )


def _action(
    action: Any, texts: set[str], title: Callable[[str], str], text: Callable[[str], str]
) -> Any:
    if not isinstance(action, dict):
        return action
    match action.get("type"):
        case "set_title" if isinstance(action.get("template"), str):
            return {**action, "template": title(action["template"])}
        case "force_review" if isinstance(action.get("reason"), str):
            return {**action, "reason": text(action["reason"])}
        case "set_field" if action.get("field_id") in texts and isinstance(
            action.get("value"), str
        ):
            return {**action, "value": text(action["value"])}
    return action


def _liquid(template: str) -> str:
    """A title template with the old placeholders in Liquid, doing what it did."""

    def replace(found: re.Match[str]) -> str:
        name, _, format = found.group(1).partition(":")
        if name == "filename":
            return _FILENAME
        if name == "document_date" and format:
            strftime = _TOKEN.sub(lambda token: _STRFTIME[token.group()], format.replace("%", "%%"))
            quote = '"' if "'" in strftime else "'"
            return (
                f"{{% if document_date %}}{{{{ document_date | date: {quote}{strftime}{quote} }}}}"
                "{% endif %}"
            )
        return f"{{{{ {name} | default: '' }}}}"

    return _PLACEHOLDER.sub(replace, template)


def _placeholders(template: str) -> str:
    """The forms `_liquid` writes, as the old placeholders."""

    def date(found: re.Match[str]) -> str:
        tokens = {strftime: token for token, strftime in _STRFTIME.items()}
        format = re.sub(r"%[Yymd]", lambda part: tokens[part.group()], found.group("format"))
        return f"{{document_date:{format.replace('%%', '%')}}}"

    template = _DATE.sub(date, template)
    template = _OPTIONAL.sub(lambda found: f"{{{found.group(1)}}}", template)
    return template.replace(_FILENAME, "{filename}")


def _kept(text: str) -> str:
    """A literal text that would read as a template, kept as written."""
    return f"{_RAW[0]}{text}{_RAW[1]}" if "{{" in text or "{%" in text else text


def _unkept(text: str) -> str:
    if text.startswith(_RAW[0]) and text.endswith(_RAW[1]):
        return text[len(_RAW[0]) : -len(_RAW[1])]
    return text
