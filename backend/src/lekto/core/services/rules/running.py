"""What every rule run needs: the rules that apply to a document, its text and pattern results,
where its values came from (model, person), and the facts about spaces and master data.

Loading the text and running the regular expressions on it happens before the unit of work that
stores the result (`prepare`), so no transaction waits for a slow pattern. Patterns on field
values (short) run inside it, on the state that is stored.
"""

import logging
import time
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
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
)
from lekto.core.domain.json_value import JsonObject, JsonValue, as_list
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

    - `model_values`: single fields (contact, type, topic, date, fields) whose value the model
      set in its latest run and no person has decided since, as JSON.
    - `machine_title`: the title the machine gave (`titles.machine_title`), if the document
      still has it and no person decided the title; applied to existing documents, rules
      replace it as they replace the file name.
    - `model_tags`: tags the model set that no person has decided on since.
    - `person`: fields a person decided (confirming in the inbox, or changing the document)
      since the model's latest run; `tags_added` and `tags_removed` by a person likewise.
    - `reviewed`: rules whose forced review a person confirmed in the current processing run.
    """

    model_values: Mapping[str, JsonValue]
    model_tags: frozenset[TagId]
    person: frozenset[str]
    reviewed: frozenset[RuleId]
    tags_added: frozenset[TagId] = frozenset()
    tags_removed: frozenset[TagId] = frozenset()
    machine_title: str | None = None

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
        uploader_name=None if uploader is None else uploader.username,
        spaces=spaces,
        existing=frozenset(existing),
        names=names,
        model_values=origin.model_values,
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


# --- one run ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleRun:
    """The plan of one rule run, with the patterns that could not run."""

    plan: RulePlan
    problems: tuple[str, ...]

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
    return RuleRun(plan(matched, context), prepared.problems + problems)


async def apply_plan(
    uow: UnitOfWork,
    document: Document,
    rule_plan: RulePlan,
    definitions: Mapping[FieldId, FieldDefinition],
    now: datetime,
) -> str | None:
    """Apply the planned change and space; the reason if the change no longer fits (nothing
    is applied then), or if the space holds the same file already (the space is left)."""
    try:
        document.apply_changes(rule_plan.changes, definitions, now)
    except ValidationError as error:
        return f"the rules' change does not fit: {error}"
    if rule_plan.space is not None and rule_plan.space != document.space_id:
        if await uow.documents.list_by_sha256(document.sha256, [rule_plan.space]):
            # Not named: the editors of the document may not read the other one.
            return "the space the rules file into holds the same file already"
        source = await uow.spaces.get(document.space_id)
        document.move_to(rule_plan.space, now)
        await arrived(uow, document, source, now)
    return None
