"""What every rule run needs: the rules that apply to a document, its text and pattern results,
where its values came from (model, person), and the facts about spaces and master data.

Loading the text and running the regular expressions on it happens before the unit of work that
stores the result (`prepare`), so no transaction waits for a slow pattern. Patterns on field
values (short) run inside it, on the state that is stored.
"""

import logging
import time
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from uuid import UUID

from lekto.core.domain.classification import (
    CHANGE_FIELDS,
    CONTACT,
    DOCUMENT_DATE,
    DOCUMENT_TYPE,
    SPACE,
    TAGS,
    TITLE,
    TOPIC,
    field_key,
)
from lekto.core.domain.documents import Document
from lekto.core.domain.errors import NotFoundError, PatternTimeoutError, ValidationError
from lekto.core.domain.evidence import DocumentText
from lekto.core.domain.fields import FieldDefinition, field_to_json
from lekto.core.domain.ids import (
    ContactId,
    DocumentTypeId,
    FieldId,
    RuleId,
    SpaceId,
    TagId,
    UserId,
    WebhookId,
)
from lekto.core.domain.json_value import JsonObject, JsonValue, as_list, as_object, as_uuid
from lekto.core.domain.permissions import in_reach
from lekto.core.domain.pipeline import (
    ACCEPTED,
    ACTOR,
    CHANGED,
    CHOSEN_SPACE,
    CORRECTED,
    ENTERED,
    KEPT,
    PERSON,
    PERSON_SPACE,
    RULES,
    RULES_CHANGE,
    TAGS_ADDED,
    TAGS_REMOVED,
    TRIGGER,
    Node,
    NodeResult,
    NodeRun,
    Outcome,
)
from lekto.core.domain.reasons import Reason, ReasonCode, because, reasons_to_json
from lekto.core.domain.rule_conditions import (
    TEXT_TARGET,
    Facts,
    Taxonomy,
    matches,
    pattern_subjects,
    pattern_text,
)
from lekto.core.domain.rule_planner import (
    Mode,
    RulePlan,
    Situation,
    SpaceTarget,
    plan,
    reviewing_rules,
)
from lekto.core.domain.rules import Rule, SetSpace, Trigger
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.patterns import PatternMatcher
from lekto.core.ports.templates import TemplateRenderer
from lekto.core.ports.unit_of_work import UnitOfWork
from lekto.core.services._access import space_label
from lekto.core.services._tags import tag_tree
from lekto.core.services.inbox import MODEL_NODES, arrived, field_checks, latest_entries
from lekto.core.services.objects import load_text
from lekto.core.services.titles import machine_title
from lekto.core.services.webhooks.delivery import queue_rule_send

log = logging.getLogger(__name__)


type PatternKey = tuple[str, str, bool]


async def active_rules(uow: UnitOfWork, space: SpaceId, trigger: Trigger | None) -> list[Rule]:
    """The enabled rules for a document in `space`: the global ones, and the space's own.
    `trigger` None: any trigger."""
    rules = await uow.rules.list_for(spaces=[space], include_global=True)
    return sorted(
        (
            rule
            for rule in rules
            if rule.is_active and (trigger is None or trigger in rule.definition.triggers)
        ),
        key=lambda rule: rule.order,
    )


async def space_rules(uow: UnitOfWork, space: SpaceId, trigger: Trigger) -> list[Rule]:
    """The enabled rules of `space` itself with `trigger` (no global ones): those that run
    when a completed document enters the space."""
    rules = await uow.rules.list_for(spaces=[space], include_global=False)
    return sorted(
        (rule for rule in rules if rule.is_active and trigger in rule.definition.triggers),
        key=lambda rule: rule.order,
    )


async def reachable_rules(
    uow: UnitOfWork, start: SpaceId, trigger: Trigger, *, include_global: bool
) -> list[Rule]:
    """The rules a document entering `start` may meet: those of `start` (with the global ones
    if `include_global`), and of every space they or the next ones file into (`set_space`),
    each once; for preparing their patterns before the transaction that runs them."""
    found: dict[RuleId, Rule] = {}
    seen: set[SpaceId] = set()
    queue = [start]
    first = True
    while queue:
        space = queue.pop(0)
        if space in seen:
            continue
        seen.add(space)
        rules = (
            await active_rules(uow, space, trigger)
            if first and include_global
            else await space_rules(uow, space, trigger)
        )
        first = False
        for rule in rules:
            found.setdefault(rule.id, rule)
            queue.extend(
                action.space_id
                for action in rule.definition.actions
                if isinstance(action, SetSpace) and action.space_id not in seen
            )
    return sorted(found.values(), key=lambda rule: rule.order)


def back_and_forth(names: Sequence[str]) -> Reason:
    """Why a chain of moves stopped: the rules would file the document into a space it was
    in already in this chain (each space at most once)."""
    return because(ReasonCode.RULES_BACK_AND_FORTH, spaces=list(names))


def problem_output(problem: Reason) -> JsonObject:
    """Why the rules' change did not apply, for a log entry's output: in English (`problem`)
    and with its code (`problem_reason`)."""
    return {"problem": problem.text, "problem_reason": problem.to_json()}


# --- text and patterns ------------------------------------------------------------------------


PATTERN_BUDGET = 2.0
"""Seconds the patterns of one rule run may take together on one document; the patterns left
then do not match (each pattern also has its own time limit)."""


class PatternBudget:
    """Time left for running patterns."""

    def __init__(self, seconds: float = PATTERN_BUDGET) -> None:
        self._end = time.monotonic() + seconds

    @property
    def exhausted(self) -> bool:
        return time.monotonic() >= self._end


@dataclass(frozen=True)
class Prepared:
    """The document text as conditions see it, and the results of the regular expressions on
    it. `problems`: patterns that timed out or could not run (they do not match)."""

    text: DocumentText | None = None
    patterns: Mapping[PatternKey, bool] = field(default_factory=dict)
    problems: tuple[str, ...] = ()


async def prepare(
    store: ObjectStore,
    matcher: PatternMatcher,
    rules: Sequence[Rule],
    document: Document,
    *,
    max_text: int,
    budget: PatternBudget | None = None,
) -> Prepared:
    """Load the text if a rule looks at it and run the rules' patterns on it."""
    if not any(rule.definition.uses_text for rule in rules):
        return Prepared()
    if document.processing.outcome(Node.PARSE) not in (Outcome.OK, Outcome.UNCERTAIN):
        return Prepared()
    try:
        markdown = (await load_text(store, document.id)).decode("utf-8")
    except NotFoundError:
        return Prepared()
    text = pattern_text(markdown, max_text)
    keys = {key for rule in rules for key in rule.definition.patterns() if key[0] == TEXT_TARGET}
    results, problems = await _search(matcher, {key: text for key in keys}, budget)
    return Prepared(DocumentText(text), results, problems)


async def field_patterns(
    matcher: PatternMatcher, rules: Sequence[Rule], document: Document
) -> tuple[dict[PatternKey, bool], tuple[str, ...]]:
    """The rules' patterns on the document's field values."""
    return await _search(matcher, pattern_subjects(rules, document, None), None)


async def _search(
    matcher: PatternMatcher, subjects: Mapping[PatternKey, str], budget: PatternBudget | None
) -> tuple[dict[PatternKey, bool], tuple[str, ...]]:
    budget = budget or PatternBudget()
    results: dict[PatternKey, bool] = {}
    problems: list[str] = []
    for key, subject in subjects.items():
        _, pattern, case_sensitive = key
        if budget.exhausted:
            problems.append(f"pattern {pattern!r} skipped: the time for patterns is used up")
            log.warning("rule pattern skipped", extra={"pattern": pattern, "error": "no time"})
            continue
        try:
            results[key] = await matcher.search(pattern, subject, case_sensitive=case_sensitive)
        except (PatternTimeoutError, ValidationError) as error:
            problems.append(str(error))
            log.warning("rule pattern skipped", extra={"pattern": pattern, "error": str(error)})
    return results, tuple(problems)


# --- where values came from -------------------------------------------------------------------

_DECISIONS = (ACCEPTED, ENTERED, KEPT, CHANGED)
_PERSON_ENTRIES = (PERSON, RULES_CHANGE, PERSON_SPACE)


@dataclass(frozen=True)
class Provenance:
    """Where the document's values came from, read from the processing log.

    - `model_values`: single fields (contact, type, topic, date, space, fields) whose value
      the model set in its latest run and no person has decided since, as JSON.
    - `machine_title`: the title the machine gave (`titles.machine_title`), if the document
      still has it and no person decided the title; applied to existing documents, rules
      replace it as they replace the file name.
    - `model_tags`: tags the model set that no person has decided on since.
    - `person`: fields a person decided (confirming in the inbox, or changing the document)
      since the model's latest run; `tags_added` and `tags_removed` by a person likewise.
    - `reviewed`: rules whose forced review a person confirmed in the current processing run.
    - `chained`: values in `model_values` that a rule of an earlier space in a chain set on
      unconfirmed values (`Chain`), not the model.
    """

    model_values: Mapping[str, JsonValue]
    model_tags: frozenset[TagId]
    person: frozenset[str]
    reviewed: frozenset[RuleId]
    tags_added: frozenset[TagId] = frozenset()
    tags_removed: frozenset[TagId] = frozenset()
    machine_title: str | None = None
    chained: frozenset[str] = frozenset()

    @property
    def unverified(self) -> frozenset[str]:
        return frozenset(
            name for name in (CONTACT, DOCUMENT_TYPE, TOPIC) if name in self.model_values
        )


def provenance(log: Sequence[NodeRun], document: Document) -> Provenance:
    latest = latest_entries(log, by_model=True)
    model_run = max((latest[node].run for node in MODEL_NODES if node in latest), default=0)
    person: set[str] = set()
    added: set[TagId] = set()
    removed: set[TagId] = set()
    for entry in log:
        if entry.run < model_run or entry.result.model_version not in _PERSON_ENTRIES:
            continue
        record = {**entry.result.input, **entry.result.output}
        for key in _DECISIONS:
            person.update(_strings(record.get(key)))
        for tag in _strings(record.get(TAGS_ADDED)):
            added.add(TagId(UUID(tag)))
            removed.discard(TagId(UUID(tag)))
        for tag in _strings(record.get(TAGS_REMOVED)):
            removed.add(TagId(UUID(tag)))
            added.discard(TagId(UUID(tag)))
    current = _current_values(document)
    model_values: dict[str, JsonValue] = {}
    model_tags: frozenset[TagId] = frozenset()
    for name, check in field_checks(log).items():
        if not check.ok or check.value is None or name in person:
            continue
        if name == TAGS:
            if isinstance(check.value, list):
                model_tags = frozenset(TagId(UUID(str(tag))) for tag in check.value) & frozenset(
                    document.tag_ids
                )
        elif name in current and repr(current[name]) == repr(check.value):
            model_values[name] = check.value
    run = document.processing.run
    reviewed: set[RuleId] = set()
    open_reviews: set[RuleId] = set()
    for entry in log:  # a confirmation answers the `apply_rules` entry before it
        if entry.result.model_version == RULES:
            open_reviews = reviewing_rules(entry.result.output)
        elif entry.result.model_version == PERSON and entry.run == run:
            reviewed |= open_reviews
    given = machine_title(log)
    return Provenance(
        model_values,
        model_tags,
        frozenset(person),
        frozenset(reviewed),
        frozenset(added),
        frozenset(removed),
        machine_title=given if TITLE not in person and document.title == given else None,
    )


def _strings(value: JsonValue) -> list[str]:
    return [str(item) for item in as_list(value)]


def person_record(
    *,
    changed: Iterable[str],
    tags_before: Collection[TagId],
    tags_after: Collection[TagId],
    corrected: Iterable[str] = (),
) -> dict[str, JsonValue]:
    """What a person changed, for a log entry `provenance` reads: the fields they set, the
    tags they added and removed, and (`corrected`) the fields whose values they really
    altered, for the share of automatic values corrected later."""
    added = sorted(str(tag) for tag in set(tags_after) - set(tags_before))
    removed = sorted(str(tag) for tag in set(tags_before) - set(tags_after))
    return {
        CHANGED: list[JsonValue](sorted(changed)),
        TAGS_ADDED: list[JsonValue](added),
        TAGS_REMOVED: list[JsonValue](removed),
        CORRECTED: list[JsonValue](sorted(corrected)),
    }


def corrected_fields(
    before: Document, after: Document, *, decided: Collection[str] | None = None
) -> frozenset[str]:
    """The values that differ between two states of a document, named as in field checks.
    With `decided` (the fields a person set), a topic only if they set it: one cleared
    because the new contact does not enable it is no correction of theirs."""
    names = {
        name
        for name, attribute in CHANGE_FIELDS.items()
        if getattr(before, attribute) != getattr(after, attribute)
    }
    for field_id in set(before.fields) | set(after.fields):
        if before.fields.get(field_id) != after.fields.get(field_id):
            names.add(field_key(field_id))
    if decided is not None and TOPIC not in decided:
        names.discard(TOPIC)
    return frozenset(names)


def entry_beside(
    document: Document,
    *,
    node: Node,
    model_version: str,
    input: JsonObject,
    output: JsonObject,
    version: str,
    now: datetime,
) -> NodeRun:
    """A log entry written beside processing, by a person or the rules (`OUTSIDE_PIPELINE`):
    in the document's current run, at `now`, taking no time."""
    return NodeRun(
        document_id=document.id,
        node=node,
        run=document.processing.run,
        result=NodeResult(
            outcome=Outcome.OK, model_version=model_version, input=input, output=output
        ),
        pipeline_version=version,
        started_at=now,
        duration=timedelta(0),
    )


def space_choice(
    document: Document, *, node: Node, actor: UserId, trigger: str, version: str, now: datetime
) -> NodeRun:
    """The log entry of a person choosing the document's space outside the inbox."""
    return entry_beside(
        document,
        node=node,
        model_version=PERSON_SPACE,
        input={TRIGGER: trigger, ACTOR: str(actor), CHOSEN_SPACE: str(document.space_id)},
        output=person_record(
            changed=[SPACE], tags_before=document.tag_ids, tags_after=document.tag_ids
        ),
        version=version,
        now=now,
    )


def _current_values(document: Document) -> dict[str, JsonValue]:
    values: dict[str, JsonValue] = {
        CONTACT: None if document.contact_id is None else str(document.contact_id),
        DOCUMENT_TYPE: None
        if document.document_type_id is None
        else str(document.document_type_id),
        TOPIC: None if document.topic_id is None else str(document.topic_id),
        DOCUMENT_DATE: None
        if document.document_date is None
        else document.document_date.isoformat(),
        # The judge's space (`judge_space`) is the model's while the document lies there.
        SPACE: str(document.space_id),
    }
    for id, value in document.fields.items():
        values[field_key(id)] = field_to_json(value)
    return values


def facts(
    document: Document,
    prepared: Prepared,
    patterns: Mapping[PatternKey, bool],
    origin: Provenance,
    taxonomy: Taxonomy | None = None,
) -> Facts:
    return Facts.of(
        document,
        text=prepared.text,
        patterns={**prepared.patterns, **patterns},
        unverified=origin.unverified,
        unverified_tags=origin.model_tags,
        taxonomy=taxonomy,
    )


@dataclass(frozen=True)
class Loaded:
    """The master data a rule run looks at, loaded once (`taxonomy`): the taxonomy, and the
    names of the contacts and types that exist, by id. The tags' names are in the tree."""

    taxonomy: Taxonomy
    contacts: Mapping[UUID, str]
    types: Mapping[UUID, str]


async def taxonomy(uow: UnitOfWork, documents: Iterable[Document], rules: Iterable[Rule]) -> Loaded:
    """The tag trees, and the groups and names of the contacts and types of `documents` and of
    those the rules refer to, and the topics those contacts enable."""
    contacts: set[UUID] = set()
    types: set[UUID] = set()
    for document in documents:
        if document.contact_id is not None:
            contacts.add(document.contact_id)
        if document.document_type_id is not None:
            types.add(document.document_type_id)
    for rule in rules:
        references = rule.definition.references()
        contacts |= references.contacts
        types |= references.document_types
    groups: dict[UUID, frozenset[TagId]] = {}
    topics: dict[UUID, frozenset[TagId]] = {}
    contact_names: dict[UUID, str] = {}
    type_names: dict[UUID, str] = {}
    for id in contacts:
        if (contact := await uow.contacts.find(ContactId(id))) is not None:
            groups[id] = contact.group_ids
            topics[id] = contact.topic_ids
            contact_names[id] = contact.name
    for id in types:
        if (kind := await uow.document_types.find(DocumentTypeId(id))) is not None:
            groups[id] = kind.group_ids
            type_names[id] = kind.name
    return Loaded(Taxonomy(await tag_tree(uow), groups, topics), contact_names, type_names)


# --- the situation ----------------------------------------------------------------------------


async def situation(
    uow: UnitOfWork,
    *,
    mode: Mode,
    document: Document,
    rules: Iterable[Rule],
    definitions: Mapping[FieldId, FieldDefinition],
    origin: Provenance,
    templates: TemplateRenderer,
    locked: Collection[str] = (),
    person_added_tags: frozenset[TagId] = frozenset(),
    person_removed_tags: frozenset[TagId] = frozenset(),
    accept_conflicts: bool = False,
    loaded: Loaded,
    applier: UserId | None = None,
) -> Situation:
    """Everything `plan` needs to know besides the matching rules. `loaded`: the master data
    of the run (`taxonomy`, for the document and at least `rules`); beyond it, only the
    spaces and the users are read."""
    rules = list(rules)
    references = [rule.definition.references() for rule in rules]
    existing: set[object] = set(definitions)
    names: dict[object, str] = {}
    contacts = {id for refs in references for id in refs.contacts}
    types = {id for refs in references for id in refs.document_types}
    if document.contact_id is not None:
        contacts.add(document.contact_id)
    if document.document_type_id is not None:
        types.add(document.document_type_id)
    for contact_id in contacts:
        if (name := loaded.contacts.get(contact_id)) is not None:
            existing.add(contact_id)
            names[contact_id] = name
    for type_id in types:
        if (name := loaded.types.get(type_id)) is not None:
            existing.add(type_id)
            names[type_id] = name
    tree = loaded.taxonomy.tree
    shown = {*document.tag_ids, *([] if document.topic_id is None else [document.topic_id])}
    for tag_id in {id for refs in references for id in refs.tags} | shown:
        if tag_id in tree:
            existing.add(tag_id)
            names[tag_id] = tree.tags[tag_id].name
    users = {user.id: user for user in await uow.users.list_all()}
    admins = frozenset(id for id, user in users.items() if user.is_active_admin)
    current = await uow.spaces.get(document.space_id)
    names[current.id] = space_label(current, users)
    spaces: dict[SpaceId, SpaceTarget] = {}
    for rule in rules:
        for action in rule.definition.actions:
            if isinstance(action, SetSpace) and action.space_id not in spaces:
                space = await uow.spaces.find(action.space_id)
                if space is not None:
                    editors = {id for id in space.editors if id in users and users[id].active}
                    receiver = None if space.personal_of is None else users.get(space.personal_of)
                    spaces[space.id] = SpaceTarget(
                        name=space_label(space, users),
                        filers=admins | editors,
                        personal=receiver is not None and receiver.active,
                        widens=current.widens(space),
                    )
                    names[space.id] = spaces[space.id].name
    uploader = None if document.uploaded_by is None else users.get(document.uploaded_by)
    return Situation(
        mode=mode,
        document=document,
        definitions=definitions,
        render=templates.render,
        in_personal_space=current.is_personal,
        uploader_name=None if uploader is None else uploader.label,
        spaces=spaces,
        existing=frozenset(existing),
        names=names,
        model_values=origin.model_values,
        chained=origin.chained,
        machine_title=origin.machine_title,
        locked=frozenset(locked),
        person_added_tags=person_added_tags,
        person_removed_tags=person_removed_tags,
        reviewed=origin.reviewed,
        accept_conflicts=accept_conflicts,
        taxonomy=loaded.taxonomy,
        applier=applier,
    )


def checked_rules(rules: Iterable[Rule]) -> list[JsonValue]:
    """The rules a run looked at, for the log's input."""
    return [{"id": str(rule.id), "version": rule.current.number} for rule in rules]


# --- chains -----------------------------------------------------------------------------------


@dataclass
class Chain:
    """What a chain of rule runs (each space a document enters runs its rules) carries from one
    space to the next: values its rules set only through unconfirmed model values stay
    unconfirmed for the next space's rules, as the model's own would. So a rule cannot launder
    an unconfirmed contact into a type a later rule files on into a wider space; and a later
    rule that sets another value there disagrees (a conflict, not a silent overwrite)."""

    values: dict[str, JsonValue] = field(default_factory=dict)
    tags: set[TagId] = field(default_factory=set)

    def origin(self, origin: Provenance) -> Provenance:
        """`origin` with what the chain carries so far."""
        if not self.values and not self.tags:
            return origin
        values = {name: value for name, value in self.values.items() if name not in origin.person}
        return replace(
            origin,
            model_values={**origin.model_values, **values},
            model_tags=origin.model_tags | frozenset(self.tags),
            chained=origin.chained | frozenset(values),
        )

    def record(self, plan: RulePlan, document: Document) -> None:
        """After `plan` was applied to `document`: carry what it set on unconfirmed values."""
        current = _current_values(document)
        for name in plan.distrusted:
            if name in current and current[name] is not None:
                self.values[name] = current[name]
        self.tags |= plan.distrusted_tags & set(document.tag_ids)


# --- one run ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Send:
    """A request a matching rule sends through a webhook (`rules.SendWebhook`): queued when the
    document is filed (on arrival) or once the run is stored (a change, a move, applying a rule
    to existing documents). `author`: who saved the rule's version, whose webhook it must be."""

    rule_id: RuleId
    version: int
    name: str
    author: UserId | None
    webhook_id: WebhookId

    def to_json(self) -> JsonObject:
        return {
            "rule_id": str(self.rule_id),
            "version": self.version,
            "name": self.name,
            "webhook_id": str(self.webhook_id),
            **({} if self.author is None else {"author": str(self.author)}),
        }

    @classmethod
    def from_json(cls, data: JsonValue) -> "Send | None":
        """The send of a log entry's output; None if it is not one."""
        item = as_object(data) or {}
        rule, webhook = as_uuid(item.get("rule_id")), as_uuid(item.get("webhook_id"))
        version, name, author = item.get("version"), item.get("name"), as_uuid(item.get("author"))
        if rule is None or webhook is None or not isinstance(version, int):
            return None
        return cls(
            rule_id=RuleId(rule),
            version=version,
            name=name if isinstance(name, str) else "",
            author=None if author is None else UserId(author),
            webhook_id=WebhookId(webhook),
        )

    @property
    def rule(self) -> JsonObject:
        """The rule as the request names it."""
        return {"id": str(self.rule_id), "name": self.name}


SENDS = "sends"
"""Key of the requests a rule run sends, in its log entry's output."""
SENDS_REFUSED = "sends_refused"
"""Key of the requests it could not send, with why, in its log entry's output."""


async def deliverable(
    uow: UnitOfWork, sends: Iterable[Send], document: Document
) -> tuple[list[Send], list[Reason]]:
    """Of `sends`, those whose webhook is there, still its rule author's, and whose owner may
    read `document` where it lies now; and why the others are not."""
    space = await uow.spaces.find(document.space_id)
    ok: list[Send] = []
    refused: list[Reason] = []
    for send in sends:
        webhook = await uow.webhooks.find(send.webhook_id)
        owner = None if webhook is None else await uow.users.find(webhook.owner_id)
        if owner is None or not owner.active or owner.id != send.author:
            refused.append(because(ReasonCode.RULE_WEBHOOK_GONE, rule=send.name))
        elif space is None or not in_reach(owner, document, space):
            refused.append(because(ReasonCode.RULE_WEBHOOK_UNREADABLE, rule=send.name))
        else:
            ok.append(send)
    return ok, refused


async def queue_sends(
    uow: UnitOfWork, sends: Iterable[Send], document: Document, now: datetime
) -> None:
    """Queue the requests in the unit of work that stores the document: they go only if it is
    committed."""
    for send in sends:
        await queue_rule_send(
            uow, webhook_id=send.webhook_id, document_id=document.id, rule=send.rule, now=now
        )


async def send_now(
    uow: UnitOfWork, sends: Iterable[Send], document: Document, now: datetime
) -> JsonObject:
    """Outside processing (a change, a move, applying a rule to existing documents): queue the
    requests that may go, and report those that may not (nothing turns yellow there). The part
    of the log entry's output that says so."""
    ok, refused = await deliverable(uow, sends, document)
    await queue_sends(uow, ok, document, now)
    output: JsonObject = {}
    if ok:
        output[SENDS] = [send.to_json() for send in ok]
    if refused:
        output[SENDS_REFUSED] = reasons_to_json(refused)
    return output


@dataclass(frozen=True)
class RuleRun:
    """The plan of one rule run, with the patterns that could not run and the requests the
    matching rules send (`sends`)."""

    plan: RulePlan
    problems: tuple[str, ...]
    sends: tuple[Send, ...] = ()

    def output(self) -> JsonObject:
        data = self.plan.to_json()
        if self.problems:
            data["problems"] = list[JsonValue](self.problems)
        return data


async def run_rules(
    uow: UnitOfWork,
    matcher: PatternMatcher,
    templates: TemplateRenderer,
    *,
    mode: Mode,
    document: Document,
    rules: Sequence[Rule],
    prepared: Prepared,
    origin: Provenance,
    definitions: Mapping[FieldId, FieldDefinition],
    before: tuple[Document, Mapping[PatternKey, bool]] | None = None,
    locked: Collection[str] = (),
    accept_conflicts: bool = False,
    applier: UserId | None = None,
) -> RuleRun:
    """Evaluate `rules` on the document and plan their change (nothing is applied). `before`:
    for a change, the state before it and its field pattern results; only rules that become
    true with the change act. `applier`: who applies the rules to existing documents."""
    patterns, problems = await field_patterns(matcher, rules, document)
    loaded = await taxonomy(uow, [document, *([] if before is None else [before[0]])], rules)
    now_facts = facts(document, prepared, patterns, origin, loaded.taxonomy)
    before_facts = None
    if before is not None:
        before_facts = facts(before[0], prepared, before[1], origin, loaded.taxonomy)
    matched = matches(rules, now_facts, definitions, before=before_facts)
    context = await situation(
        uow,
        mode=mode,
        document=document,
        rules=[match.rule for match in matched],
        definitions=definitions,
        origin=origin,
        templates=templates,
        locked=locked,
        person_added_tags=origin.tags_added,
        person_removed_tags=origin.tags_removed,
        accept_conflicts=accept_conflicts,
        loaded=loaded,
        applier=applier,
    )
    sends = tuple(
        Send(
            rule_id=match.rule.id,
            version=match.rule.current.number,
            name=match.rule.definition.name,
            author=match.rule.current.created_by,
            webhook_id=action.webhook_id,
        )
        for match in matched
        for action in match.rule.definition.sends
    )
    return RuleRun(plan(matched, context), prepared.problems + problems, sends)


async def apply_plan(
    uow: UnitOfWork,
    document: Document,
    rule_plan: RulePlan,
    definitions: Mapping[FieldId, FieldDefinition],
    now: datetime,
) -> Reason | None:
    """Apply the planned change and space; the reason if the change no longer fits (nothing
    is applied then)."""
    try:
        document.apply_changes(rule_plan.changes, definitions, now)
    except ValidationError as error:
        return because(ReasonCode.RULES_CHANGE_UNFIT, detail=str(error))
    if rule_plan.space is not None and rule_plan.space != document.space_id:
        source = await uow.spaces.get(document.space_id)
        target = await uow.spaces.get(rule_plan.space)
        document.move_to(
            rule_plan.space,
            now,
            handed_over=target.personal_of not in (None, document.uploaded_by),
        )
        await arrived(uow, document, source, now)
    return None
