"""What a node sent to a model and got back, kept beside the document (`domain.exchanges`)."""

import json
import logging

from lekto.core.domain import media_types
from lekto.core.domain.documents import Document
from lekto.core.domain.errors import NotFoundError, ValidationError
from lekto.core.domain.exchanges import (
    ModelCall,
    RunExchange,
    exchanges_from_json,
    exchanges_to_json,
    with_run,
)
from lekto.core.domain.pipeline import Node
from lekto.core.ports.object_store import ObjectStore
from lekto.core.services.objects import exchanges_key

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


async def keep_request(store: ObjectStore, document: Document, node: Node, request: str) -> None:
    """What the node sends a webhook in the document's current run (a model call's context),
    before its answer is there; as `keep_calls`."""
    call = ModelCall(system="", user=request, answer="", model="", usage={})
    await keep_calls(store, document, node, [call])


async def keep_answer(
    store: ObjectStore, document: Document, node: Node, answer: str, model: str
) -> None:
    """The answer of a webhook in the document's current run, beside what was sent
    (`keep_request`); as `keep_calls`."""
    try:
        runs = await _runs(store, document, node)
        sent = next((run for run in runs if run.run == document.processing.run), None)
        request = sent.calls[-1].user if sent is not None and sent.calls else ""
        call = ModelCall(system="", user=request, answer=answer, model=model, usage={})
        await _write(store, document, node, [call], runs)
    except Exception:
        log.warning(
            "the answer of a webhook was not kept",
            exc_info=True,
            extra={"document_id": str(document.id), "node": node.value},
        )


async def _runs(store: ObjectStore, document: Document, node: Node) -> list[RunExchange]:
    try:
        return exchanges_from_json(json.loads(await store.get(exchanges_key(document.id, node))))
    except NotFoundError:
        return []
    except (ValueError, ValidationError):
        log.warning(
            "replacing an unreadable file of model exchanges",
            extra={"document_id": str(document.id), "node": node.value},
        )
        return []


async def _write(
    store: ObjectStore,
    document: Document,
    node: Node,
    calls: list[ModelCall],
    runs: list[RunExchange] | None = None,
) -> None:
    key = exchanges_key(document.id, node)
    if runs is None:
        runs = await _runs(store, document, node)
    runs = with_run(runs, RunExchange(run=document.processing.run, calls=tuple(calls)))
    data = json.dumps(exchanges_to_json(runs), ensure_ascii=False).encode("utf-8")
    await store.put(key, data, content_type=media_types.JSON)
