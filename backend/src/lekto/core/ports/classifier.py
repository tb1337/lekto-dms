"""Classifier: learns contact, document type, topic, tags and the space from confirmed
documents (their texts and metadata) and predicts them for a new text, as Paperless-ngx's
matching does. A trained model is bytes: the caller keeps it (in the object store) and hands it
back to predict."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from lekto.core.domain.ids import ContactId, DocumentTypeId, TagId
from lekto.core.domain.json_value import JsonObject


@dataclass(frozen=True)
class TrainingExample:
    """A confirmed document: its text and what a person said it is (None: no contact, type or
    topic). `labelled`: a person confirmed the metadata; a document of which a person decided
    only the space teaches only `space` (a label: a space id, or `OWN_SPACE` for its uploader's
    personal space)."""

    text: str
    contact: ContactId | None
    document_type: DocumentTypeId | None
    tags: frozenset[TagId] = frozenset()
    topic: TagId | None = None
    space: str | None = None
    labelled: bool = True


@dataclass(frozen=True)
class TrainedModel:
    data: bytes
    summary: JsonObject  # what it learned: classes per target, size; for the status


@dataclass(frozen=True)
class Prediction:
    """Probabilities by class: for contact, type and topic of all classes the model knows
    (summing to 1), best first; for every tag it knows, its own. A class the model does not
    know (too few examples) is not in `known_*`: the model cannot name it."""

    contacts: Sequence[tuple[ContactId, float]] = ()
    document_types: Sequence[tuple[DocumentTypeId, float]] = ()
    tags: Mapping[TagId, float] = field(default_factory=dict)
    topics: Sequence[tuple[TagId, float]] = ()
    spaces: Sequence[tuple[str, float]] = ()  # by label, as `TrainingExample.space`

    @property
    def known_contacts(self) -> frozenset[ContactId]:
        return frozenset(contact for contact, _ in self.contacts)

    @property
    def known_types(self) -> frozenset[DocumentTypeId]:
        return frozenset(kind for kind, _ in self.document_types)

    @property
    def known_topics(self) -> frozenset[TagId]:
        return frozenset(topic for topic, _ in self.topics)

    @property
    def known_spaces(self) -> frozenset[str]:
        return frozenset(space for space, _ in self.spaces)


class Classifier(Protocol):
    """Errors: ClassifierError (see there). Training and predicting take a while on the CPU;
    adapters run them off the event loop."""

    @property
    def name(self) -> str:
        """The method and its version, for the log."""
        ...

    async def train(self, examples: Sequence[TrainingExample]) -> TrainedModel:
        """A model of the examples. A class needs at least two examples (and a tag two
        documents without it); a target with fewer than two classes is not learned."""
        ...

    async def predict(self, model: bytes, text: str) -> Prediction: ...
