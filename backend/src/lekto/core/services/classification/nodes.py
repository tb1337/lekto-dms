"""The nodes that understand a document: the language model's signal, the judge and the
fields node.

A node that asks the language model checks the answer's structure and asks once more if it
does not fit; a second unfit answer fails the node (red). An unreachable model raises, so the
pipeline retries the node. Every value is then checked against facts (`FieldCheck`): the
confidence comes from what the text shows, what the master data holds and what the other
signals say, never from the model's own judgement. Values that pass are applied to the
document; uncertain ones are only proposed, and the node is uncertain (the document waits in
the inbox).
"""

import asyncio
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any
from uuid import UUID

from lekto.core.domain.classification import (
    CHECKS,
    DOCUMENT_DATE,
    TITLE,
    FieldCheck,
    checks_to_json,
    field_id_of,
    field_key,
)
from lekto.core.domain.documents import UNSET, Document, DocumentChanges, Unset
from lekto.core.domain.errors import (
    NotFoundError,
    UnprocessableDocumentError,
    ValidationError,
)
from lekto.core.domain.evidence import (
    DocumentText,
    read_amount,
    read_date,
    read_number,
    read_period,
    truth_value,
)
from lekto.core.domain.exchanges import ModelCall, tokens_of
from lekto.core.domain.facts import Strength
from lekto.core.domain.fields import (
    FieldDefinition,
    FieldType,
    FieldValue,
    Money,
    Url,
    field_from_json,
    field_to_json,
)
from lekto.core.domain.ids import ContactId, DocumentId, FieldId, SpaceId, UserId
from lekto.core.domain.json_value import JsonObject, JsonValue, as_list
from lekto.core.domain.labels import LabelCheck, LabelOutcome, check_label
from lekto.core.domain.locations import Location
from lekto.core.domain.master_data import Contact, DocumentType, Tag
from lekto.core.domain.names import match_key, mentions, named_share
from lekto.core.domain.periods import Period, PeriodKind
from lekto.core.domain.pipeline import (
    ENDPOINT,
    MODEL,
    MODEL_RUN,
    TRUNCATED,
    Node,
    NodeResult,
    NodeRun,
    Outcome,
    ProcessingHistory,
)
from lekto.core.domain.reading import (
    OcrOutput,
    PageReading,
    ReadWord,
    reading_from_json,
    surroundings,
    value_on_pages,
    value_words,
    words_at,
)
from lekto.core.domain.reasons import Reason, ReasonCode, because
from lekto.core.domain.sorting import sort_key
from lekto.core.domain.text import Shortened, shorten
from lekto.core.domain.validation import name_key
from lekto.core.domain.verdict import (
    Thresholds,
    judge_contact,
    judge_space,
    judge_tags,
    judge_topic,
    judge_type,
    named_persons,
    recipient_persons,
)
from lekto.core.ports.clock import Clock
from lekto.core.ports.llm import LanguageModel, StructuredAnswer, StructuredRequest
from lekto.core.ports.locator import TextLocator
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.unit_of_work import UnitOfWorkFactory
from lekto.core.services._spaces import SpaceCandidates, space_candidates
from lekto.core.services.classification.answers import (
    AnswerError,
    Proposal,
    StoredProposal,
    extract_schema,
    field_keys,
    parse_extract,
    parse_propose,
    propose_schema,
)
from lekto.core.services.classification.prompts import (
    EXTRACT_PROMPT,
    EXTRACT_SCHEMA,
    EXTRACT_SYSTEM,
    PROPOSE_PROMPT,
    PROPOSE_SCHEMA,
    PROPOSE_SYSTEM,
    Listed,
    extract_message,
    propose_message,
    retry_message,
)
from lekto.core.services.classification.signals import (
    ABSTAINED,
    PROPOSAL,
    abstained,
    model_proposal,
    signals_of,
)
from lekto.core.services.exchanges import keep_calls
from lekto.core.services.nodes import ARCHIVE_FILE, work_directory
from lekto.core.services.objects import (
    archive_key,
    load_layout,
    load_text,
    reading_key,
    text_key,
)
from lekto.core.services.pipeline import MetadataResult
from lekto.core.services.profiles import matching_persons
from lekto.core.services.titles import has_machine_title

log = logging.getLogger(__name__)

_RAW_LENGTH = 4000  # characters of an unfit answer kept in the log
_EARLIEST = date(1900, 1, 1)
_LATEST_AHEAD = timedelta(days=366)

NO_MODEL = "no language model is configured"
JUDGE = "judge"
"""`model_version` of the judge's entry when the language model gave nothing."""


_NO_WORDS: Mapping[int, tuple[ReadWord, ...]] = MappingProxyType({})

MAX_CONTACTS = 20
"""Contacts a prompt lists, those the text names most: enough for every sender a letter
names, few enough that the list does not crowd out the document (`architektur.md`)."""


@dataclass(frozen=True, kw_only=True)
class ClassificationPolicy:
    """`accept`: a field with at least this confidence is applied; `suggest_contact`: an
    existing contact at least this similar is suggested. Texts longer than `input_budget`
    characters are shortened; at most `max_tags` tags and `max_contacts` contacts (those the
    text names most) are listed in a prompt. `default_currency`: the currency of an amount in
    a text that shows none. `poor_reading`: the share of unsure (content) words from which a
    value's place counts as poorly read (`Surroundings.poor`, `PageReading.poor`). All but
    `max_contacts` are configuration: the composition sets them from the settings, whose
    defaults are the one source."""

    accept: float
    suggest_contact: float
    input_budget: int
    max_tags: int
    max_contacts: int = MAX_CONTACTS
    default_currency: str
    poor_reading: float


class _UnfitAnswerError(Exception):
    """The model answered twice with something that does not fit the schema."""

    def __init__(self, errors: list[str], answers: list[StructuredAnswer]) -> None:
        super().__init__(errors[-1])
        self.errors = errors
        self.answers = answers


async def _document_text(store: ObjectStore, id: DocumentId) -> str:
    return (await load_text(store, id)).decode("utf-8")


async def _locate_quotes(
    store: ObjectStore, locator: TextLocator | None, document: Document, checks: list[FieldCheck]
) -> list[FieldCheck]:
    """Each quote's page and boxes in the archive PDF. Without a locator, an archive or a
    readable PDF the checks stay as they are: the places help a person find the passage, they
    are not part of the check."""
    quotes = sorted({(check.evidence or "").strip() for check in checks} - {""})
    if locator is None or not quotes:
        return checks
    async with work_directory() as work:
        archive = work / ARCHIVE_FILE
        try:
            await store.download(archive_key(document.id), archive)
            places = await locator.locate(archive, quotes)
        except Exception as error:
            log.warning(
                "the quotes were not located: %s",
                error,
                exc_info=not isinstance(error, (NotFoundError, UnprocessableDocumentError)),
                extra={"document_id": str(document.id)},
            )
            return checks
    found = dict(zip(quotes, places, strict=True))
    return [
        replace(check, locations=found.get((check.evidence or "").strip(), ())) for check in checks
    ]


class _ModelStep:
    """A node that asks the language model (`_ask`); without one (None) the node decides what
    it does."""

    def __init__(
        self,
        uow: UnitOfWorkFactory,
        store: ObjectStore,
        model: LanguageModel | None,
        clock: Clock,
        policy: ClassificationPolicy,
    ) -> None:
        self._uow = uow
        self._store = store
        self._model = model
        self._clock = clock
        self._policy = policy

    async def _ask[T](
        self,
        document: Document,
        node: Node,
        system: str,
        message: str,
        schema: JsonObject,
        name: str,
        parse: Callable[[str], T],
    ) -> tuple[T, list[StructuredAnswer]]:
        """The parsed answer and all answers; once more after an unfit one. What was sent and
        received is kept beside the document (`exchanges_key`), also when the node fails."""
        assert self._model is not None
        answers: list[StructuredAnswer] = []
        calls: list[ModelCall] = []
        errors: list[str] = []
        user = message
        try:
            for _ in range(2):
                answer = await self._model.complete(
                    StructuredRequest(system=system, user=user, schema=schema, schema_name=name)
                )
                answers.append(answer)
                calls.append(
                    ModelCall(
                        system=system,
                        user=user,
                        answer=answer.content,
                        model=answer.model,
                        usage=answer.usage,
                    )
                )
                try:
                    return parse(answer.content), answers
                except AnswerError as error:
                    errors.append(str(error))
                    user = retry_message(message, str(error))
            raise _UnfitAnswerError(errors, answers)
        finally:
            if calls:
                await keep_calls(self._store, document, node, calls)

    def _input(self, document: Document, text: str, sent: Shortened, prompt: str) -> JsonObject:
        assert self._model is not None
        return {
            "text": text_key(document.id),
            "characters": len(text),
            "sent": len(sent.text),
            TRUNCATED: sent.omitted > 0,
            "prompt": prompt,
            MODEL: self._model.model,
            ENDPOINT: self._model.endpoint,
        }

    def _unfit(self, error: _UnfitAnswerError, input: JsonObject) -> NodeResult:
        return NodeResult(
            outcome=Outcome.FAILED,
            reason=f"the model's answer does not fit the schema: {error}",
            model_version=_model_version(error.answers[-1]),
            input=input,
            output={
                "attempts": len(error.answers),
                "errors": list(error.errors),
                "answers": [answer.content[:_RAW_LENGTH] for answer in error.answers],
            },
        )


class LlmSignal(_ModelStep):
    """The language model's proposal (`signal_llm`): one request for the sender and the
    recipient, the type, the topic (among those of the contacts listed), tags, date, a title
    and the language, the values of the fields of the type it chooses and of the global ones,
    and, with two spaces or more to choose from (`SpaceCandidates`), the space. Without a model
    it abstains; two unfit answers fail it. It checks nothing: the judge and the fields node
    do."""

    async def run(self, document: Document) -> NodeResult:
        if self._model is None:
            return abstained(NO_MODEL)
        text = await _document_text(self._store, document.id)
        async with self._uow() as uow:
            contacts = await uow.contacts.list_all()
            types = sorted(
                await uow.document_types.list_all(), key=lambda item: sort_key(item.name)
            )
            every = await uow.tags.list_all()
            # Only the tags the classification sets: document tags, not those set by hand.
            tags = sorted(
                (item for item in every if item.is_target), key=lambda item: sort_key(item.name)
            )
            topics = {item.id: item.name for item in every if item.is_topic_target}
            definitions = sorted(
                (item for item in await uow.fields.list_all() if item.is_read),
                key=lambda item: item.name,
            )
            spaces = _listed_spaces(await space_candidates(uow, document.uploaded_by))
        # Matching every name against a long text takes a while: not in the loop.
        facts = await asyncio.to_thread(DocumentText.read, text)
        listed = await asyncio.to_thread(_listed_tags, tags, facts, self._policy.max_tags)
        candidates = await asyncio.to_thread(
            _listed_contacts, contacts, facts, self._policy.max_contacts
        )
        # The topics of each contact listed: the answer names one of the sender's.
        enabled = {
            contact.id: tuple(
                sorted((topics[id] for id in contact.topic_ids if id in topics), key=sort_key)
            )
            for contact in candidates
        }
        topic_names = sorted({name for names in enabled.values() for name in names}, key=sort_key)
        keys = field_keys(definitions)
        key_of = {definition.id: key for key, definition in keys.items()}
        typed = [
            (
                Listed(kind.name, description=kind.description),
                [
                    (key_of[definition.id], definition)
                    for definition in definitions
                    if not definition.is_global and definition.applies_to(kind.id)
                ],
            )
            for kind in types
        ]
        general = [(key_of[item.id], item) for item in definitions if item.is_global]
        sent = shorten(text, self._policy.input_budget)
        input = self._input(document, text, sent, PROPOSE_PROMPT) | {
            "contacts": len(contacts),
            "contacts_listed": len(candidates),
            "document_types": len(types),
            "tags": len(tags),
            "tags_listed": len(listed),
            "topics_listed": len(topic_names),
            "fields": {key: str(definition.id) for key, definition in keys.items()},
            "spaces": {key: str(id) for key, (id, _) in spaces.items()},
        }
        tag_names = [item.name for item in listed]
        try:
            answer, answers = await self._ask(
                document,
                Node.SIGNAL_LLM,
                PROPOSE_SYSTEM,
                propose_message(
                    [
                        Listed(item.name, aliases=tuple(item.aliases), topics=enabled[item.id])
                        for item in candidates
                    ],
                    typed,
                    general,
                    tag_names,
                    sent,
                    [(key, label) for key, (_, label) in spaces.items()],
                ),
                propose_schema(
                    [item.name for item in types],
                    tag_names,
                    list(keys),
                    topic_names,
                    list(spaces),
                ),
                PROPOSE_SCHEMA,
                lambda content: parse_propose(content, list(keys), list(spaces)),
            )
        except _UnfitAnswerError as error:
            return self._unfit(error, input)
        chosen = {key: id for key, (id, _) in spaces.items()}
        return NodeResult(
            outcome=Outcome.OK,
            model_version=_model_version(answers[-1]),
            input=input,
            output=_answered(answers, answer.raw)
            | {PROPOSAL: StoredProposal.of(answer, keys, chosen).to_json()},
        )


def _listed_spaces(candidates: SpaceCandidates | None) -> dict[str, tuple[SpaceId, str]]:
    """The spaces for the prompt by key (`s1`, ...), with their labels: the uploader's own
    personal space first (with what the uploader wrote about it), then the shared ones with
    their descriptions, then the personal spaces of the other users by their user only (what
    they wrote is theirs). None with fewer than two: nothing to choose."""
    if candidates is None or len(candidates.spaces) < 2:
        return {}
    own = candidates.personal
    shared = sorted(
        (space for space in candidates.spaces.values() if space.personal_of is None),
        key=lambda space: sort_key(space.name),
    )
    others = sorted(
        (
            space
            for space in candidates.spaces.values()
            if space.personal_of is not None and space.id != own
        ),
        key=lambda space: sort_key(candidates.label(space.id)),
    )
    described = candidates.spaces[own].description if own in candidates.spaces else None
    labels = [(own, "own personal space of the uploader" + (f": {described}" if described else ""))]
    labels += [
        (space.id, space.name + (f": {space.description}" if space.description else ""))
        for space in shared
    ]
    labels += [(space.id, candidates.label(space.id)) for space in others]
    return {f"s{number}": item for number, item in enumerate(labels, start=1)}


class JudgeNode:
    """The judge (`judge`): contact, document type, topic and tags from the signals' proposals
    by the rules of `domain.verdict`, and the document date the model read, checked against the
    text. What is green is applied; tags are added. A document the model answered for, but no
    signal recognised anything in, fails (red); without the model's proposal the judge is
    uncertain. With two spaces or more to choose from (`SpaceCandidates`) it judges the space
    too (`judge_space`): a space that shows the document to no one new and keeps it with its
    uploader it moves it to; one that shows it to others, one its uploader would not see and
    another user's personal space (a hand-over) it suggests (uncertain)."""

    def __init__(
        self,
        uow: UnitOfWorkFactory,
        store: ObjectStore,
        clock: Clock,
        policy: ClassificationPolicy,
        *,
        thresholds: Thresholds,
        locator: TextLocator | None = None,
    ) -> None:
        """`thresholds`: those of the judge, from the same settings as `policy`; `locator`:
        find each quote on the pages of the archive PDF (`FieldCheck.locations`)."""
        self._uow = uow
        self._store = store
        self._clock = clock
        self._policy = policy
        self._thresholds = thresholds
        self._locator = locator

    async def run(self, document: Document) -> NodeResult | MetadataResult:
        async with self._uow() as uow:
            log = await uow.processing_log.list_for(document.id)
            contacts = await uow.contacts.list_all()
            types = await uow.document_types.list_all()
            tags = await uow.tags.list_all()
            candidates = await space_candidates(uow, document.uploaded_by)
            current = await uow.spaces.find(document.space_id)
            matched = await matching_persons(uow) if candidates is not None else []
        people = [(person.user_id, person.names) for person in matched]
        # By display name alone: whom the recipient names by what anyone may know.
        shown = [
            (person.user_id, (person.display_name,)) for person in matched if person.display_name
        ]
        entries = ProcessingHistory(log).signals()
        signals = signals_of(entries)
        proposal = model_proposal(entries)
        text = await _document_text(self._store, document.id)
        facts = await asyncio.to_thread(DocumentText.read, text)
        if proposal is None:
            silent = entries.get(Node.SIGNAL_LLM)
            why = (
                str(silent.result.output.get(ABSTAINED, "it did not run"))
                if silent is not None
                else "it did not run"
            )
            date_check = FieldCheck(
                field=DOCUMENT_DATE,
                outcome=Outcome.UNCERTAIN,
                confidence=0,
                reasons=(because(ReasonCode.DATE_NONE_FROM_MODEL, detail=why),),
            )
        else:
            date_check = _check_date(
                DOCUMENT_DATE,
                proposal.document_date,
                facts,
                self._today(),
                document.created_at.date(),
            )
        contact = judge_contact(signals, contacts, self._thresholds)
        kind = judge_type(signals, types, self._thresholds)
        topic = judge_topic(signals, contact, contacts, tags, self._thresholds)
        tagged = judge_tags(signals, tags, self._thresholds)
        # The persons the document names: the facts' and the model's recipient (only names
        # are matched here; the facts matched the rest of the profiles).
        recipient = signals.model.recipient if signals.model is not None else None
        active = {person.user_id for person in matched}
        persons = named_persons(
            {  # facts of an earlier run may name a user deactivated since
                user: strength
                for user, strength in (signals.facts.persons if signals.facts else {}).items()
                if user in active
            },
            recipient_persons(recipient, people, self._thresholds),
        )
        addressed = recipient_persons(recipient, shown, self._thresholds)
        public = named_persons(
            {user: Strength.WEAK for user in (signals.facts.public if signals.facts else ())},
            addressed,
        )
        space = (
            None
            if candidates is None or current is None or len(candidates.spaces) < 2
            else judge_space(
                signals,
                candidates.choice(current, locked=document.space_confirmed_at is not None),
                self._thresholds,
                persons,
                frozenset(user for user in addressed if user in active),
            )
        )
        model_entry = entries.get(Node.SIGNAL_LLM)
        llm_input = model_entry.result.input if model_entry is not None else {}
        input: JsonObject = {key: llm_input[key] for key in MODEL_RUN if key in llm_input}
        input["signals"] = {
            node.value: (
                "abstained" if ABSTAINED in entry.result.output else entry.result.model_version
            )
            for node, entry in sorted(entries.items())
        }
        model_version = (
            model_entry.result.model_version
            if model_entry is not None and proposal is not None
            else JUDGE
        )
        recognised = contact.candidates or kind.candidates or date_check.value
        if proposal is not None and not (recognised or date_check.suggestion):
            # The model answered, and no signal recognised anything: as before the signals.
            # Without its proposal the judge is uncertain, and a person classifies.
            return NodeResult(
                outcome=Outcome.FAILED,
                reason="nothing recognised: no contact, document type or date",
                model_version=model_version,
                input=input,
                output={CHECKS: checks_to_json([contact, kind, topic, tagged, date_check])},
            )
        contact, kind, topic, tagged, date_check = await _locate_quotes(
            self._store, self._locator, document, [contact, kind, topic, tagged, date_check]
        )
        reading = await _ocr_reading(self._store, document, log, [date_check])
        date_check = _readable(
            date_check, reading, self._policy.poor_reading, _date_shown(date_check.value)
        )
        checks = [contact, kind, topic, tagged, date_check, *([space] if space else [])]
        # A topic set is one of the contact's; a contact set that does not enable the
        # document's topic clears it (`checked_changes`).
        changes = DocumentChanges(
            contact_id=_applied(contact, lambda value: ContactId(UUID(value))),
            document_type_id=_applied(kind, lambda value: _by_id(types, value).id),
            topic_id=_applied(topic, lambda value: _by_id(tags, value).id),
            document_date=_applied(date_check, date.fromisoformat),
        )
        # Tags are added: those the document has (set by its owner) stay.
        add_tags = frozenset(_by_id(tags, value).id for value in as_list(tagged.value))
        uncertain = [check for check in checks if not check.ok]
        output: JsonObject = {CHECKS: checks_to_json(checks)}
        if space is not None and persons:
            output[PERSONS] = _persons_json(persons, public)
        result = NodeResult(
            outcome=Outcome.UNCERTAIN if uncertain else Outcome.OK,
            reason="; ".join(_reason(check) for check in uncertain) or None,
            confidence=min(check.confidence for check in checks),
            model_version=model_version,
            input=input,
            output=output,
        )
        moved = _applied(space, lambda value: SpaceId(UUID(value))) if space else UNSET
        target = None if isinstance(moved, Unset) or moved == document.space_id else moved
        return MetadataResult(result, changes, add_tags, space=target)

    def _today(self) -> date:
        return self._clock.now().date()


PERSONS = "persons"


def _persons_json(
    persons: Mapping[UserId, Strength], public: Mapping[UserId, Strength]
) -> JsonValue:
    """The persons the judge weighed for the space, by id with the strength of the evidence
    (ids only, as the facts keep them), and `public` the strength of the evidence anyone may
    know (their display name in the text or as the recipient): the log shows another user
    only by that (`_access.readable_log`)."""
    return [
        {
            "user_id": str(user),
            "strength": strength.value,
            **({"public": public[user].value} if user in public else {}),
        }
        for user, strength in sorted(
            persons.items(), key=lambda item: (-item[1].rank, str(item[0]))
        )
    ]


class FieldsNode(_ModelStep):
    """The fields that apply to the document (those of its type and the global ones) and its
    title.

    The language model's signal gave the values of the global fields and of the fields of the
    type it chose; if the judge decided on that type, they are taken over, else (or for a
    document from before the signals) the fields it did not give are asked for. A required
    field the document does not show is uncertain, an optional one stays empty; a value given
    must pass its check either way. Without a model nothing reads the missing ones: the same
    holds, the required ones say why. A field set by hand is never asked for and keeps its
    value (the rules node checks that a required one has one).

    The title comes from the type's title pattern, or from the model's proposal, as long as
    the document's title is still the file name or the one set here before."""

    def __init__(
        self,
        uow: UnitOfWorkFactory,
        store: ObjectStore,
        model: LanguageModel | None,
        clock: Clock,
        policy: ClassificationPolicy,
        *,
        locator: TextLocator | None = None,
    ) -> None:
        """`locator`: find each quote on the pages of the archive PDF (`FieldCheck.locations`)."""
        super().__init__(uow, store, model, clock, policy)
        self._locator = locator

    async def run(self, document: Document) -> NodeResult | MetadataResult:
        async with self._uow() as uow:
            log = await uow.processing_log.list_for(document.id)
            definitions = sorted(
                (
                    item
                    for item in await uow.fields.list_all()
                    if item.applies_to(document.document_type_id)
                ),
                key=lambda item: item.name,
            )
            document_type = (
                None
                if document.document_type_id is None
                else await uow.document_types.find(document.document_type_id)
            )
        entries = ProcessingHistory(log).signals()
        proposal = model_proposal(entries)
        given: dict[FieldId, Proposal] = {}
        if proposal is not None:
            same_type = document_type is not None and _same_name(
                proposal.document_type, document_type.name
            )
            for definition in definitions:
                if definition.is_read and (definition.is_global or same_type):
                    given[definition.id] = proposal.fields.get(
                        definition.id, Proposal(value=None, evidence=None)
                    )
        missing = [item for item in definitions if item.is_read and item.id not in given]
        answers: list[StructuredAnswer] = []
        text = (
            await _document_text(self._store, document.id)
            if any(item.is_read for item in definitions)
            else ""
        )
        taken_over = len(given)
        input: JsonObject = {"taken_over": taken_over}
        unread: set[FieldId] = set()
        if missing and self._model is None:
            # Nothing read them: an optional field stays empty, a required one is open.
            unread = {item.id for item in missing}
            given |= {item.id: Proposal(value=None, evidence=None) for item in missing}
        elif missing:
            keys = field_keys(missing)
            sent = shorten(text, self._policy.input_budget)
            input |= self._input(document, text, sent, EXTRACT_PROMPT) | {
                "fields": {key: str(definition.id) for key, definition in keys.items()},
            }
            try:
                proposals, answers = await self._ask(
                    document,
                    Node.FIELDS,
                    EXTRACT_SYSTEM,
                    extract_message(
                        None if document_type is None else document_type.name, keys, sent
                    ),
                    extract_schema(keys),
                    EXTRACT_SCHEMA,
                    lambda content: parse_extract(content, list(keys)),
                )
            except _UnfitAnswerError as error:
                return self._unfit(error, input)
            given |= {keys[key].id: value for key, value in proposals.items()}
        facts = await asyncio.to_thread(DocumentText.read, text)
        language = _text_value(proposal.language) if proposal else None
        checks = [
            _check_field(
                definition,
                given[definition.id],
                facts,
                self._clock.now().date(),
                document.document_date,
                required=definition.is_required_for(document.document_type_id),
                language=language,
                default_currency=self._policy.default_currency,
                received=document.created_at.date(),
            )
            if definition.is_read
            else _set_by_hand(definition)
            for definition in definitions
        ]
        checks = [
            replace(
                check,
                reasons=(because(ReasonCode.FIELD_NOT_READ_NO_MODEL, field=definition.name),),
            )
            if definition.id in unread and not check.ok
            else check
            for check, definition in zip(checks, definitions, strict=True)
        ]
        checks = await _locate_quotes(self._store, self._locator, document, checks)
        reading = await _ocr_reading(self._store, document, log, checks)
        checks = [
            _readable(
                check,
                reading,
                self._policy.poor_reading,
                _field_shown(definition, check.value),
                definition.name,
            )
            if definition.data_type in _LITERAL
            else check
            for check, definition in zip(checks, definitions, strict=True)
        ]
        checks = await _labelled(self._store, document, checks, definitions, given)
        values: dict[FieldId, object] = {}
        for check, definition in zip(checks, definitions, strict=True):
            if check.ok and check.value is not None:
                values[definition.id] = field_from_json(definition, check.value)
        title = _title(document, proposal, log)
        changes = DocumentChanges(fields=values)
        if title is not None and title.value is not None:
            changes = replace(changes, title=str(title.value))
        raw: JsonObject = {str(id): value.to_json() for id, value in given.items()}
        all_checks = [*checks, *([title] if title is not None else [])]
        model_version = (
            _model_version(answers[-1])
            if answers
            else (entries[Node.SIGNAL_LLM].result.model_version if taken_over else None)
        )
        uncertain = [check for check in checks if not check.ok]
        result = NodeResult(
            outcome=Outcome.UNCERTAIN if uncertain else Outcome.OK,
            reason="; ".join(_reason(check) for check in uncertain) or None,
            confidence=min((check.confidence for check in checks), default=1.0),
            model_version=model_version,
            input=input,
            output=_answered(answers, {"fields": raw}) | {CHECKS: checks_to_json(all_checks)},
        )
        return MetadataResult(result, changes)


def _title(
    document: Document, proposal: StoredProposal | None, log: Sequence[NodeRun]
) -> FieldCheck | None:
    """The title check: the model's title; None if the document has a title of its own (a
    person's or a rule's), or the model gave none. A type's title pattern is a rule
    (`rules.title_rule`): it replaces this title when the rules run."""
    if not has_machine_title(document, log):
        return None
    proposed = _text_value(proposal.title) if proposal else None
    if not proposed:
        return None
    return FieldCheck(
        field=TITLE, outcome=Outcome.OK, confidence=1, proposed=proposed, value=proposed
    )


def _text_value(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _same_name(proposed: str | None, name: str) -> bool:
    return proposed is not None and name_key(proposed) == name_key(name)


# --- checks -----------------------------------------------------------------------------------


def _check_date(
    field: str, proposal: Proposal, facts: DocumentText, today: date, received: date | None
) -> FieldCheck:
    """A date as the model gives it; `received`, the day the document came in, picks the
    reading of a two-digit year the text does not decide (`read_date`)."""
    common = _common(field, proposal)
    if proposal.value is None:
        return FieldCheck(
            outcome=Outcome.UNCERTAIN,
            confidence=0,
            reasons=(because(ReasonCode.DATE_NONE),),
            **common,
        )
    value = (
        read_date(proposal.value, facts, received=received)
        if isinstance(proposal.value, str)
        else None
    )
    if value is None:
        return FieldCheck(
            outcome=Outcome.UNCERTAIN,
            confidence=0,
            reasons=(because(ReasonCode.NOT_A_DATE, value=_raw(proposal.value)),),
            **common,
        )
    common["quote_shows_value"] = _quoted(proposal, lambda quote: quote.has_date(value))
    if not _EARLIEST <= value <= today + _LATEST_AHEAD:
        return FieldCheck(
            outcome=Outcome.UNCERTAIN,
            confidence=0,
            reasons=(because(ReasonCode.DATE_IMPLAUSIBLE, date=value.isoformat()),),
            **common,
        )
    return _verified(
        common,
        value.isoformat(),
        proposal,
        facts,
        facts.has_date(value),
        because(ReasonCode.DATE_NOT_IN_TEXT),
        literal=True,
    )


def _set_by_hand(definition: FieldDefinition) -> FieldCheck:
    """A field set by hand is never read: its value stays as the document has it. Whether a
    required one has a value is checked after the rules, which may set it (`ApplyRulesNode`)."""
    return FieldCheck(
        field=field_key(definition.id),
        outcome=Outcome.OK,
        confidence=1,
        reasons=(because(ReasonCode.FIELD_SET_BY_HAND, field=definition.name),),
    )


def _check_field(
    definition: FieldDefinition,
    proposal: Proposal,
    facts: DocumentText,
    today: date,
    document_date: date | None,
    *,
    required: bool,
    language: str | None = None,
    default_currency: str | None = None,
    received: date | None = None,
) -> FieldCheck:
    """A required field must be found, an optional one may stay empty; a value given must
    pass the checks either way. A date equal to the document date is only suggested: models
    put the document date into date fields the text does not show (a due date "within 30
    days")."""
    field = field_key(definition.id)
    common = _common(field, proposal)
    if proposal.value is None:
        if not required:
            return FieldCheck(outcome=Outcome.OK, confidence=1, **common)
        return FieldCheck(
            outcome=Outcome.UNCERTAIN,
            confidence=0,
            reasons=(because(ReasonCode.FIELD_NOT_FOUND, field=definition.name),),
            **common,
        )
    if definition.data_type is FieldType.PERIOD:
        return _check_period(definition, proposal, facts, today, document_date, received)
    if definition.data_type is FieldType.DATE:
        check = _check_date(field, proposal, facts, today, received)
        if check.ok and document_date is not None and check.value == document_date.isoformat():
            check = replace(
                check,
                outcome=Outcome.UNCERTAIN,
                confidence=0,
                reasons=(because(ReasonCode.SAME_AS_DOCUMENT_DATE),),
                suggestion=check.value,
                value=None,
            )
        if check.ok:
            return check
        return FieldCheck(
            outcome=Outcome.UNCERTAIN,
            confidence=check.confidence,
            reasons=_about(check.reasons, definition.name),
            suggestion=check.suggestion,
            quote_shows_value=check.quote_shows_value,
            **common,
        )
    try:
        value = _parse_value(
            definition, proposal.value, facts, language, default_currency, received
        )
    except ValidationError:
        invalid = because(
            ReasonCode.VALUE_INVALID,
            value=_raw(proposal.value),
            field=definition.name,
            type=definition.data_type.value,
        )
        return FieldCheck(outcome=Outcome.UNCERTAIN, confidence=0, reasons=(invalid,), **common)
    common["quote_shows_value"] = _quoted(proposal, lambda quote: _literally(value, quote))
    shown, unshown = _shown(definition, value, proposal, facts, default_currency)
    literal = definition.data_type in _LITERAL
    check = _verified(
        common, field_to_json(value), proposal, facts, shown, unshown, literal=literal
    )
    if check.ok:
        return check
    return FieldCheck(
        outcome=Outcome.UNCERTAIN,
        confidence=check.confidence,
        reasons=_about(check.reasons, definition.name),
        suggestion=check.suggestion,
        **common,
    )


_SHORTEST_EVIDENCE = 4  # characters of a quoted passage that alone backs a yes/no or choice
# Values written as such: their quoted passage must show them (`_verified`), and a poorly
# read place does not back them (`_readable`).
_LITERAL = frozenset(
    {
        FieldType.TEXT,
        FieldType.NUMBER,
        FieldType.AMOUNT,
        FieldType.DATE,
        FieldType.LINK,
        FieldType.PERIOD,
    }
)


def _check_period(
    definition: FieldDefinition,
    proposal: Proposal,
    facts: DocumentText,
    today: date,
    document_date: date | None,
    received: date | None = None,
) -> FieldCheck:
    """A period as the model gives it: `{start, end}` (extract-5) or as written (propose-4:
    `September 2026`, `KW 38/2026`, `01.09.-30.09.2026`). Its quoted passage must show it. One
    without a year takes that of the document date and is only suggested, as is a single day
    equal to the document date (models put the document date where the text shows none)."""
    common = _common(field_key(definition.id), proposal)
    read = _read_period(proposal.value, document_date, received)
    if read is None:
        not_a_period = because(ReasonCode.NOT_A_PERIOD, value=_raw(proposal.value))
        return FieldCheck(
            outcome=Outcome.UNCERTAIN,
            confidence=0,
            reasons=(not_a_period.about(definition.name),),
            **common,
        )
    period, yearless = read
    evidence = (proposal.evidence or "").strip()
    shows: bool | None = None
    if evidence:
        quote = DocumentText(evidence)
        shows = quote.has_period(period)
        if not shows and document_date is not None and quote.has_period(period, document_date):
            shows, yearless = True, True
    common["quote_shows_value"] = shows
    if not (period.start >= _EARLIEST and period.end <= today + _LATEST_AHEAD):
        implausible = because(ReasonCode.PERIOD_IMPLAUSIBLE, period=str(period))
        return FieldCheck(
            outcome=Outcome.UNCERTAIN,
            confidence=0,
            reasons=(implausible.about(definition.name),),
            **common,
        )
    in_text = facts.has_period(period, document_date if yearless else None)
    check = _verified(
        common,
        field_to_json(period),
        proposal,
        facts,
        in_text,
        because(ReasonCode.PERIOD_NOT_IN_TEXT),
        literal=True,
    )
    if check.ok and yearless:
        reasons: tuple[Reason, ...] = (because(ReasonCode.PERIOD_NO_YEAR),)
    elif check.ok and period.kind is PeriodKind.DAY and period.start == document_date:
        reasons = (because(ReasonCode.SAME_DAY_AS_DOCUMENT_DATE),)
    elif check.ok:
        return check
    else:
        reasons = check.reasons
    return replace(
        check,
        outcome=Outcome.UNCERTAIN,
        confidence=0,
        reasons=_about(reasons, definition.name),
        suggestion=check.value if check.ok else check.suggestion,
        value=None,
    )


def _read_period(
    raw: JsonValue, document_date: date | None, received: date | None = None
) -> tuple[Period, bool] | None:
    """The period of a proposed value, and whether its year was assumed."""
    if isinstance(raw, dict) and set(raw) == {"start", "end"}:
        start, end = (
            read_date(day, received=received) if isinstance(day, str) else None
            for day in (raw["start"], raw["end"])
        )
        if start is None or end is None or end < start:
            return None
        return Period(start, end), False
    return read_period(raw, document_date, received=received) if isinstance(raw, str) else None


def _shown(
    definition: FieldDefinition,
    value: FieldValue,
    proposal: Proposal,
    facts: DocumentText,
    default_currency: str | None,
) -> tuple[bool, Reason]:
    """Whether the text shows the value, and why not if it does not. Yes/no and choice values
    are not written as such; for them a quoted passage of some length must be in the text. An
    amount in a text that shows no currency at all (a pay slip's bare numbers) is in the
    default currency."""
    match value:
        case Money():
            if not facts.has_number(value.amount):
                return False, because(ReasonCode.AMOUNT_NOT_IN_TEXT)
            currency = because(ReasonCode.CURRENCY_NOT_IN_TEXT, currency=value.currency)
            if not facts.currencies and default_currency is not None:
                return value.currency == default_currency, currency
            return facts.has_currency(value.currency), currency
        case Decimal():
            return facts.has_number(value), because(ReasonCode.NUMBER_NOT_IN_TEXT)
        case Url():
            return facts.contains(value.value), because(ReasonCode.LINK_NOT_IN_TEXT)
        case str() if definition.data_type is FieldType.TEXT:
            return facts.contains(value), because(ReasonCode.TEXT_NOT_IN_TEXT)
        case _:
            evidence = (proposal.evidence or "").strip()
            short = because(ReasonCode.QUOTE_TOO_SHORT if evidence else ReasonCode.QUOTE_MISSING)
            return len(evidence) >= _SHORTEST_EVIDENCE, short


def _quoted(proposal: Proposal, shows: Callable[[DocumentText], bool]) -> bool | None:
    """Whether the quoted passage itself shows the value; None without a quote."""
    evidence = (proposal.evidence or "").strip()
    return shows(DocumentText(evidence)) if evidence else None


def _literally(value: FieldValue, quote: DocumentText) -> bool:
    """Whether `quote` shows the value itself, not only what it follows from: a yes or no is
    never written as such."""
    match value:
        case Money():
            return quote.has_amount(value.amount)
        case Decimal():
            return quote.has_number(value)
        case Url():
            return quote.contains(value.value)
        case str():
            return quote.contains(value)
        case _:
            return False


@dataclass(frozen=True)
class _Reading:
    """How the OCR read the pages (`pages`), and the words Tesseract read on them by page
    (`words`; none for pages the vision language model read, or read before words were kept)."""

    pages: tuple[PageReading, ...] = ()
    words: Mapping[int, tuple[ReadWord, ...]] = _NO_WORDS


async def _ocr_reading(
    store: ObjectStore,
    document: Document,
    history: Sequence[NodeRun],
    checks: Sequence[FieldCheck],
) -> _Reading:
    """How the OCR read the pages, by its latest entry that made a text (as
    `PipelineService.reading` tells it); nothing for a document recognised before readings, or
    with text of its own. The words it kept beside the archive only where one of `checks`
    passed: no other check looks at them."""
    entry = ProcessingHistory(history).latest(Node.OCR, made=True)
    pages = () if entry is None else OcrOutput.from_json(entry.result.output).readings
    if not pages or not any(check.ok and check.value is not None for check in checks):
        return _Reading(pages)
    key = reading_key(document.id)
    try:
        data = await store.get(key)
        words = await asyncio.to_thread(lambda: reading_from_json(json.loads(data)))
    except NotFoundError:
        words = None
    except (ValueError, ValidationError):
        log.warning("the words of the reading cannot be read", extra={"key": key})
        words = None
    return _Reading(pages, words or _NO_WORDS)


def _date_shown(value: JsonValue) -> Callable[[DocumentText], bool] | None:
    """How a quote shows a checked date (ISO), as the quote check reads it."""
    if not isinstance(value, str):
        return None
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return None
    return lambda text: text.has_date(day)


def _field_shown(
    definition: FieldDefinition, value: JsonValue
) -> Callable[[DocumentText], bool] | None:
    """How a quote shows a checked value of `definition`, as the quote check reads it."""
    try:
        parsed = field_from_json(definition, value)
    except ValidationError:
        return None
    match parsed:
        case Period():
            period = parsed
            return lambda text: text.has_period(period)
        case date():
            day = parsed
            return lambda text: text.has_date(day)
        case _:
            return lambda text: _literally(parsed, text)


def _readable(
    check: FieldCheck,
    reading: _Reading,
    threshold: float,
    shows: Callable[[DocumentText], bool] | None,
    name: str | None = None,
) -> FieldCheck:
    """A checked value is only suggested where it was not read sure: in a poorly read place
    (counting content only), as on a broken scan a number may be anything, however sure the
    engine was of it; or where a word of the value itself was read unsure. The value's words
    are those in its quote's boxes that show it (`shows`); its place, the content words around
    them (`surroundings`). A quote without a place (its words not one run on the page, or put
    together by the model) leaves the value itself to be found among the words of the pages
    (`value_on_pages`), where it stands just once. Where the value's words are not found (no
    words kept, a value not written as such, or not just once), or too few words stand around
    them, the place is the page of the quote, or any recognised page if the quote was not found
    on one."""
    if not check.ok or check.value is None:
        return check
    places: list[_Place] = []
    for location in check.locations:
        words = reading.words.get(location.page, ())
        found = None if shows is None else value_words(words_at(location, words), shows)
        places.append((location, words, found))
    if not places and shows is not None and (alone := value_on_pages(reading.words, shows)):
        page, value = alone
        boxes = tuple(word.box for word in value if word.box is not None)
        if boxes:
            places.append((Location(page, boxes), reading.words[page], value))
    reason = _poorly_read(places, reading.pages, threshold)
    if reason is None:
        unsure = [word.confidence for *_, value in places for word in value or () if word.unsure]
        if not unsure:
            return check
        reason = because(ReasonCode.VALUE_READ_UNSURE, unsure=min(unsure))
    return replace(
        check,
        outcome=Outcome.UNCERTAIN,
        confidence=0,
        reasons=(reason if name is None else reason.about(name),),
        suggestion=check.value,
        value=None,
    )


_LABELLED = frozenset({FieldType.AMOUNT, FieldType.NUMBER, FieldType.DATE, FieldType.PERIOD})
"""The types whose label is checked (issue #55): values a pay slip or a form lists among others
of their kind, where the quote of the wrong line passes every other check."""


async def _labelled(
    store: ObjectStore,
    document: Document,
    checks: Sequence[FieldCheck],
    definitions: Sequence[FieldDefinition],
    given: Mapping[FieldId, Proposal],
) -> list[FieldCheck]:
    """Each check of a field the model gave a value for, with its label check (`check_label`):
    recorded only, it changes no outcome (issue #55, step 1). The value is the checked one, or
    else the suggestion; a type other than `_LABELLED` is not checked (unknown). The words of
    the parsed text are loaded only where a field of such a type has a label."""
    read = [
        definition.id in given and given[definition.id].value is not None
        for definition in definitions
    ]
    if not any(read):
        return list(checks)
    wanted = any(
        asked and definition.data_type in _LABELLED and given[definition.id].label is not None
        for asked, definition in zip(read, definitions, strict=True)
    )
    pages = await load_layout(store, document.id) if wanted else {}

    def label(check: FieldCheck, definition: FieldDefinition) -> LabelCheck:
        text = given[definition.id].label
        if definition.data_type not in _LABELLED:
            return LabelCheck(text, LabelOutcome.UNKNOWN)
        value = check.value if check.value is not None else check.suggestion
        shows = None if value is None else _field_shown(definition, value)
        return check_label(text, pages, check.locations, shows)

    def all_labelled() -> list[FieldCheck]:
        return [
            replace(check, label=label(check, definition)) if asked else check
            for check, definition, asked in zip(checks, definitions, read, strict=True)
        ]

    try:
        return await asyncio.to_thread(all_labelled)
    except Exception:  # recorded only: a failure of the check must not fail the node
        log.warning(
            "the labels were not checked", exc_info=True, extra={"document_id": str(document.id)}
        )
        return list(checks)


type _Place = tuple[Location, Sequence[ReadWord], tuple[ReadWord, ...] | None]
"""A place of a quote, the words Tesseract read on its page and those of the value there (None
where they are not found)."""


def _poorly_read(
    places: Sequence[_Place], pages: Sequence[PageReading], threshold: float
) -> Reason | None:
    """Why a value stands in a poorly read place, at any of its quote's places; None if it
    does not. A place is the content around the value's words there, or, without them or with
    too few words around, the page; without places, any recognised page. A page whose
    surroundings were judged at one place is not judged as a whole for another place on it
    where the value's words were not found: the boxes of the text layer and Tesseract's differ
    at a line's edge, and the whole page would undo its surroundings."""
    if not places:
        poor = next((page for page in pages if page.poor(threshold)), None)
        return None if poor is None else poor.describe()
    judged: set[int] = set()
    for location, words, value in places:
        around = None if value is None else surroundings(words, value)
        if around is not None:
            if around.poor():
                return around.describe()
            judged.add(location.page)
    for location, _, _ in places:
        if location.page in judged:
            continue
        poor = next(
            (page for page in pages if page.page == location.page and page.poor(threshold)), None
        )
        if poor is not None:
            return poor.describe()
    return None


def _about(reasons: Sequence[Reason], name: str) -> tuple[Reason, ...]:
    """`reasons` about the custom field `name` (`Reason.subject`)."""
    return tuple(reason.about(name) for reason in reasons)


def _raw(value: JsonValue) -> JsonValue:
    """A value as the model gave it, for a reason: text as it is, anything else as JSON text."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _common(field: str, proposal: Proposal) -> dict[str, Any]:
    return {"field": field, "proposed": proposal.value, "evidence": proposal.evidence}


def _verified(
    common: dict[str, Any],
    value: JsonValue,
    proposal: Proposal,
    facts: DocumentText,
    shown: bool,
    unshown: Reason,
    *,
    literal: bool,
) -> FieldCheck:
    """The check of a value read from the text: the quoted passage must appear in it, and the
    text must show the value (`shown`; why not: `unshown`). A `literal` value (an amount,
    number, date, text or link) also needs a quoted passage that shows it: elsewhere in the
    text the same digits may stand for anything, on a broken scan a lone fragment (`620` for
    620,00 €)."""
    if proposal.evidence is not None and not facts.contains(proposal.evidence):
        reason = because(ReasonCode.QUOTE_NOT_IN_TEXT)
    elif literal and common["quote_shows_value"] is None:
        reason = because(ReasonCode.QUOTE_MISSING)
    elif literal and not common["quote_shows_value"]:
        reason = because(ReasonCode.QUOTE_WITHOUT_VALUE)
    elif not shown:
        reason = unshown
    else:
        return FieldCheck(outcome=Outcome.OK, confidence=1, value=value, **common)
    return FieldCheck(
        outcome=Outcome.UNCERTAIN,
        confidence=0,
        reasons=(reason,),
        suggestion=value,
        **common,
    )


# --- values -----------------------------------------------------------------------------------


def _parse_value(
    definition: FieldDefinition,
    raw: JsonValue,
    facts: DocumentText,
    language: str | None,
    default_currency: str | None = None,
    received: date | None = None,
) -> FieldValue:
    """A proposed value read leniently, as a person writes it (`2.111,68 €`, `12.03.2026`,
    `ja`; an ambiguous number the way the text shows it, else as the document's `language`
    writes it), then checked against the definition. ValidationError if it does not fit."""
    value: object = raw
    match definition.data_type:
        case FieldType.NUMBER:
            value = _number(raw, facts, language)
        case FieldType.AMOUNT if isinstance(raw, dict):
            number, currency = _number(raw.get("amount"), facts, language), raw.get("currency")
            if number is not None:
                code = currency.strip().upper() if isinstance(currency, str) else ""
                value = Money(number, code)
        case FieldType.AMOUNT if isinstance(raw, str):
            amount = read_amount(raw, facts, language=language, default=default_currency)
            value = None if amount is None else Money(*amount)
        case FieldType.DATE if isinstance(raw, str):
            value = read_date(raw, facts, received=received)
        case FieldType.BOOLEAN if isinstance(raw, str):
            truth = truth_value(raw)
            value = raw if truth is None else truth
        case FieldType.LINK if isinstance(raw, str):
            value = Url(raw.strip())
        case FieldType.TEXT | FieldType.CHOICE if isinstance(raw, str):
            value = raw.strip()
    return definition.validate(value)


def _number(raw: JsonValue, facts: DocumentText, language: str | None) -> Decimal | None:
    """A number given as JSON number or as written."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        number = Decimal(str(raw))
        return number if number.is_finite() else None
    return read_number(raw, facts, language=language) if isinstance(raw, str) else None


# --- helpers ----------------------------------------------------------------------------------


def _listed_tags(tags: Sequence[Tag], facts: DocumentText, limit: int) -> list[Tag]:
    """All tags if they fit the limit; otherwise first those named in the text."""
    if len(tags) <= limit:
        return list(tags)
    text_key = match_key(facts.raw)
    named = [tag for tag in tags if mentions(text_key, match_key(tag.name))]
    rest = [tag for tag in tags if tag not in named]
    return sorted((named + rest)[:limit], key=lambda tag: sort_key(tag.name))


def _listed_contacts(contacts: Sequence[Contact], facts: DocumentText, limit: int) -> list[Contact]:
    """The contacts whose names or aliases the text shows most (see `named_share`), at most
    `limit`; none the text does not show at all."""
    text_key = match_key(facts.raw)
    words = frozenset(text_key.split())
    scored = [
        (max(named_share(text_key, words, match_key(own)) for own in contact.names()), contact)
        for contact in contacts
    ]
    ranked = sorted(
        ((score, contact) for score, contact in scored if score > 0),
        key=lambda entry: (-entry[0], sort_key(entry[1].name)),
    )
    return [contact for _, contact in ranked[:limit]]


def _by_id[T: Contact | DocumentType | Tag](items: Sequence[T], id: JsonValue) -> T:
    return next(item for item in items if str(item.id) == id)


def _applied[T](check: FieldCheck, convert: Callable[[str], T]) -> T | Unset:
    if check.ok and isinstance(check.value, str):
        return convert(check.value)
    return UNSET


def _model_version(answer: StructuredAnswer) -> str:
    return f"{answer.model} ({answer.fingerprint})" if answer.fingerprint else answer.model


def _answered(answers: Sequence[StructuredAnswer], answer: JsonValue) -> JsonObject:
    """The output of a model node that got its answer: how many requests it took, the answer
    and the tokens of each request."""
    return {
        "attempts": len(answers),
        "answer": answer,
        "tokens": tokens_of(item.usage for item in answers),
    }


def _reason(check: FieldCheck) -> str:
    """Reasons of field checks name the field already."""
    if field_id_of(check.field) is not None:
        return str(check.reason)
    return f"{check.field}: {check.reason}"
