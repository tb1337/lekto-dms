"""Documents with their field values, and the processing log."""

from collections.abc import Collection, Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Row, and_, delete, insert, or_, select

from papiq.adapters.outbound.sql import tables as t
from papiq.adapters.outbound.sql.drawers import visible_to
from papiq.adapters.outbound.sql.repositories import MICROSECOND, SqlRepository, Values
from papiq.adapters.outbound.sql.transaction import Transaction
from papiq.core.domain.documents import Channel, Document, Sha256
from papiq.core.domain.fields import FieldValue, Money, Url
from papiq.core.domain.ids import (
    ContactId,
    DocumentId,
    DocumentTypeId,
    DrawerId,
    FieldId,
    TagId,
    UserId,
)
from papiq.core.domain.pipeline import (
    Lane,
    Outcome,
    Processing,
    ProcessingStatus,
    Step,
    StepResult,
    StepRun,
)
from papiq.core.ports.repository import DocumentFilter


class SqlDocumentRepository(SqlRepository[DocumentId, Document]):
    kind = "document"
    table = t.documents

    async def find_by_sha256(self, owner: UserId, sha256: Sha256) -> Document | None:
        found = await self._load(
            and_(t.documents.c.owner_id == owner, t.documents.c.sha256 == sha256.hex)
        )
        return found[0] if found else None

    async def list_visible_to(self, user: UserId) -> list[Document]:
        return await self._load(visible_to(user))

    async def field_in_use(
        self,
        field: FieldId,
        *,
        values: Collection[str] | None = None,
        outside_types: Collection[DocumentTypeId] | None = None,
    ) -> bool:
        documents, values_table = t.documents, t.document_fields
        statement = (
            select(values_table.c.document_id)
            .join(documents, documents.c.id == values_table.c.document_id)
            .where(values_table.c.field_id == field)
        )
        if values is not None:
            statement = statement.where(values_table.c.value_text.in_(list(values)))
        if outside_types is not None:
            statement = statement.where(
                or_(
                    documents.c.document_type_id.is_(None),
                    documents.c.document_type_id.not_in(list(outside_types)),
                )
            )
        found = await self._tx.read(statement.limit(1))
        return found.first() is not None

    async def query_visible(
        self,
        user: UserId,
        filter: DocumentFilter,
        *,
        before: DocumentId | None = None,
        limit: int,
    ) -> list[Document]:
        return await self._query([visible_to(user)], filter, before=before, limit=limit)

    async def query(
        self, filter: DocumentFilter, *, before: DocumentId | None = None, limit: int
    ) -> list[Document]:
        return await self._query([], filter, before=before, limit=limit)

    async def _query(
        self,
        criteria: list[ColumnElement[bool]],
        filter: DocumentFilter,
        *,
        before: DocumentId | None,
        limit: int,
    ) -> list[Document]:
        documents = t.documents
        if before is not None:
            criteria.append(documents.c.id < before)
        if filter.contact is not None:
            criteria.append(documents.c.contact_id == filter.contact)
        if filter.document_type is not None:
            criteria.append(documents.c.document_type_id == filter.document_type)
        if filter.drawer is not None:
            criteria.append(documents.c.drawer_id == filter.drawer)
        for tag in sorted(filter.tags):
            tags = t.document_tags
            criteria.append(
                documents.c.id.in_(select(tags.c.document_id).where(tags.c.tag_id == tag))
            )
        if filter.lanes is not None:
            values = [lane.value for lane in filter.lanes if lane is not None]
            lane_criteria = [documents.c.lane.in_(values)]
            if None in filter.lanes:
                lane_criteria.append(documents.c.lane.is_(None))
            criteria.append(or_(*lane_criteria))
        rows = (
            await self._tx.read(
                select(documents).where(*criteria).order_by(documents.c.id.desc()).limit(limit)
            )
        ).all()
        return await self._entities(rows)

    async def exists(
        self,
        *,
        owner: UserId | None = None,
        drawer: DrawerId | None = None,
        contact: ContactId | None = None,
        document_type: DocumentTypeId | None = None,
        tag: TagId | None = None,
        field: FieldId | None = None,
        sha256: Sha256 | None = None,
    ) -> bool:
        documents = t.documents
        criteria: list[ColumnElement[bool]] = []
        if owner is not None:
            criteria.append(documents.c.owner_id == owner)
        if drawer is not None:
            criteria.append(documents.c.drawer_id == drawer)
        if contact is not None:
            criteria.append(documents.c.contact_id == contact)
        if document_type is not None:
            criteria.append(documents.c.document_type_id == document_type)
        if tag is not None:
            tags = t.document_tags
            criteria.append(
                documents.c.id.in_(select(tags.c.document_id).where(tags.c.tag_id == tag))
            )
        if field is not None:
            values = t.document_fields
            criteria.append(
                documents.c.id.in_(select(values.c.document_id).where(values.c.field_id == field))
            )
        if sha256 is not None:
            criteria.append(documents.c.sha256 == sha256.hex)
        if not criteria:
            raise ValueError("exists needs at least one criterion")
        found = await self._tx.read(select(documents.c.id).where(*criteria).limit(1))
        return found.first() is not None

    async def _entities(self, rows: Sequence[Row[Any]]) -> list[Document]:
        ids = [row.id for row in rows]
        tags = await self._children(t.document_tags, "document_id", ids)
        fields = await self._children(t.document_fields, "document_id", ids)
        return [
            Document(
                id=DocumentId(row.id),
                owner_id=UserId(row.owner_id),
                drawer_id=DrawerId(row.drawer_id),
                sha256=Sha256(row.sha256),
                title=row.title,
                original_filename=row.original_filename,
                media_type=row.media_type,
                contact_id=None if row.contact_id is None else ContactId(row.contact_id),
                document_type_id=(
                    None if row.document_type_id is None else DocumentTypeId(row.document_type_id)
                ),
                tag_ids={TagId(tag.tag_id) for tag in tags[row.id]},
                fields={FieldId(value.field_id): _field_value(value) for value in fields[row.id]},
                document_date=row.document_date,
                channel=Channel(row.channel),
                lane=None if row.lane is None else Lane(row.lane),
                processing=Processing(
                    status=ProcessingStatus(row.processing_status),
                    current_step=None if row.processing_step is None else Step(row.processing_step),
                    run=row.processing_run,
                    outcomes={
                        Step(step): Outcome(outcome)
                        for step, outcome in row.processing_outcomes.items()
                    },
                ),
                created_at=row.created_at,
                updated_at=row.updated_at,
                version=row.version,
            )
            for row in rows
        ]

    def _values(self, entity: Document) -> Values:
        processing = entity.processing
        return {
            "id": entity.id,
            "owner_id": entity.owner_id,
            "drawer_id": entity.drawer_id,
            "sha256": entity.sha256.hex,
            "title": entity.title,
            "original_filename": entity.original_filename,
            "media_type": entity.media_type,
            "contact_id": entity.contact_id,
            "document_type_id": entity.document_type_id,
            "document_date": entity.document_date,
            "channel": entity.channel.value,
            "lane": None if entity.lane is None else entity.lane.value,
            "processing_status": processing.status.value,
            "processing_step": (
                None if processing.current_step is None else processing.current_step.value
            ),
            "processing_run": processing.run,
            "processing_outcomes": {
                step.value: outcome.value for step, outcome in processing.outcomes.items()
            },
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
            "version": entity.version,
        }

    async def _write_children(self, entity: Document) -> None:
        await self._insert_many(
            t.document_tags,
            [{"document_id": entity.id, "tag_id": tag_id} for tag_id in entity.tag_ids],
        )
        await self._insert_many(
            t.document_fields,
            [
                {"document_id": entity.id, "field_id": field_id, **_value_columns(value)}
                for field_id, value in entity.fields.items()
            ],
        )

    async def _delete_children(self, ids: list[DocumentId]) -> None:
        for table in (t.document_tags, t.document_fields):
            await self._tx.write(delete(table).where(table.c.document_id.in_(ids)))


_EMPTY_VALUE: Values = {
    "value_text": None,
    "value_decimal": None,
    "value_currency": None,
    "value_date": None,
    "value_boolean": None,
}


def _value_columns(value: FieldValue) -> Values:
    """The columns of `document_fields` that hold a field value."""
    match value:
        case bool():
            columns: Values = {"kind": "boolean", "value_boolean": value}
        case Money(amount=amount, currency=currency):
            columns = {"kind": "money", "value_decimal": amount, "value_currency": currency}
        case Decimal():
            columns = {"kind": "decimal", "value_decimal": value}
        case Url(value=url):
            columns = {"kind": "url", "value_text": url}
        case str():
            columns = {"kind": "text", "value_text": value}
        case _:  # date; datetime is no field value
            columns = {"kind": "date", "value_date": value}
    return {**_EMPTY_VALUE, **columns}


def _field_value(row: Row[Any]) -> FieldValue:
    match row.kind:
        case "boolean":
            return bool(row.value_boolean)
        case "money":
            return Money(row.value_decimal, row.value_currency)
        case "decimal":
            return row.value_decimal  # type: ignore[no-any-return]
        case "url":
            return Url(row.value_text)
        case "text":
            return row.value_text  # type: ignore[no-any-return]
        case "date":
            return row.value_date  # type: ignore[no-any-return]
    raise ValueError(f"unknown field value kind {row.kind!r}")


class SqlProcessingLog:
    def __init__(self, transaction: Transaction) -> None:
        self._tx = transaction

    async def append(self, run: StepRun) -> None:
        result = run.result
        await self._tx.write(
            insert(t.processing_log).values(
                document_id=run.document_id,
                step=run.step.value,
                run=run.run,
                outcome=result.outcome.value,
                reason=result.reason,
                confidence=result.confidence,
                model_version=result.model_version,
                input=result.input,
                output=result.output,
                pipeline_version=run.pipeline_version,
                started_at=run.started_at,
                duration_us=run.duration // MICROSECOND,
            )
        )

    async def list_for(self, document: DocumentId) -> list[StepRun]:
        log = t.processing_log
        rows = await self._tx.read(
            select(log).where(log.c.document_id == document).order_by(log.c.seq)
        )
        return [_step_run(row) for row in rows]


def _step_run(row: Row[Any]) -> StepRun:
    return StepRun(
        document_id=DocumentId(row.document_id),
        step=Step(row.step),
        run=row.run,
        result=StepResult(
            outcome=Outcome(row.outcome),
            reason=row.reason,
            confidence=row.confidence,
            model_version=row.model_version,
            input=row.input,
            output=row.output,
        ),
        pipeline_version=row.pipeline_version,
        started_at=row.started_at,
        duration=row.duration_us * MICROSECOND,
    )
