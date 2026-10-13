"""Documents know when a person last confirmed their metadata

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-13 20:00:00.000000

`documents.confirmed_at` is filled from the processing log: the latest confirmation in the
inbox (`person`), change of contact, type, tags, date or fields by a person (`rules:change`)
or metadata taken over from the source system (`imported` at `classify`). A run of the model
at `classify` after it derived the metadata anew: such a document is not confirmed. A
confirmed document's version goes up, so the search index's reconciliation takes it up again
(with the new `confirmed` attribute; its vectors stay).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

from papiq.adapters.outbound.sql import types

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Log entries written by people, rules or the migration rather than the model.
_NO_MODEL = ("person", "rules", "rules:change", "rules:apply", "person:drawer", "imported")

_documents = sa.table(
    "documents",
    sa.column("id"),
    sa.column("confirmed_at", types.UtcDateTime()),
    sa.column("version", sa.Integer()),
)
_log = sa.table(
    "processing_log",
    sa.column("seq"),
    sa.column("document_id"),
    sa.column("node", sa.Text()),
    sa.column("model_version", sa.Text()),
    sa.column("input", types.json_type()),
    sa.column("started_at", types.UtcDateTime()),
)


def upgrade() -> None:
    op.add_column("documents", sa.Column("confirmed_at", types.UtcDateTime(), nullable=True))
    op.create_index(op.f("ix_documents_confirmed_at"), "documents", ["confirmed_at"])
    connection = op.get_bind()
    confirmed: dict[Any, datetime | None] = {}
    columns = [_log.c.document_id, _log.c.node, _log.c.model_version, _log.c.input]
    entries = connection.execute(
        sa.select(*columns, _log.c.started_at).order_by(_log.c.seq)
    ).mappings()
    for entry in entries:
        document, when = entry["document_id"], entry["started_at"]
        if _confirms(entry["node"], entry["model_version"], entry["input"]):
            confirmed[document] = when
        elif entry["node"] == "classify" and entry["model_version"] not in _NO_MODEL:
            confirmed[document] = None
    for document, when in confirmed.items():
        if when is not None:
            connection.execute(
                sa.update(_documents)
                .where(_documents.c.id == document)
                .values(confirmed_at=when, version=_documents.c.version + 1)
            )


def _confirms(node: str, model_version: str | None, input: Any) -> bool:
    if model_version == "person":
        return True
    if model_version == "imported":
        return node == "classify"
    if model_version != "rules:change" or not isinstance(input, dict):
        return False
    changed = [name for name in input.get("changed") or () if name != "title"]
    return bool(changed or input.get("tags_added") or input.get("tags_removed"))


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_confirmed_at"), table_name="documents")
    # Not a batch operation: on SQLite, it would copy the table, which others refer to.
    op.drop_column("documents", "confirmed_at")
