"""Classification and field extraction for documents taken over from another system.

A document received with metadata (channel `migration`, see `PipelineService.receive`) keeps
what the source system knew: these nodes apply it instead of asking the language model. Every
other document goes to the node they wrap. The applied values are not model output, so rules
trust them (they have no field checks in the log, see `rules.running.provenance`).
"""

from lekto.core.domain.documents import Channel, Document, DocumentChanges
from lekto.core.domain.errors import ValidationError
from lekto.core.domain.imports import IMPORTED, ImportedMetadata
from lekto.core.domain.pipeline import Node, NodeResult, Outcome
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from lekto.core.services._access import field_definitions
from lekto.core.services.classification.signals import abstained
from lekto.core.services.pipeline import DeferredResult, MetadataResult, NodeExecutor

REASON = "taken over from the source system"


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
            return self._apply(ImportedMetadata.from_json(stored, definitions))
        except ValidationError as error:
            return NodeResult(
                outcome=Outcome.UNCERTAIN,
                reason=f"the metadata of the source system no longer fits: {error}",
            )

    def _apply(self, imported: ImportedMetadata) -> NodeResult | DeferredResult:
        raise NotImplementedError


class ImportedSignal(_ImportedStep):
    """Nothing to propose: the source system's metadata is applied as it is. The signal
    abstains, as one without its service does."""

    def _apply(self, imported: ImportedMetadata) -> NodeResult:
        return abstained(REASON, model_version=IMPORTED)


class ImportedJudgeNode(_ImportedStep):
    """Title, contact, document type, tags and document date from the source system."""

    def _apply(self, imported: ImportedMetadata) -> MetadataResult:
        result = NodeResult(
            outcome=Outcome.OK,
            reason=REASON,
            model_version=IMPORTED,
            output={IMPORTED: imported.to_json()},
        )
        return MetadataResult(result, imported.classification(), imported.tag_ids, confirms=True)


class ImportedFieldsNode(_ImportedStep):
    """Field values from the source system."""

    def _apply(self, imported: ImportedMetadata) -> MetadataResult:
        result = NodeResult(
            outcome=Outcome.OK,
            reason=REASON,
            model_version=IMPORTED,
            output={"fields": len(imported.fields)},
        )
        return MetadataResult(result, DocumentChanges(fields=dict(imported.fields)))
