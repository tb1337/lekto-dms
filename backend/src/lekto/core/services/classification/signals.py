"""The signals: each proposes metadata from one source, for the judge (`domain.verdict`).

A signal never decides the lane. It ends OK with what it found, or, if it has nothing to say,
with `output.abstained` naming why (no model trained, no embeddings, ...). Only the language
model's signal fails, when its answers do not fit or it cannot be reached after every retry.

- `signal_facts`: contacts whose name or alias stands whole in the text, and identifiers of
  contacts (IBAN, VAT number, ...) found in it, with the topic each points to; evidence, not a
  proposal of its own. The codes on the archive's pages count as well (`domain.codes`): their
  identifiers like those of the text, the payee of a GiroCode like a name in the text.
- `signal_classifier`: the trained classifier's probabilities for contact, type, topic and
  tags.
- `signal_neighbours`: the most similar confirmed documents the owner may read, by vector,
  with their contact, type, topic and tags.
"""

import asyncio
import json
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from lekto.core.domain import media_types
from lekto.core.domain.codes import (
    Code,
    code_identifiers,
    codes_from_json,
    codes_to_json,
)
from lekto.core.domain.documents import Document
from lekto.core.domain.errors import (
    ClassifierError,
    EmbeddingsError,
    NotFoundError,
    SearchError,
    ValidationError,
)
from lekto.core.domain.facts import facts_in
from lekto.core.domain.identifiers import IdentifierKind, identifiers_in
from lekto.core.domain.ids import ContactId, DocumentTypeId, TagId
from lekto.core.domain.json_value import (
    JsonObject,
    JsonValue,
    as_list,
    as_number,
    as_object,
    as_text,
    as_uuid,
)
from lekto.core.domain.master_data import Contact
from lekto.core.domain.permissions import reach_access
from lekto.core.domain.pipeline import Node, NodeResult, NodeRun, Outcome
from lekto.core.domain.search import Visibility
from lekto.core.domain.verdict import (
    ClassifierView,
    FactsView,
    KnownLabels,
    ModelProposal,
    Neighbour,
    Signals,
)
from lekto.core.ports.codes import CodeReader
from lekto.core.ports.embeddings import Embeddings
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.repository import DocumentFilter
from lekto.core.ports.search_index import SearchIndex, SimilarQuery
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services.classification.answers import StoredProposal
from lekto.core.services.classifier import ClassifierService
from lekto.core.services.indexing import split_sections
from lekto.core.services.nodes import ARCHIVE_FILE, work_directory
from lekto.core.services.objects import archive_key, codes_key, load_text

log = logging.getLogger(__name__)

ABSTAINED = "abstained"
"""Key of the output of a signal that had nothing to say: why."""
PROPOSAL = "proposal"
"""Key of the language model's proposal (`StoredProposal`) in the output of `signal_llm`."""
FACTS = "facts"
_RANKED = 5  # classes of contact and type the classifier's signal keeps


def abstained(reason: str, *, model_version: str | None = None) -> NodeResult:
    return NodeResult(outcome=Outcome.OK, model_version=model_version, output={ABSTAINED: reason})


async def _text(store: ObjectStore, document: Document) -> str | None:
    try:
        return (await load_text(store, document.id)).decode("utf-8", "replace")
    except NotFoundError:
        return None


class FactsSignal:
    """Hard evidence in the text and in the codes on the pages: a contact's name or alias,
    whole, and identifiers of contacts. A name alone proposes nothing (a bank statement names
    payees, a pay slip the employee); it backs or contradicts what other signals propose.

    The codes are read from the archive once (`codes`, without a reader none) and kept beside
    the document (`codes_key`); the OCR node drops them with a new archive. A code that cannot
    be read never fails the signal. The identifiers found are kept for the document
    (`DocumentIdentifierRepository`), applied with the result."""

    def __init__(
        self, uow: UnitOfWorkFactory, store: ObjectStore, codes: CodeReader | None = None
    ) -> None:
        self._uow = uow
        self._store = store
        self._codes = codes

    async def run(self, document: Document) -> "NodeResult | FactsResult":
        text = await _text(self._store, document)
        if text is None:
            return abstained("the document has no text", model_version=FACTS)
        codes = await self.codes(document)
        async with self._uow() as uow:
            contacts = await uow.contacts.list_all()
        # Matching every contact's names against a long text takes a while: not in the loop.
        output = await asyncio.to_thread(facts_of, text, contacts, codes or ())
        if codes is not None:
            output["codes"] = len(codes)
        found = await asyncio.to_thread(identifiers_in, text)
        for code in codes or ():
            found |= code_identifiers(code)
        result = NodeResult(outcome=Outcome.OK, model_version=FACTS, output=output)
        return FactsResult(result, frozenset(found))

    async def codes(self, document: Document) -> tuple[Code, ...] | None:
        """The codes on the archive's pages, read before or now; None without a reader, an
        archive, or when they cannot be read."""
        if self._codes is None:
            return None
        key = codes_key(document.id)
        try:
            kept = codes_from_json(json.loads(await self._store.get(key)))
        except NotFoundError:
            kept = None
        except (ValueError, ValidationError):
            log.warning("reading an unreadable file of codes again", extra={"key": key})
            kept = None
        if kept is not None:
            return kept
        try:
            async with work_directory() as work:
                archive = work / ARCHIVE_FILE
                await self._store.download(archive_key(document.id), archive)
                reading = await self._codes.read_codes(archive)
        except NotFoundError:
            return None
        except Exception:
            log.warning(
                "the codes were not read", exc_info=True, extra={"document_id": str(document.id)}
            )
            return None
        data = json.dumps(codes_to_json(reading.codes), ensure_ascii=False).encode("utf-8")
        await self._store.put(key, data, content_type=media_types.JSON)
        return reading.codes


@dataclass(frozen=True)
class FactsResult:
    """The facts, and the identifiers the document shows: kept for it when the result is
    recorded."""

    result: NodeResult
    identifiers: frozenset[tuple[IdentifierKind, str]]

    @property
    def output(self) -> JsonObject:
        return self.result.output

    async def apply(self, uow: UnitOfWork, document: Document, now: datetime) -> NodeResult:
        await uow.document_identifiers.replace(document.id, self.identifiers)
        return self.result


def facts_of(text: str, contacts: Sequence[Contact], codes: Sequence[Code] = ()) -> JsonObject:
    """What `signal_facts` reports for `text` and the `codes` of its pages (`domain.facts`);
    what a code holds is marked `in_code`."""
    facts = facts_in(text, contacts, codes)

    def marked(item: JsonObject, in_code: bool) -> JsonObject:
        return {**item, "in_code": True} if in_code else item

    return {
        "named": [
            marked(
                {"contact_id": str(item.contact_id), "name": item.name, "alias": item.alias},
                item.in_code,
            )
            for item in facts.named
        ],
        "identifiers": [
            marked(
                {
                    "contact_id": str(item.contact_id),
                    "kind": item.kind.value,
                    "value": item.value,
                    **({} if item.topic_id is None else {"topic_id": str(item.topic_id)}),
                },
                item.in_code,
            )
            for item in facts.identifiers
            if item.contact_id is not None
        ],
        "unknown_identifiers": [
            marked({"kind": item.kind.value, "value": item.value}, item.in_code)
            for item in facts.identifiers
            if item.contact_id is None
        ],
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
        view = ClassifierView(
            contacts=prediction.contacts[:_RANKED],
            document_types=prediction.document_types[:_RANKED],
            tags=prediction.tags,
            known_contacts=prediction.known_contacts,
            known_types=prediction.known_types,
            topics=prediction.topics[:_RANKED],
            known_topics=prediction.known_topics,
        )
        return NodeResult(
            outcome=Outcome.OK,
            model_version=f"classifier {model.number}",
            output={"model": model.number, **_classifier_to_json(view)},
        )


@dataclass(frozen=True, kw_only=True)
class NeighboursPolicy:
    """Configuration: the composition sets it from the settings, whose defaults are the one
    source."""

    count: int  # neighbours asked for; 0: none
    chunk_size: int  # of the first section, as the index cuts it
    document_prefix: str = ""  # put before it, as the index does
    dimensions: int | None = None  # the length of the vectors the index takes


class NeighboursSignal:
    """The most similar confirmed documents the owner may read: by the vector of the start of
    the text, against the index's vectors; their contact, type, topic and tags (from the
    database, not the index, which lags a little), and what any confirmed document carries
    (`known`): the values similar documents could have named."""

    def __init__(
        self,
        uow: UnitOfWorkFactory,
        store: ObjectStore,
        index: SearchIndex | None,
        embeddings: Embeddings | None,
        policy: NeighboursPolicy,
    ) -> None:
        self._uow = uow
        self._store = store
        self._index = index
        self._embeddings = embeddings
        self._policy = policy

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
            spaces = await uow.spaces.list_accessible(owner.id)
        visibility = Visibility(owner.id, frozenset(space.id for space in spaces))
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
        neighbours: list[Neighbour] = []
        async with self._uow() as uow:
            known = await uow.documents.confirmed_labels(owner.id)
            # They vote on the tags and topics the classification sets only, not on those set
            # by hand.
            tags = await uow.tags.list_all()
            targets = {tag.id for tag in tags if tag.is_target}
            topics = {tag.id for tag in tags if tag.is_topic_target}
            for hit in hits:
                found = await uow.documents.find(hit.id)
                if found is None or found.confirmed_at is None:
                    continue  # the index is behind
                space = await uow.spaces.find(found.space_id)
                if space is None or reach_access(owner, found, space) is None:
                    continue
                neighbours.append(
                    Neighbour(
                        document=str(found.id),
                        contact=found.contact_id,
                        document_type=found.document_type_id,
                        tags=frozenset(found.tag_ids & targets),
                        similarity=None if hit.score is None else round(hit.score, 4),
                        topic=found.topic_id if found.topic_id in topics else None,
                    )
                )
        if not neighbours:
            return abstained("no similar confirmed document")
        known = replace(known, tags=known.tags & targets, topics=known.topics & topics)
        output: JsonObject = {
            "neighbours": [_neighbour_to_json(item) for item in neighbours],
            "known": _known_to_json(known),
        }
        return NodeResult(outcome=Outcome.OK, output=output)


def _texts(ids: Iterable[object]) -> list[JsonValue]:
    return list[JsonValue](sorted(str(id) for id in ids))


# --- what the judge reads ---------------------------------------------------------------------


def signals_of(entries: Mapping[Node, NodeRun]) -> Signals:
    """The signals as the judge's rules take them; a signal that abstained (or never ran) is
    None."""

    def output(node: Node) -> JsonObject | None:
        entry = entries.get(node)
        if entry is None or ABSTAINED in entry.result.output:
            return None
        return entry.result.output

    neighbours = output(Node.SIGNAL_NEIGHBOURS)
    return Signals(
        model=_model_view(model_proposal(entries)),
        classifier=_classifier_view(output(Node.SIGNAL_CLASSIFIER)),
        neighbours=_neighbours_view(neighbours),
        facts=_facts_view(output(Node.SIGNAL_FACTS)),
        neighbours_know=_known_view(neighbours),
    )


def model_proposal(entries: Mapping[Node, NodeRun]) -> StoredProposal | None:
    """The language model's proposal as it stored it; None if it gave none."""
    entry = entries.get(Node.SIGNAL_LLM)
    if entry is None or ABSTAINED in entry.result.output:
        return None
    return StoredProposal.from_json(entry.result.output.get(PROPOSAL))


def _model_view(proposal: StoredProposal | None) -> ModelProposal | None:
    if proposal is None:
        return None
    return ModelProposal(
        sender=_optional_text(proposal.sender.value),
        sender_quote=_optional_text(proposal.sender.evidence),
        recipient=_optional_text(proposal.recipient),
        document_type=_optional_text(proposal.document_type),
        new_document_type=_optional_text(proposal.new_document_type),
        tags=proposal.tags,
        new_tags=proposal.new_tags,
        topic=_optional_text(proposal.topic),
    )


# Each signal's output is written and read by a pair of functions below, side by side.


def _classifier_to_json(view: ClassifierView) -> JsonObject:
    known = KnownLabels(
        contacts=view.known_contacts, document_types=view.known_types, topics=view.known_topics
    )
    return {
        "contacts": [[str(id), round(p, 4)] for id, p in view.contacts],
        "document_types": [[str(id), round(p, 4)] for id, p in view.document_types],
        "topics": [[str(id), round(p, 4)] for id, p in view.topics],
        "tags": {str(id): round(p, 4) for id, p in view.tags.items()},
        "known": _known_to_json(known),
    }


def _classifier_view(output: JsonObject | None) -> ClassifierView | None:
    if output is None:
        return None
    known = _known_from_json(output.get("known")) or KnownLabels()
    tags = as_object(output.get("tags")) or {}
    return ClassifierView(
        contacts=[(ContactId(id), p) for id, p in _ranking(output.get("contacts"))],
        document_types=[
            (DocumentTypeId(id), p) for id, p in _ranking(output.get("document_types"))
        ],
        tags={
            TagId(id): p
            for key, value in tags.items()
            if (id := as_uuid(key)) is not None and (p := as_number(value)) is not None
        },
        known_contacts=known.contacts,
        known_types=known.document_types,
        topics=[(TagId(id), p) for id, p in _ranking(output.get("topics"))],
        known_topics=known.topics,
    )


def _ranking(value: JsonValue) -> list[tuple[UUID, float]]:
    """The pairs `[id, probability]` as `_classifier_to_json` writes them."""
    ranked = []
    for item in as_list(value):
        pair = as_list(item)
        if len(pair) == 2:
            id, p = as_uuid(pair[0]), as_number(pair[1])
            if id is not None and p is not None:
                ranked.append((id, p))
    return ranked


def _ids(value: JsonValue) -> list[UUID]:
    return [id for item in as_list(value) if (id := as_uuid(item)) is not None]


def _id_of[I](kind: Callable[[UUID], I], value: JsonValue) -> I | None:
    found = as_uuid(value)
    return None if found is None else kind(found)


def _neighbour_to_json(neighbour: Neighbour) -> JsonObject:
    return {
        "document_id": neighbour.document,
        "score": neighbour.similarity,
        "contact_id": _optional_id(neighbour.contact),
        "document_type_id": _optional_id(neighbour.document_type),
        "tag_ids": _texts(neighbour.tags),
        "topic_id": _optional_id(neighbour.topic),
    }


def _neighbours_view(output: JsonObject | None) -> tuple[Neighbour, ...] | None:
    if output is None:
        return None
    return tuple(
        Neighbour(
            document=as_text(item.get("document_id")) or "",
            contact=_id_of(ContactId, item.get("contact_id")),
            document_type=_id_of(DocumentTypeId, item.get("document_type_id")),
            tags=frozenset(TagId(id) for id in _ids(item.get("tag_ids"))),
            similarity=as_number(item.get("score")),
            topic=_id_of(TagId, item.get("topic_id")),
        )
        for value in as_list(output.get("neighbours"))
        if (item := as_object(value)) is not None
    )


def _known_to_json(known: KnownLabels) -> JsonObject:
    return {
        "contacts": _texts(known.contacts),
        "document_types": _texts(known.document_types),
        "tags": _texts(known.tags),
        "topics": _texts(known.topics),
    }


def _known_from_json(value: JsonValue) -> KnownLabels | None:
    known = as_object(value)
    if known is None:
        return None
    return KnownLabels(
        contacts=frozenset(ContactId(id) for id in _ids(known.get("contacts"))),
        document_types=frozenset(DocumentTypeId(id) for id in _ids(known.get("document_types"))),
        tags=frozenset(TagId(id) for id in _ids(known.get("tags"))),
        topics=frozenset(TagId(id) for id in _ids(known.get("topics"))),
    )


def _known_view(output: JsonObject | None) -> KnownLabels | None:
    """What the similar documents could have named; None for an entry from before it was
    kept (then they count as covering every value)."""
    return None if output is None else _known_from_json(output.get("known"))


def _optional_id(id: object | None) -> str | None:
    return None if id is None else str(id)


def _facts_view(output: JsonObject | None) -> FactsView | None:
    if output is None:
        return None
    identifiers: dict[ContactId, tuple[str, ...]] = {}
    topics: dict[ContactId, dict[TagId, tuple[str, ...]]] = {}
    for value in as_list(output.get("identifiers")):
        item = as_object(value) or {}
        contact, kind = _id_of(ContactId, item.get("contact_id")), as_text(item.get("kind"))
        if contact is None or kind is None:
            continue
        identifiers[contact] = (*identifiers.get(contact, ()), kind)
        topic = _id_of(TagId, item.get("topic_id"))
        if topic is not None:
            pairs = topics.setdefault(contact, {})
            pairs[topic] = (*pairs.get(topic, ()), kind)
    named = (
        _id_of(ContactId, (as_object(value) or {}).get("contact_id"))
        for value in as_list(output.get("named"))
    )
    return FactsView(
        named=frozenset(contact for contact in named if contact is not None),
        identifiers=identifiers,
        topics=topics,
    )


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
