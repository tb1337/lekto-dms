"""Classification and field extraction for documents taken over from another system.

A document received with metadata (channel `migration`, see `PipelineService.receive`) keeps
what the source system knew: these nodes apply it instead of asking the language model. Every
other document goes to the node they wrap. The applied values are not model output, so rules
trust them (they have no field checks in the log, see `rules.running.provenance`). What the
source system lacks of contact, document type and date, and the document has neither, makes
the judge uncertain, as Lekto's own judge is without them: a person decides it in the inbox.
"""

from lekto.core.domain.classification import (
    CHECKS,
    CONTACT,
    DOCUMENT_DATE,
    DOCUMENT_TYPE,
    FieldCheck,
    checks_to_json,
    field_id_of,
)
from lekto.core.domain.documents import Channel, Document, DocumentChanges
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.imports import IMPORTED, ImportedMetadata, ImportedReview
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.pipeline import Node, NodeResult, Outcome
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from lekto.core.services._access import field_definitions
from lekto.core.services.classification.signals import abstained
from lekto.core.services.pipeline import DeferredResult, MetadataResult, NodeExecutor

REASON = "taken over from the source system"
MISSING: dict[str, str] = {
    CONTACT: "contact",
    DOCUMENT_TYPE: "document type",
    DOCUMENT_DATE: "document date",
}
"""The judge's fields a document needs; without them from the source system, a person decides."""


class _ImportedStep:
    def __init__(self, uow: UnitOfWorkFactory, inner: NodeExecutor) -> None:
        self._uow = uow
        self._inner = inner

    async def run(self, document: Document) -> NodeResult | DeferredResult:
        if document.channel is not Channel.MIGRATION:
            return await self._inner.run(document)
        async with self._uow() as uow:
            entries = await uow.processing_log.list_for(document.id)
            definitions = await field_definitions(uow)
        stored = next(
            (
                entry.result.output[IMPORTED]
                for entry in entries
                if entry.node is Node.RECEIVE and IMPORTED in entry.result.output
            ),
            None,
        )
        if stored is None:
            return await self._inner.run(document)
        try:
            return self._apply(ImportedMetadata.from_json(stored, definitions), document)
        except ValidationError as error:
            return NodeResult(
                outcome=Outcome.UNCERTAIN,
                reason=f"the metadata of the source system no longer fits: {error}",
            )

    def _apply(self, imported: ImportedMetadata, document: Document) -> NodeResult | DeferredResult:
        raise NotImplementedError


class ImportedSignal(_ImportedStep):
    """Nothing to propose: the source system's metadata is applied as it is. The signal
    abstains, as one without its service does."""

    def _apply(self, imported: ImportedMetadata, document: Document) -> NodeResult:
        return abstained(REASON, model_version=IMPORTED)


class ImportedJudgeNode(_ImportedStep):
    """Title, contact, document type, tags and document date from the source system. Reviews
    of the document or of one of these fields make it uncertain, and so does a contact, type
    or date that neither the source system nor the document has (`MISSING`); it then confirms
    nothing."""

    def _apply(self, imported: ImportedMetadata, document: Document) -> MetadataResult:
        reviews = [item for item in imported.review if field_id_of(item.field or "") is None]
        reviewed = {item.field for item in reviews}
        reviews += [
            ImportedReview(reason=f"no {MISSING[field]} in the source system", field=field)
            for field in _lacking(imported, document)
            if field not in reviewed
        ]
        output: JsonObject = {IMPORTED: imported.to_json()}
        if reviews:
            output[CHECKS] = checks_to_json(_open(reviews))
        result = _result(reviews, output)
        return MetadataResult(
            result, imported.classification(), imported.tag_ids, confirms=not reviews
        )


class ImportedFieldsNode(_ImportedStep):
    """Field values from the source system; a review of one of them makes it uncertain."""

    def _apply(self, imported: ImportedMetadata, document: Document) -> MetadataResult:
        reviews = [item for item in imported.review if field_id_of(item.field or "") is not None]
        output: JsonObject = {"fields": len(imported.fields)}
        if reviews:
            output[CHECKS] = checks_to_json(_open(reviews))
        result = _result(reviews, output)
        return MetadataResult(result, DocumentChanges(fields=dict(imported.fields)))


def _lacking(imported: ImportedMetadata, document: Document) -> list[str]:
    """The fields of `MISSING` neither the source system nor the document has: what the source
    system lacks, a person may have set since (reprocessing applies the metadata again)."""
    held = {
        CONTACT: (imported.contact_id, document.contact_id),
        DOCUMENT_TYPE: (imported.document_type_id, document.document_type_id),
        DOCUMENT_DATE: (imported.document_date, document.document_date),
    }
    return [field for field, values in held.items() if values == (None, None)]


def _result(reviews: list[ImportedReview], output: JsonObject) -> NodeResult:
    if not reviews:
        return NodeResult(outcome=Outcome.OK, reason=REASON, model_version=IMPORTED, output=output)
    reason = "; ".join(dict.fromkeys(item.reason for item in reviews))
    return NodeResult(
        outcome=Outcome.UNCERTAIN, reason=reason, model_version=IMPORTED, output=output
    )


def _open(reviews: list[ImportedReview]) -> list[FieldCheck]:
    """The named fields as open checks: kept with a value, decided by a person without one."""
    return [
        FieldCheck(field=item.field, outcome=Outcome.UNCERTAIN, confidence=0.0, reason=item.reason)
        for item in reviews
        if item.field is not None
    ]
