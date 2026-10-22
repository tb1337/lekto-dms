"""The judge's rules: contact, document type, topic and tags from what the signals proposed.

A signal *names* a value when it is sure of it:

- the language model: its sender matches a contact (name or alias, legal forms and
  punctuation aside) at least `accept` and no other contact comes close; a type or tag from the
  lists;
- the classifier: its best class with at least `classifier` probability (a tag: its own);
- the similar documents: at least two of them, and more than half of those found, carry it;
  a contact only if no other contact is carried by two of them as well (similar documents split
  between senders are alike by their form, a pay slip's employee for one, not by their sender).

Facts in the text name nothing on their own; they are evidence: an identifier of the contact,
or its name (or alias) standing whole in the text, is *hard* evidence. An identifier of a
contact alone makes it a candidate, never green.

A signal *contradicts* a value when it names another one; for a contact also when the model's
recipient is that contact, when an identifier of another contact stands in the text, and when
the model's sender is none of the contacts and unrelated to this one. A contradiction is
always uncertain, also against a value the other signal could not have named.

A signal *covers* a value when it could have named it: the classifier if it was trained on
the value, the similar documents if any was found and a confirmed document carries the
value.

- A contact is green without contradiction if hard evidence backs it and a signal names it, or
  if the model's sender matches it at least `suggest` and the classifier or the similar
  documents name it.
- A type is green without contradiction if two signals name it, or if only the model names it
  and no other signal covers it: the rule from before the signals, per value, until the
  others know it.
- A tag is set as a type is green; one only a single signal names is a suggestion. Tags never
  make a document uncertain. Only the tags the classification sets are judged (document tags
  set `auto`); a tag set by hand is never proposed.
- A topic is judged after the contact, among the topics that contact enables (those set
  `auto`): it is set if the contact is green and an identifier of the pair of contact and
  topic stands in the text and a signal names the topic, or two signals name it. Otherwise it
  is a suggestion; if signals (or identifiers of the pair) name different topics, it stays
  empty with all candidates. A topic never makes a document uncertain. Under a contact that is
  only suggested, the topic is only suggested too.
- A space is judged among the spaces the uploader may file into (`SpaceChoice`), as a type:
  sure if two signals name it, or only the model names it and no other signal covers it. A
  space a person decided is left as it is. Sure of the space the document lies in: nothing
  changes. Sure of another that shows the document to no one new (fewer or the same
  members): it moves there. Sure of one with members who cannot see it now: uncertain, with
  the space as suggestion and its new readers in the reason (more visibility only with a
  person's click). Not sure: it stays where it is, never uncertain.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from lekto.core.domain.classification import (
    CONTACT,
    DOCUMENT_TYPE,
    SPACE,
    TAGS,
    TOPIC,
    Candidate,
    CandidateSource,
    FieldCheck,
)
from lekto.core.domain.ids import ContactId, DocumentTypeId, SpaceId, TagId, UserId
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.master_data import Contact, DocumentType, Tag
from lekto.core.domain.names import best_match, match_key, mentions, related
from lekto.core.domain.pipeline import Node, Outcome
from lekto.core.domain.sorting import sort_key
from lekto.core.domain.tag_tree import TagTree
from lekto.core.domain.validation import name_key

LLM = Node.SIGNAL_LLM.value
CLASSIFIER = Node.SIGNAL_CLASSIFIER.value
NEIGHBOURS = Node.SIGNAL_NEIGHBOURS.value
FACTS = Node.SIGNAL_FACTS.value
_UNSURE = 0.89  # the confidence of an uncertain field stays below acceptance


@dataclass(frozen=True, kw_only=True)
class Thresholds:
    """The judge's thresholds. The first three are configuration (the composition sets them
    from the settings, whose defaults are the one source); `ambiguity` is a constant."""

    accept: float  # the model's sender matches a contact this well: it names it
    suggest: float  # this well: a weak match, a suggestion
    classifier: float  # the classifier this sure: it names the class
    ambiguity: float = 0.05  # two contacts this close: the model names neither


@dataclass(frozen=True)
class ModelProposal:
    """What the language model proposed (`signal_llm`)."""

    sender: str | None = None
    sender_quote: str | None = None
    recipient: str | None = None
    document_type: str | None = None
    new_document_type: str | None = None
    tags: tuple[str, ...] = ()
    new_tags: tuple[str, ...] = ()
    topic: str | None = None
    space: SpaceId | None = None  # the listed space it chose (`propose-5`)


@dataclass(frozen=True)
class ClassifierView:
    """The classifier's probabilities (`signal_classifier`), best first, and what it knows."""

    contacts: Sequence[tuple[ContactId, float]] = ()
    document_types: Sequence[tuple[DocumentTypeId, float]] = ()
    tags: Mapping[TagId, float] = field(default_factory=dict)
    known_contacts: frozenset[ContactId] = frozenset()
    known_types: frozenset[DocumentTypeId] = frozenset()
    topics: Sequence[tuple[TagId, float]] = ()
    known_topics: frozenset[TagId] = frozenset()
    # Spaces among the uploader's candidates (a personal space as the uploader's own one).
    spaces: Sequence[tuple[SpaceId, float]] = ()
    known_spaces: frozenset[SpaceId] = frozenset()


@dataclass(frozen=True)
class Neighbour:
    document: str
    contact: ContactId | None
    document_type: DocumentTypeId | None
    tags: frozenset[TagId] = frozenset()
    similarity: float | None = None  # to the document, as the search index measures it
    topic: TagId | None = None
    # Its decided space as one of the uploader's candidates: one in its own uploader's
    # personal space votes for this uploader's personal space; None: no vote.
    space: SpaceId | None = None


@dataclass(frozen=True)
class FactsView:
    """Contacts named in the text, the kinds of their identifiers found in it, and the topics
    those identifiers point to (each with the kinds that point to it): the pairs of contact and
    topic the text shows."""

    named: frozenset[ContactId] = frozenset()
    identifiers: Mapping[ContactId, tuple[str, ...]] = field(default_factory=dict)
    topics: Mapping[ContactId, Mapping[TagId, tuple[str, ...]]] = field(default_factory=dict)


@dataclass(frozen=True)
class KnownLabels:
    """The contacts, types, topics and tags confirmed documents carry: what similar documents
    can name."""

    contacts: frozenset[ContactId] = frozenset()
    document_types: frozenset[DocumentTypeId] = frozenset()
    tags: frozenset[TagId] = frozenset()
    topics: frozenset[TagId] = frozenset()
    spaces: frozenset[SpaceId] = frozenset()  # as candidates of the uploader


@dataclass(frozen=True)
class Signals:
    """What each signal said; None where it abstained (or, before the signals, never ran).
    `neighbours_know`: what the similar documents could have named; None (an older entry)
    counts as everything."""

    model: ModelProposal | None = None
    classifier: ClassifierView | None = None
    neighbours: tuple[Neighbour, ...] | None = None
    facts: FactsView | None = None
    neighbours_know: KnownLabels | None = None


# --- ranking ----------------------------------------------------------------------------------


class _Named(Protocol):
    @property
    def name(self) -> str: ...


@dataclass(frozen=True, kw_only=True)
class _Ranking[K]:
    """What the signals say about the values of one field (contact, type or topic), worked out
    once, and the order of its candidates: by the number of signals that name a value, then
    hard evidence in the text, the classifier's probability, how well the model's answer matches
    it, the similar documents that carry it, and its name. The judges differ only in their
    rules: when a value is green and what contradicts it."""

    names: Mapping[K, _Named]  # the values the field can take
    answer: Mapping[K, CandidateSource]  # the value the model's answer matches, as a source
    probabilities: Mapping[K, float]  # the classifier's
    neighbours: tuple[Neighbour, ...]
    votes: Counter[K]  # how many of the similar documents carry a value
    namers: Mapping[K, tuple[str, ...]]  # the signals that name a value
    evidence: Mapping[K, CandidateSource]  # hard evidence in the text, as a source
    identified: tuple[K, ...]  # the values identifiers in the text point to
    thresholds: Thresholds
    carried: Callable[[Neighbour], K | None]  # the value a similar document carries

    @classmethod
    def of(
        cls,
        names: Mapping[K, _Named],
        signals: Signals,
        thresholds: Thresholds,
        *,
        answer: Mapping[K, CandidateSource],
        classified: Sequence[tuple[K, float]],
        carried: Callable[[Neighbour], K | None],
        undivided: bool = False,
        evidence: Mapping[K, CandidateSource] | None = None,
        identified: Iterable[K] = (),
    ) -> "_Ranking[K]":
        """`answer`: the value the model's answer matches, as a source (the model names it if
        the source says so); `classified`: the classifier's probabilities, best first;
        `carried`: the value a similar document carries; `undivided`: as for `_majority`."""
        # A model trained before a value was deleted (two merged) still knows it: leave it out.
        ranking = [(id, p) for id, p in classified if id in names]
        neighbours = signals.neighbours or ()
        votes = Counter(
            id for item in neighbours if (id := carried(item)) is not None and id in names
        )
        namers: dict[K, tuple[str, ...]] = {}
        for signal, named in (
            (LLM, next((id for id, source in answer.items() if source.names), None)),
            (CLASSIFIER, _top(ranking, thresholds.classifier)),
            (NEIGHBOURS, _majority(votes, len(neighbours), undivided=undivided)),
        ):
            if named is not None:
                namers[named] = (*namers.get(named, ()), signal)
        return cls(
            names=names,
            answer=answer,
            probabilities=dict(ranking),
            neighbours=neighbours,
            votes=votes,
            namers=namers,
            evidence=evidence or {},
            identified=tuple(identified),
            thresholds=thresholds,
            carried=carried,
        )

    def candidates(self) -> list[K]:
        """The values a signal names or points to, best first."""
        likely = (id for id, p in self.probabilities.items() if p >= 1 - self.thresholds.classifier)
        found = _unique([*self.namers, *self.answer, *self.identified, *likely, *self.votes])
        return sorted(
            (id for id in found if id in self.names),
            key=lambda id: (
                -len(self.namers.get(id, ())),
                -(id in self.evidence),
                -self.probabilities.get(id, 0.0),
                -self._matches(id),
                -self.votes.get(id, 0),
                sort_key(self.names[id].name),
            ),
        )

    def listed(self, ranked: Iterable[K], contradicted: Callable[[K], bool]) -> list[Candidate]:
        """The candidates `ranked`, each with what the signals say about it."""
        return [
            Candidate(
                value=str(id),
                label=self.names[id].name,
                sources=self.sources(id),
                contradicted=contradicted(id),
            )
            for id in ranked
        ]

    def sources(self, id: K) -> tuple[CandidateSource, ...]:
        """What each signal says about the value `id`."""
        found = [self.answer[id]] if id in self.answer else []
        if id in self.probabilities:
            p = self.probabilities[id]
            named = p >= self.thresholds.classifier
            found.append(
                CandidateSource(
                    signal=CLASSIFIER, names=named, score=p, threshold=self.thresholds.classifier
                )
            )
        if self.votes.get(id):
            found.append(self._neighbour_source(id))
        if id in self.evidence:
            found.append(self.evidence[id])
        return tuple(found)

    def _matches(self, id: K) -> float:
        """How well the model's answer matches the value `id`."""
        source = self.answer.get(id)
        return (source.score or 0.0) if source is not None else 0.0

    def _neighbour_source(self, id: K) -> CandidateSource:
        neighbours = self.neighbours
        carrying = [item for item in neighbours if self.carried(item) == id]
        similarities = [item.similarity for item in carrying if item.similarity is not None]
        count = self.votes.get(id, 0)
        return CandidateSource(
            signal=NEIGHBOURS,
            names=NEIGHBOURS in self.namers.get(id, ()),
            score=count / len(neighbours) if neighbours else None,
            similarity=max(similarities) if similarities else None,
            votes=count,
            of=len(neighbours),
            documents=tuple(item.document for item in carrying),
        )


# --- contact ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _ContactView:
    """What the signals say about contacts, worked out once."""

    names: Mapping[ContactId, Contact]
    sender: str | None
    quote: str | None
    matched: ContactId | None  # the contact the model's sender matches at least `suggest`
    match_score: float
    ambiguous: bool  # another contact matches the sender about as well
    recipient: ContactId | None
    facts: FactsView
    ranking: _Ranking[ContactId]
    thresholds: Thresholds

    def hard(self, id: ContactId) -> bool:
        return id in self.facts.identifiers or id in self.facts.named

    def contradicted(self, id: ContactId) -> bool:
        unrelated = (
            self.sender is not None
            and self.matched is None
            and not any(
                related(match_key(self.sender), match_key(own), threshold=self.thresholds.suggest)
                for own in self.names[id].names()
            )
        )
        return (
            any(other != id for other in self.ranking.namers)
            or self.recipient == id
            or any(other != id for other in self.facts.identifiers)
            or unrelated
        )

    def green(self, id: ContactId) -> bool:
        if self.contradicted(id):
            return False
        naming = self.ranking.namers.get(id, ())
        backed = CLASSIFIER in naming or NEIGHBOURS in naming
        soft = self.matched == id and not self.ambiguous and backed
        return (self.hard(id) and id in self.ranking.namers) or soft


def judge_contact(
    signals: Signals,
    contacts: Sequence[Contact],
    thresholds: Thresholds,
) -> FieldCheck:
    view = _contact_view(signals, contacts, thresholds)
    names, probabilities = view.names, view.ranking.probabilities
    ranked = view.ranking.candidates()
    listed = view.ranking.listed(ranked, view.contradicted)
    if view.sender and view.matched is None:
        source = CandidateSource(signal=LLM, quote=view.quote)
        listed.append(Candidate(value=None, label=view.sender, sources=(source,)))
    shown = _quote_names(view.quote, names[view.matched] if view.matched else None, view.sender)
    chosen = next((id for id in ranked if view.green(id)), None)
    if chosen is not None:
        score = max(
            view.match_score if view.matched == chosen else 0.0,
            probabilities.get(chosen, 0.0),
            thresholds.accept,
        )
        return FieldCheck(
            field=CONTACT,
            outcome=Outcome.OK,
            confidence=min(score, 1.0),
            proposed=view.sender,
            evidence=view.quote,
            value=str(chosen),
            quote_shows_value=shown,
            candidates=tuple(listed),
        )
    top = ranked[0] if ranked else None
    score = max(view.match_score, probabilities.get(top, 0.0) if top else 0.0)
    return FieldCheck(
        field=CONTACT,
        outcome=Outcome.UNCERTAIN,
        confidence=min(score, _UNSURE),
        reason=_contact_reason(view, top, signals.model is None),
        proposed=view.sender,
        evidence=view.quote,
        suggestion=None if top is None else str(top),
        new_name=view.sender if view.sender and view.matched is None else None,
        quote_shows_value=shown,
        candidates=tuple(listed),
    )


def _contact_view(
    signals: Signals, contacts: Sequence[Contact], thresholds: Thresholds
) -> _ContactView:
    pairs = [(contact, own) for contact in contacts for own in contact.names()]
    model = signals.model
    sender = model.sender if model else None
    quote = model.sender_quote if model else None
    matched: ContactId | None = None
    match_score, model_names, ambiguous = 0.0, False, False
    if sender:
        match = best_match(sender, pairs)
        if match.best is not None and match.score >= thresholds.suggest:
            matched, match_score = match.best.id, match.score
            ambiguous = match.runner_up >= match.score - thresholds.ambiguity
            model_names = match.score >= thresholds.accept and not ambiguous
    recipient: ContactId | None = None
    if model and model.recipient:
        found = best_match(model.recipient, pairs)
        if found.best is not None and found.score >= thresholds.accept:
            recipient = found.best.id
    names = {contact.id: contact for contact in contacts}
    answer: dict[ContactId, CandidateSource] = {}
    if matched is not None:
        answer[matched] = CandidateSource(
            signal=LLM,
            names=model_names,
            score=match_score,
            threshold=thresholds.accept,
            quote=quote,
        )
    facts = signals.facts or FactsView()
    evidence = {
        id: CandidateSource(
            signal=FACTS,
            identifiers=facts.identifiers.get(id, ()),
            named_in_text=id in facts.named,
        )
        for id in (*facts.identifiers, *facts.named)
    }
    ranking = _Ranking.of(
        names,
        signals,
        thresholds,
        answer=answer,
        classified=signals.classifier.contacts if signals.classifier else (),
        carried=lambda item: item.contact,
        undivided=True,
        evidence=evidence,
        identified=facts.identifiers,
    )
    return _ContactView(
        names=names,
        sender=sender,
        quote=quote,
        matched=matched,
        match_score=match_score,
        ambiguous=ambiguous,
        recipient=recipient,
        facts=facts,
        ranking=ranking,
        thresholds=thresholds,
    )


def _disagreeing(names: Iterable[str]) -> str:
    """The reason when more than one value is named."""
    return "the signals disagree: " + " or ".join(f"'{name}'" for name in names)


def _contact_reason(view: _ContactView, top: ContactId | None, no_model: bool) -> str:
    names, namers = view.names, view.ranking.namers
    if len(namers) > 1:
        return _disagreeing(names[id].name for id in namers)
    if top is not None and view.recipient == top:
        return f"'{names[top].name}' is the recipient, not the sender"
    if len(view.facts.identifiers) > 1:
        return "identifiers of several contacts stand in the text"
    if top is None:
        if view.sender:
            return f"no contact matches '{view.sender}'; a new contact is proposed"
        silent = " (the language model did not answer)" if no_model else ""
        return f"no contact recognised{silent}"
    name = names[top].name
    if view.sender and view.matched is None:
        return f"'{view.sender}' is no contact, and only other signals point to '{name}'"
    if top not in namers:
        if top == view.matched and view.match_score >= view.thresholds.accept:
            return f"'{view.sender}' matches several contacts"
        if top == view.matched:
            return f"'{view.sender}' is only similar to the contact '{name}'"
        return f"'{name}' is only suggested: no signal is sure of it"
    if not view.hard(top):
        return f"the contact '{name}' does not appear in the text"
    return f"only one signal names '{name}'"


def _quote_names(quote: str | None, contact: Contact | None, sender: str | None) -> bool | None:
    """Whether the model's quote shows the contact's name (or the sender as read)."""
    if not quote:
        return None
    key = match_key(quote)
    own = contact.names() if contact is not None else [sender] if sender else []
    return any(mentions(key, match_key(name)) for name in own)


# --- document type ----------------------------------------------------------------------------


def judge_type(
    signals: Signals,
    types: Sequence[DocumentType],
    thresholds: Thresholds,
) -> FieldCheck:
    names = {kind.id: kind for kind in types}
    model = signals.model
    proposed = model.document_type if model else None
    by_model = _by_name(types, proposed) if proposed else None
    new = (model.new_document_type if model else None) or (
        proposed if proposed and by_model is None else None
    )
    classifier = signals.classifier
    ranking = _Ranking.of(
        names,
        signals,
        thresholds,
        answer={by_model.id: CandidateSource(signal=LLM, names=True)} if by_model else {},
        classified=classifier.document_types if classifier else (),
        carried=lambda item: item.document_type,
    )
    namers, probabilities = ranking.namers, ranking.probabilities
    known = signals.neighbours_know

    def covered_by_others(id: DocumentTypeId) -> bool:
        by_classifier = classifier is not None and id in classifier.known_types
        by_neighbours = bool(ranking.neighbours) and (known is None or id in known.document_types)
        return by_classifier or by_neighbours

    def contradicted(id: DocumentTypeId) -> bool:
        return any(other != id for other in namers)

    def green(id: DocumentTypeId) -> bool:
        naming = namers.get(id, ())
        sole = naming == (LLM,) and not covered_by_others(id)
        return not contradicted(id) and (len(naming) >= 2 or sole)

    ranked = ranking.candidates()
    listed = ranking.listed(ranked, contradicted)
    if new:
        listed.append(Candidate(value=None, label=new, sources=(CandidateSource(signal=LLM),)))
    chosen = next((id for id in ranked if green(id)), None)
    if chosen is not None:
        sure = len(namers[chosen]) >= 2 or not probabilities
        return FieldCheck(
            field=DOCUMENT_TYPE,
            outcome=Outcome.OK,
            confidence=1.0 if sure else max(probabilities.get(chosen, 0.0), thresholds.accept),
            proposed=proposed,
            value=str(chosen),
            candidates=tuple(listed),
        )
    top = ranked[0] if ranked else None
    return FieldCheck(
        field=DOCUMENT_TYPE,
        outcome=Outcome.UNCERTAIN,
        confidence=min(probabilities.get(top, 0.0) if top else 0.0, _UNSURE),
        reason=_type_reason(names, namers, top, new),
        proposed=proposed,
        suggestion=None if top is None else str(top),
        new_name=new,
        candidates=tuple(listed),
    )


def _type_reason(
    names: Mapping[DocumentTypeId, DocumentType],
    namers: Mapping[DocumentTypeId, tuple[str, ...]],
    top: DocumentTypeId | None,
    new: str | None,
) -> str:
    if len(namers) > 1:
        return _disagreeing(names[id].name for id in namers)
    if top is not None and top in namers:
        return f"only one signal names '{names[top].name}'"
    if new:
        return f"no document type fits; a new type '{new}' is proposed"
    if top is not None:
        return f"'{names[top].name}' is only suggested: no signal is sure of it"
    return "no document type recognised"


# --- tags -------------------------------------------------------------------------------------


def judge_tags(
    signals: Signals,
    tags: Sequence[Tag],
    thresholds: Thresholds,
) -> FieldCheck:
    """Always OK: tags set are those two signals name, or the model alone where no other
    signal could have, without the ancestors of others set (`TagTree.normalise`); those one
    signal names are a suggestion (their ids). `tags`: all tags; only the classification's
    targets (`Tag.is_target`) are named."""
    targets = [tag for tag in tags if tag.is_target]
    names = {tag.id: tag for tag in targets}
    model = signals.model
    proposed_names = model.tags if model else ()
    by_model = {found.id for name in proposed_names if (found := _by_name(targets, name))}
    classifier = signals.classifier
    probabilities = {
        id: p for id, p in (classifier.tags if classifier else {}).items() if id in names
    }
    neighbours = signals.neighbours or ()
    carried = Counter(tag for item in neighbours for tag in item.tags)

    def namers(id: TagId) -> tuple[str, ...]:
        found = []
        if id in by_model:
            found.append(LLM)
        if probabilities.get(id, 0.0) >= thresholds.classifier:
            found.append(CLASSIFIER)
        if carried.get(id, 0) >= 2 and carried[id] > len(neighbours) / 2:
            found.append(NEIGHBOURS)
        return tuple(found)

    known = signals.neighbours_know

    def covered_by_others(id: TagId) -> bool:
        by_neighbours = bool(neighbours) and (known is None or id in known.tags)
        return by_neighbours or id in probabilities

    applied: list[TagId] = []
    suggested: list[TagId] = []
    for id in _unique([*by_model, *probabilities, *carried]):
        naming = namers(id)
        if id not in names or not naming:
            continue
        if len(naming) >= 2 or (naming == (LLM,) and not covered_by_others(id)):
            applied.append(id)
        else:
            suggested.append(id)
    by_name = sorted([*applied, *suggested], key=lambda id: sort_key(names[id].name))
    kept = TagTree.of(tags).normalise(applied)
    applied = [id for id in applied if id in kept]
    candidates = tuple(
        Candidate(
            value=str(id),
            label=names[id].name,
            sources=tuple(CandidateSource(signal=signal, names=True) for signal in namers(id)),
        )
        for id in by_name
    )
    suggestion: list[JsonValue] = [
        str(id) for id in sorted(suggested, key=lambda id: sort_key(names[id].name))
    ]
    proposed: JsonValue = None
    if model is not None:
        proposed = {"tags": list(model.tags), "new_tags": list(model.new_tags)}
    return FieldCheck(
        field=TAGS,
        outcome=Outcome.OK,
        confidence=1.0,
        proposed=proposed,
        value=[str(id) for id in by_name if id in applied],
        suggestion=suggestion or None,
        candidates=candidates,
    )


# --- topic ------------------------------------------------------------------------------------


def judge_topic(
    signals: Signals,
    contact: FieldCheck,
    contacts: Sequence[Contact],
    tags: Sequence[Tag],
    thresholds: Thresholds,
) -> FieldCheck:
    """Always OK, as tags: the topic of the contact the judge decided (`contact`, the check of
    `judge_contact`), among the topics it enables that the classification sets
    (`Tag.is_topic_target`). Set if the contact is green and an identifier of the pair stands in
    the text and a signal names the topic, or two signals name it; otherwise a suggestion (its
    id), also for every topic under a contact that is only suggested. Signals or identifiers that
    name different topics leave it empty, with all candidates. `tags`: all tags."""
    green = contact.ok and isinstance(contact.value, str)
    chosen = contact.value if green else contact.suggestion
    owner = next((item for item in contacts if str(item.id) == chosen), None)
    model = signals.model
    proposed: JsonValue = None if model is None else model.topic
    if owner is None:
        return FieldCheck(
            field=TOPIC,
            outcome=Outcome.OK,
            confidence=1.0,
            reason="no contact: a topic is one of a contact's",
            proposed=proposed,
        )
    names = {tag.id: tag for tag in tags if tag.is_topic_target and tag.id in owner.topic_ids}
    by_model = _by_name(list(names.values()), model.topic) if model and model.topic else None
    classifier = signals.classifier
    evidence = {
        id: kinds
        for id, kinds in (signals.facts or FactsView()).topics.get(owner.id, {}).items()
        if id in names
    }
    ranking = _Ranking.of(
        names,
        signals,
        thresholds,
        answer={by_model.id: CandidateSource(signal=LLM, names=True)} if by_model else {},
        classified=classifier.topics if classifier else (),
        carried=lambda item: item.topic,
        evidence={
            id: CandidateSource(signal=FACTS, identifiers=kinds) for id, kinds in evidence.items()
        },
        identified=evidence,
    )
    namers = ranking.namers
    named = set(namers) | set(evidence)

    def sure(id: TagId) -> bool:
        naming = namers.get(id, ())
        return len(named) == 1 and ((id in evidence and bool(naming)) or len(naming) >= 2)

    ranked = ranking.candidates()
    listed = tuple(ranking.listed(ranked, lambda id: any(other != id for other in named)))
    top = ranked[0] if ranked else None
    if green and top is not None and sure(top):
        return FieldCheck(
            field=TOPIC,
            outcome=Outcome.OK,
            confidence=1.0,
            proposed=proposed,
            value=str(top),
            candidates=listed,
        )
    if len(named) > 1:
        reason = _disagreeing(names[id].name for id in ranked if id in named)
        suggestion = None
    elif top is None:
        reason = f"no topic of '{owner.name}' recognised"
        suggestion = None
    else:
        suggestion = str(top)
        if not green:
            reason = f"the contact '{owner.name}' is only suggested"
        elif top in namers:
            reason = f"only one signal names '{names[top].name}'"
        elif top in evidence:
            reason = f"only an identifier points to '{names[top].name}'"
        else:
            reason = f"'{names[top].name}' is only suggested: no signal is sure of it"
    return FieldCheck(
        field=TOPIC,
        outcome=Outcome.OK,
        confidence=1.0,
        reason=reason,
        proposed=proposed,
        suggestion=suggestion,
        candidates=listed,
    )


# --- space ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SpaceOption:
    """A space as the judge weighs it: how reasons name it and who may see what lies in it."""

    name: str
    members: frozenset[UserId]


@dataclass(frozen=True)
class SpaceChoice:
    """Where a document may go: the spaces its uploader may file into (`options`, with the
    space it lies in, `current`), whether a person decided its space (`locked`), and the names
    of the members (for the reason)."""

    current: SpaceId
    options: Mapping[SpaceId, SpaceOption]
    locked: bool = False
    people: Mapping[UserId, str] = field(default_factory=dict)


def judge_space(signals: Signals, choice: SpaceChoice, thresholds: Thresholds) -> FieldCheck:
    """The space for the document (see the module): the check's `value` is the space it gets
    (None: it stays where it is)."""
    current = choice.current
    names = choice.options
    if choice.locked:
        return FieldCheck(
            field=SPACE, outcome=Outcome.OK, confidence=1.0, reason="a person chose the space"
        )
    model = signals.model
    by_model = model.space if model is not None and model.space in names else None
    classifier = signals.classifier
    ranking = _Ranking.of(
        names,
        signals,
        thresholds,
        answer={by_model: CandidateSource(signal=LLM, names=True)} if by_model else {},
        classified=classifier.spaces if classifier else (),
        carried=lambda item: item.space,
    )
    namers, probabilities = ranking.namers, ranking.probabilities
    known = signals.neighbours_know

    def covered_by_others(id: SpaceId) -> bool:
        by_classifier = classifier is not None and id in classifier.known_spaces
        by_neighbours = bool(ranking.neighbours) and (known is None or id in known.spaces)
        return by_classifier or by_neighbours

    def contradicted(id: SpaceId) -> bool:
        return any(other != id for other in namers)

    def sure(id: SpaceId) -> bool:
        naming = namers.get(id, ())
        sole = naming == (LLM,) and not covered_by_others(id)
        return not contradicted(id) and (len(naming) >= 2 or sole)

    ranked = ranking.candidates()
    listed = tuple(ranking.listed(ranked, contradicted))
    chosen = next((id for id in ranked if sure(id)), None)
    if chosen is None:
        top = next((id for id in ranked if id != current), None)
        return FieldCheck(  # it stays: nothing to doubt (as an unsure topic)
            field=SPACE,
            outcome=Outcome.OK,
            confidence=1.0,
            reason=_disagreeing(names[id].name for id in namers) if len(namers) > 1 else None,
            suggestion=None if top is None else str(top),
            candidates=listed,
        )
    confidence = (
        1.0
        if len(namers[chosen]) >= 2 or not probabilities
        else max(probabilities.get(chosen, 0.0), thresholds.accept)
    )
    here = names.get(current)
    target = names[chosen]
    seeing = here.members if here is not None else frozenset()
    gaining = sorted(
        (choice.people.get(user, str(user)) for user in target.members - seeing), key=sort_key
    )
    if chosen != current and gaining:
        return FieldCheck(
            field=SPACE,
            outcome=Outcome.UNCERTAIN,
            confidence=min(confidence, _UNSURE),
            reason=f"suggests the space '{target.name}', which shows it to {', '.join(gaining)}",
            suggestion=str(chosen),
            candidates=listed,
        )
    return FieldCheck(
        field=SPACE,
        outcome=Outcome.OK,
        confidence=confidence,
        value=str(chosen),
        candidates=listed,
    )


# --- helpers ----------------------------------------------------------------------------------


def _top[K](ranking: Sequence[tuple[K, float]], threshold: float) -> K | None:
    return ranking[0][0] if ranking and ranking[0][1] >= threshold else None


def _majority[K](votes: Counter[K], found: int, *, undivided: bool = False) -> K | None:
    """The value at least two and more than half of the `found` carry; `undivided`: and no
    other value two of them carry."""
    if not votes:
        return None
    (value, count), *others = votes.most_common()
    if undivided and any(other >= 2 for _, other in others):
        return None
    return value if count >= 2 and count > found / 2 else None


def _unique[K](items: Iterable[K]) -> list[K]:
    return list(dict.fromkeys(items))


def _by_name[T: (DocumentType, Tag)](items: Sequence[T], name: str) -> T | None:
    key = name_key(name)
    return next((item for item in items if name_key(item.name) == key), None)
