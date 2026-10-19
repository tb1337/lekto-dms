"""Pipeline steps are called nodes: columns, job kinds, payload keys and event types

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-12 18:00:00.000000

The names of the nodes themselves (`ocr`, `parse`, ...) stay; what changes is the word for
them: the columns `documents.processing_step` and `processing_log.step`, the job kind
`pipeline.step` with the payload key `step`, the event type `document.step_completed` with
its payload key, and where webhooks store that event type.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from lekto.adapters.outbound.sql import types

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_KIND = ("pipeline.step", "pipeline.node")
_EVENT_TYPE = ("document.step_completed", "document.node_completed")
_KEY = ("step", "node")


def upgrade() -> None:
    op.alter_column("documents", "processing_step", new_column_name="processing_node")
    op.alter_column("processing_log", "step", new_column_name="node")
    _rename_stored(up=True)


def downgrade() -> None:
    _rename_stored(up=False)
    op.alter_column("processing_log", "node", new_column_name="step")
    op.alter_column("documents", "processing_node", new_column_name="processing_step")


def _rename_stored(*, up: bool) -> None:
    def pick(pair: tuple[str, str]) -> tuple[str, str]:
        return pair if up else (pair[1], pair[0])

    kind, event_type, key = pick(_JOB_KIND), pick(_EVENT_TYPE), pick(_KEY)
    connection = op.get_bind()

    jobs = sa.table(
        "jobs",
        sa.column("id"),
        sa.column("kind", sa.Text()),
        sa.column("payload", types.json_type()),
    )
    for row in connection.execute(sa.select(jobs).where(jobs.c.kind == kind[0])).mappings():
        connection.execute(
            jobs.update()
            .where(jobs.c.id == row["id"])
            .values(kind=kind[1], payload=_rekey(row["payload"], key))
        )

    outbox = sa.table(
        "outbox",
        sa.column("seq"),
        sa.column("type", sa.Text()),
        sa.column("payload", types.json_type()),
    )
    rows = connection.execute(sa.select(outbox).where(outbox.c.type == event_type[0])).mappings()
    for row in rows:
        connection.execute(
            outbox.update()
            .where(outbox.c.seq == row["seq"])
            .values(type=event_type[1], payload=_rekey(row["payload"], key))
        )

    deliveries = sa.table("webhook_deliveries", sa.column("event_type", sa.Text()))
    connection.execute(
        deliveries.update()
        .where(deliveries.c.event_type == event_type[0])
        .values(event_type=event_type[1])
    )

    webhooks = sa.table("webhooks", sa.column("id"), sa.column("event_types", types.json_type()))
    for row in connection.execute(sa.select(webhooks)).mappings():
        event_types = row["event_types"]
        if isinstance(event_types, list) and event_type[0] in event_types:
            renamed = [event_type[1] if item == event_type[0] else item for item in event_types]
            connection.execute(
                webhooks.update().where(webhooks.c.id == row["id"]).values(event_types=renamed)
            )


def _rekey(payload: Any, key: tuple[str, str]) -> Any:
    if isinstance(payload, dict) and key[0] in payload:
        return {key[1] if name == key[0] else name: value for name, value in payload.items()}
    return payload
