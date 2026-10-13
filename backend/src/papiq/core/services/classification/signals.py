"""The signals: each proposes metadata from one source, for the judge (`domain.verdict`).

A signal never decides the lane. It ends OK with what it found, or, if it has nothing to say,
with `output.abstained` naming why (no model trained, no embeddings, ...). Only the language
model's signal fails, when its answers do not fit or it cannot be reached after every retry.

- `signal_facts`: contacts whose name or alias stands whole in the text, and identifiers of
  contacts (IBAN, VAT number, ...) found in it; evidence, not a proposal of its own.
- `signal_classifier`: the trained classifier's probabilities for contact, type and tags.
- `signal_neighbours`: the most similar confirmed documents the owner may read, by vector,
  with their contact, type and tags.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from papiq.core.domain.documents import Document
from papiq.core.domain.errors import ClassifierError, EmbeddingsError, NotFoundError, SearchError
from papiq.core.domain.identifiers import identifiers_in, matches
from papiq.core.domain.json_value import JsonObject, JsonValue
from papiq.core.domain.master_data import Contact
from papiq.core.domain.names import mentions, name_key
from papiq.core.domain.permissions import reach_access
from papiq.core.domain.pipeline import NodeResult, Outcome
from papiq.core.domain.search import Visibility
from papiq.core.ports import DocumentFilter, Embeddings, ObjectStore, UnitOfWorkFactory
from papiq.core.ports.search_index import SearchIndex, SimilarQuery
from papiq.core.services.classifier import ClassifierService
from papiq.core.services.indexing import split_sections
from papiq.core.services.objects import markdown_key

log = logging.getLogger(__name__)

ABSTAINED = "abstained"
"""Key of the output of a signal that had nothing to say: why."""
FACTS = "facts"
_MOST = 20  # contacts and identifiers a signal reports
_RANKED = 5  # classes of contact and type the classifier's signal keeps


def abstained(reason: str, *, model_version: str | None = None) -> NodeResult:
    return NodeResult(outcome=Outcome.OK, model_version=model_version, output={ABSTAINED: reason})


async def _text(store: ObjectStore, document: Document) -> str | None:
    try:
        return (await store.get(markdown_key(document.id))).decode("utf-8", "replace")
    except NotFoundError:
        return None


class FactsSignal:
    """Hard evidence in the text: a contact's name or alias, whole, and identifiers of
    contacts. A name in the text alone proposes nothing (a bank statement names payees, a pay
    slip the employee); it backs or contradicts what other signals propose."""

    def __init__(self, uow: UnitOfWorkFactory, store: ObjectStore) -> None:
        self._uow = uow
        self._store = store

    async def run(self, document: Document) -> NodeResult:
        text = await _text(self._store, document)
        if text is None:
            return abstained("the document has no text", model_version=FACTS)
        async with self._uow() as uow:
            contacts = await uow.contacts.list_all()
        return NodeResult(outcome=Outcome.OK, model_version=FACTS, output=facts_of(text, contacts))


def facts_of(text: str, contacts: Sequence[Contact]) -> JsonObject:
    """What `signal_facts` reports for `text`."""
    text_key = name_key(text)
    named: list[JsonValue] = []
    for contact in contacts:
        own = next((name for name in contact.names() if mentions(text_key, name_key(name))), None)
        if own is not None:
            named.append({"contact_id": str(contact.id), "name": own, "alias": own != contact.name})
    found = identifiers_in(text)
    hits: list[JsonValue] = []
    known: set[tuple[object, str]] = set()
    for contact in contacts:
        for identifier in contact.identifiers:
            matched = [item for item in found if matches(identifier, item)]
            known.update(matched)
            if matched and identifier.counts:
                hits.append(
                    {
                        "contact_id": str(contact.id),
                        "kind": identifier.kind.value,
                        "value": identifier.value,
                    }
                )
    unknown: list[JsonValue] = [
        {"kind": kind.value, "value": value}
        for kind, value in sorted(found - known, key=lambda item: (item[0].value, item[1]))
    ]
    return {
        "named": named[:_MOST],
        "identifiers": hits[:_MOST],
        "unknown_identifiers": unknown[:_MOST],
    }


class ClassifierSignal:
    """The trained classifier's probabilities, and the classes it knows (a class it does not
    know it cannot name: the judge then goes by the other signals)."""

    def __init__(self, store: ObjectStore, classifier: ClassifierService | None) -> None:
        self._store = store
        self._classifier = classifier

    async def run(self, document: Document) -> NodeResult:
        if self._classifier is None:
            return abstained("no classifier is configured")
        text = await _text(self._store, document)
        if text is None:
            return abstained("the document has no text")
        try:
            predicted = await self._classifier.predict(text)
        except ClassifierError as error:
            log.warning("the classifier could not be asked: %s", error)
            return abstained(f"the classifier cannot be used: {error}")
        if predicted is None:
            return abstained("no model is trained yet")
        model, prediction = predicted
        output: JsonObject = {
            "model": model.number,
            "contacts": [[str(id), round(p, 4)] for id, p in prediction.contacts[:_RANKED]],
            "document_types": [
                [str(id), round(p, 4)] for id, p in prediction.document_types[:_RANKED]
            ],
            "tags": {str(id): round(p, 4) for id, p in prediction.tags.items()},
            "known": {
                "contacts": _texts(prediction.known_contacts),
                "document_types": _texts(prediction.known_types),
            },
        }
        return NodeResult(
            outcome=Outcome.OK,
            model_version=f"classifier {model.number}",
            output=output,
        )


@dataclass(frozen=True)
class NeighboursPolicy:
    count: int = 5  # neighbours asked for; 0: none
    chunk_size: int = 1500  # of the first section, as the index cuts it
    document_prefix: str = ""  # put before it, as the index does
    dimensions: int | None = None  # the length of the vectors the index takes


class NeighboursSignal:
    """The most similar confirmed documents the owner may read: by the vector of the start of
    the text, against the index's vectors; their contact, type and tags (from the database,
    not the index, which lags a little)."""

    def __init__(
        self,
        uow: UnitOfWorkFactory,
        store: ObjectStore,
        index: SearchIndex | None,
        embeddings: Embeddings | None,
        policy: NeighboursPolicy | None = None,
    ) -> None:
        self._uow = uow
        self._store = store
        self._index = index
        self._embeddings = embeddings
        self._policy = policy or NeighboursPolicy()

    async def run(self, document: Document) -> NodeResult:
        if self._policy.count == 0:
            return abstained("neighbours are turned off")
        if self._index is None or self._embeddings is None:
            return abstained("there is no search index with embeddings")
        text = await _text(self._store, document)
        sections = [] if text is None else split_sections(text, self._policy.chunk_size, 1)
        if not sections:
            return abstained("the document has no text")
        try:
            embedded = await self._embeddings.embed([self._policy.document_prefix + sections[0]])
        except EmbeddingsError as error:
            return abstained(f"the text could not be embedded: {error}")
        vector = tuple(embedded.vectors[0]) if embedded.vectors else ()
        wanted = self._policy.dimensions
        if not vector or (wanted is not None and len(vector) != wanted):
            return abstained("the text's vector does not fit the index")
        async with self._uow() as uow:
            owner = await uow.users.get(document.owner_id)
            drawers = await uow.drawers.list_accessible(owner.id)
        visibility = Visibility(owner.id, frozenset(drawer.id for drawer in drawers))
        try:
            hits = await self._index.similar(
                SimilarQuery(
                    vector=vector,
                    visibility=visibility,
                    filter=DocumentFilter(confirmed=True),
                    exclude=document.id,
                    limit=self._policy.count,
                )
            )
        except SearchError as error:
            return abstained(f"the search index cannot be asked: {error}")
        neighbours: list[JsonValue] = []
        async with self._uow() as uow:
            for hit in hits:
                found = await uow.documents.find(hit.id)
                if found is None or found.confirmed_at is None:
                    continue  # the index is behind
                drawer = await uow.drawers.find(found.drawer_id)
                if drawer is None or reach_access(owner, found, drawer) is None:
                    continue
                neighbours.append(
                    {
                        "document_id": str(found.id),
                        "score": None if hit.score is None else round(hit.score, 4),
                        "contact_id": None if found.contact_id is None else str(found.contact_id),
                        "document_type_id": (
                            None if found.document_type_id is None else str(found.document_type_id)
                        ),
                        "tag_ids": _texts(found.tag_ids),
                    }
                )
        if not neighbours:
            return abstained("no similar confirmed document")
        return NodeResult(outcome=Outcome.OK, output={"neighbours": neighbours})


def _texts(ids: Iterable[object]) -> list[JsonValue]:
    return list[JsonValue](sorted(str(id) for id in ids))
