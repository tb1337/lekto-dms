"""What a node sent to a model and got back, kept beside the document (`domain.exchanges`)."""

import json
import logging

from papiq.core.domain import media_types
from papiq.core.domain.documents import Document
from papiq.core.domain.errors import NotFoundError, ValidationError
from papiq.core.domain.exchanges import (
    ModelCall,
    RunExchange,
    exchanges_from_json,
    exchanges_to_json,
    with_run,
)
from papiq.core.domain.pipeline import Node
from papiq.core.ports import ObjectStore
from papiq.core.services.objects import exchanges_key

log = logging.getLogger(__name__)


async def keep_calls(
    store: ObjectStore, document: Document, node: Node, calls: list[ModelCall]
) -> None:
    """Add the calls of the document's current run to the node's file; a run that is there
    already (the node ran again within it) is replaced. Keeping them is for people who look
    into a document: it never fails the node, nor hides why the node failed."""
    try:
        await _write(store, document, node, calls)
    except Exception:
        log.warning(
            "the model exchanges were not kept",
            exc_info=True,
            extra={"document_id": str(document.id), "node": node.value},
        )


async def _write(
    store: ObjectStore, document: Document, node: Node, calls: list[ModelCall]
) -> None:
    key = exchanges_key(document.id, node)
    runs: list[RunExchange] = []
    try:
        runs = exchanges_from_json(json.loads(await store.get(key)))
    except NotFoundError:
        pass
    except (ValueError, ValidationError):
        log.warning(
            "replacing an unreadable file of model exchanges",
            extra={"document_id": str(document.id), "node": node.value},
        )
    runs = with_run(runs, RunExchange(run=document.processing.run, calls=tuple(calls)))
    data = json.dumps(exchanges_to_json(runs), ensure_ascii=False).encode("utf-8")
    await store.put(key, data, content_type=media_types.JSON)
