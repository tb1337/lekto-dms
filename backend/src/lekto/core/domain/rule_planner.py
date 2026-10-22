"""Turning the actions of the matching rules (`rule_conditions.matches`) into one change,
with conflicts instead of silent overwrites.

How the actions of all matching rules come together (`plan`):

- A single field (space, contact, type, topic, title, a field) set by one rule, or by several
  to the same value, is set. Several different values are a conflict: nothing is set.
- A topic is set only if the contact the rules leave enables it (otherwise the action is
  skipped and noted); a contact set that does not enable the document's topic clears it,
  unless a person chose that topic: then the contact is overruled.
- A value a person decided (confirming in the inbox, or changing the document) is never
  replaced: the rule is overruled and that is logged.
- A value the model set and no person confirmed is not replaced either: a conflict.
- Tags added and removed by rules are combined; a tag added by one rule and removed by another
  is a conflict. Removing a tag the model set is no conflict (tags are unchecked proposals). Only
  document tags are added (also those set by hand); the result is normalised: a tag above one
  the document keeps is not added, and a parent gives way to its child.
- On arrival (`ingest`) conflicts, refused actions and forced reviews make the node uncertain:
  the document waits in the inbox. On a change by a person (`change`) nothing turns yellow (a
  filed document would disappear for everyone else): what cannot be applied is only reported.
- Applied to existing documents on request (`retroactive`), one rule: a field that has another
  value already is a conflict, applied only where the person accepted it.

Reasons name what they are about as a person reads it: contacts, types, topics, spaces, tags
and fields by their names, a field's value as written (`_Planner._shown`); the ids stay in the
structured parts (values, suggestions, effects). Only something that no longer exists is named
by its id.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from lekto.core.domain.classification import (
    CHANGE_FIELDS,
    CHECKS,
    CONTACT,
    DOCUMENT_TYPE,
    REVIEW,
    SPACE,
    TAGS,
    TITLE,
    TOPIC,
    CheckField,
    FieldCheck,
    field_id_of,
    field_key,
)
from lekto.core.domain.documents import Document, DocumentChanges, Unset
from lekto.core.domain.errors import MissingValueError, ValidationError
from lekto.core.domain.fields import (
    FieldDefinition,
    FieldType,
    FieldValue,
    Money,
    Url,
    decimal_text,
    field_from_json,
    field_to_json,
)
from lekto.core.domain.ids import (
    ContactId,
    DocumentTypeId,
    FieldId,
    RuleId,
    SpaceId,
    TagId,
    UserId,
)
from lekto.core.domain.json_value import JsonObject, JsonValue, as_list, as_object, as_uuid
from lekto.core.domain.master_data import TagScope
from lekto.core.domain.periods import Period
from lekto.core.domain.pipeline import Outcome
from lekto.core.domain.rule_conditions import Match, Taxonomy
from lekto.core.domain.rules import (
    AddTags,
    ForceReview,
    RemoveTags,
    RuleScope,
    SetContact,
    SetDocumentType,
    SetField,
    SetSpace,
    SetTitle,
    SetTopic,
)
from lekto.core.domain.templates import Render, TemplateValue, template_values


class Mode(StrEnum):
    INGEST = "ingest"
    CHANGE = "change"
    RETROACTIVE = "retroactive"


# --- planning the change ----------------------------------------------------------------------


@dataclass(frozen=True)
class SpaceTarget:
    """What the rules need to know about a space they file into. `filers`: who may file into
    it (its active editors and the active admins); `personal`: the personal space of an active
    user, into which a document may be handed over by anyone (a deactivated user receives
    nothing); `widens`: moving the document there shows it to someone who cannot read it where
    it lies (`Space.widens`)."""

    name: str
    filers: frozenset[UserId]
    personal: bool
    widens: bool

    def open_to(self, author: UserId | None) -> bool:
        """Whether a rule last saved by `author` may file into it."""
        return self.personal or (author is not None and author in self.filers)


@dataclass(frozen=True, kw_only=True)
class Situation:
    """Everything `plan` needs besides the matching rules.

    - `spaces`: the spaces the rules file into that exist.
    - `existing`: ids of the contacts, types, tags and fields that exist.
    - `names`: names of contacts, types, tags and spaces, for templates; `uploader_name` that
      of who uploaded the document.
    - `in_personal_space`: the document lies in a personal space; for applying to existing
      documents its space counts as empty there.
    - `render`: renders the templates of titles, text fields and review reasons (the port
      `TemplateRenderer`).
    - `model_values`: single fields that hold the value the model set, unconfirmed, as JSON.
    - `machine_title`: the title the machine gave, if the document still has it; like the
      file name, rules may replace it.
    - `locked`: single fields a person decided; `person_added_tags` and `person_removed_tags`
      likewise for tags.
    - `reviewed`: rules whose forced review a person confirmed in this processing run.
    - `accept_conflicts` (retroactive): the person accepted the rule's values over others.
    - `applier` (retroactive): who applies the rules; they file only where they may file
      themselves (or hand over), whoever saved the rule.
    - `taxonomy`: the tag trees (tags added are document tags, the result is normalised) and
      the groups of the contacts and types the rules may leave (for templates).
    """

    mode: Mode
    document: Document
    definitions: Mapping[FieldId, FieldDefinition]
    render: Render
    in_personal_space: bool = False
    uploader_name: str | None = None
    spaces: Mapping[SpaceId, SpaceTarget] = field(default_factory=dict)
    existing: frozenset[object] = frozenset()
    names: Mapping[object, str] = field(default_factory=dict)
    model_values: Mapping[str, JsonValue] = field(default_factory=dict)
    machine_title: str | None = None
    locked: frozenset[str] = frozenset()
    person_added_tags: frozenset[TagId] = frozenset()
    person_removed_tags: frozenset[TagId] = frozenset()
    reviewed: frozenset[RuleId] = frozenset()
    accept_conflicts: bool = False
    taxonomy: Taxonomy = field(default_factory=Taxonomy)
    applier: UserId | None = None


@dataclass(frozen=True)
class Effect:
    field: str
    old: JsonValue
    new: JsonValue

    def to_json(self) -> JsonObject:
        return {"field": self.field, "old": self.old, "new": self.new}


class NoteKind(StrEnum):
    """Why a rule's action was not applied, or a review the rule forces."""

    SKIPPED = "skipped"  # gone, does not apply, or a template writes a missing value
    OVERRULED = "overruled"  # a person decided the field
    REFUSED = "refused"  # rights, scope, unconfirmed values
    CONFLICT = "conflict"  # rules or values disagree
    REVIEW = "review"  # the rule holds the document for a review
    YIELDED = "yielded"  # the type's title pattern gave way to another rule


@dataclass(frozen=True)
class Note:
    """An action that was not applied, and why, or a review the rule forces."""

    field: str
    kind: NoteKind
    reason: str

    def to_json(self) -> JsonObject:
        return {"field": self.field, "kind": self.kind, "reason": self.reason}


@dataclass
class RuleReport:
    rule_id: RuleId
    version: int
    name: str
    scope: RuleScope
    applied: list[Effect] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)

    def to_json(self, *, names: bool = True) -> JsonObject:
        data: JsonObject = {
            "rule_id": str(self.rule_id),
            "version": self.version,
            "scope": self.scope.value,
            "applied": [item.to_json() for item in self.applied],
            "notes": [item.to_json() for item in self.notes],
        }
        if names:
            data["name"] = self.name
        return data


@dataclass
class RulePlan:
    """The combined change of all matching rules.

    `checks`: per single field the rules touched, as in the model nodes: OK if applied,
    uncertain (on arrival) if a person has to decide; the inbox reads them. `reviews`:
    reasons of forced reviews that hold. `labels`: how `reasons` names a field (`field:<id>`)
    of a check, by its name."""

    changes: DocumentChanges
    space: SpaceId | None
    reports: list[RuleReport]
    checks: list[FieldCheck]
    reviews: list[str]
    labels: Mapping[str, str] = field(default_factory=dict)

    @property
    def uncertain(self) -> bool:
        return bool(self.reviews) or any(not check.ok for check in self.checks)

    @property
    def reasons(self) -> list[str]:
        return [
            f"{self.labels.get(check.field, check.field)}: {check.reason}"
            for check in self.checks
            if not check.ok
        ] + self.reviews

    @property
    def effects(self) -> list[Effect]:
        return [effect for report in self.reports for effect in report.applied]

    def to_json(self) -> JsonObject:
        return {
            "rules": [report.to_json() for report in self.reports],
            CHECKS: [check.to_json() for check in self.checks],
            "reviews": list(self.reviews),
        }


def reviewing_rules(output: JsonValue) -> set[RuleId]:
    """The rules that forced a review, in what `RulePlan.to_json` wrote."""
    found: set[RuleId] = set()
    for value in as_list((as_object(output) or {}).get("rules")):
        report = as_object(value) or {}
        rule = as_uuid(report.get("rule_id"))
        notes = (as_object(note) or {} for note in as_list(report.get("notes")))
        if rule is not None and any(note.get("kind") == NoteKind.REVIEW for note in notes):
            found.add(RuleId(rule))
    return found


@dataclass
class _Candidate:
    report: RuleReport
    value: JsonValue
    match: Match


def plan(matched: Sequence[Match], situation: Situation) -> RulePlan:
    """Combine the actions of the matching rules (in rule order) into one change."""
    return _Planner(matched, situation).run()


class _Planner:
    def __init__(self, matched: Sequence[Match], situation: Situation) -> None:
        self._matched = list(matched)
        self._s = situation
        self._document = situation.document
        self._reports = [
            RuleReport(
                match.rule.id,
                match.rule.current.number,
                match.rule.definition.name,
                match.rule.scope,
            )
            for match in self._matched
        ]
        self._checks: dict[str, FieldCheck] = {}
        self._reviews: list[str] = []
        self._candidates: dict[str, list[_Candidate]] = {}
        self._adds: dict[TagId, list[RuleReport]] = {}
        self._removes: dict[TagId, list[RuleReport]] = {}
        self._titles: list[tuple[RuleReport, SetTitle, Match]] = []
        self._texts: list[tuple[RuleReport, SetField, Match]] = []
        self._review_reasons: list[tuple[RuleReport, str]] = []

    def run(self) -> RulePlan:
        for match, report in zip(self._matched, self._reports, strict=True):
            for action in match.rule.definition.actions:
                self._collect(match, report, action)
        result: dict[str, JsonValue] = {}
        self._person_topic()
        for single in (DOCUMENT_TYPE, CONTACT, SPACE):
            self._single(single, result)
        self._topic(result)
        type_after = self._type_after(result)
        self._text_fields(result, type_after)
        fields: dict[FieldId, object] = {}
        for field_name, field_id in [
            (name, id) for name in self._candidates if (id := field_id_of(name)) is not None
        ]:
            definition = self._s.definitions[field_id]
            if not definition.applies_to(type_after):
                for candidate in self._candidates[field_name]:
                    candidate.report.notes.append(
                        Note(field_name, NoteKind.SKIPPED, f"'{definition.name}' does not apply")
                    )
                continue
            self._single(field_name, result)
            if field_name in result:
                fields[field_id] = field_from_json(definition, result[field_name])
        tags = self._tags()
        values = self._values(result, type_after, fields, tags)
        self._title(result, values)
        for report, reason in self._review_reasons:
            self._review(report, self._reason(reason, values))
        changes = DocumentChanges(fields=fields)
        if CONTACT in result:
            changes = replace(changes, contact_id=ContactId(UUID(str(result[CONTACT]))))
        if DOCUMENT_TYPE in result:
            changes = replace(
                changes, document_type_id=DocumentTypeId(UUID(str(result[DOCUMENT_TYPE])))
            )
        if TOPIC in result:
            topic = result[TOPIC]
            changes = replace(changes, topic_id=None if topic is None else TagId(UUID(str(topic))))
        if TITLE in result:
            changes = replace(changes, title=str(result[TITLE]))
        if tags is not None:
            changes = replace(changes, tag_ids=tags)
        space = SpaceId(UUID(str(result[SPACE]))) if SPACE in result else None
        definitions = self._s.definitions
        return RulePlan(
            changes=changes,
            space=space,
            reports=self._reports,
            checks=list(self._checks.values()),
            reviews=self._reviews,
            labels={
                name: f"'{definitions[id].name}'"
                for name in self._checks
                if (id := field_id_of(name)) is not None and id in definitions
            },
        )

    # --- collecting ---------------------------------------------------------------------------

    def _collect(self, match: Match, report: RuleReport, action: object) -> None:
        s = self._s
        match action:
            case SetSpace(space_id=space):
                self._space(match, report, space)
            case SetContact(contact_id=contact):
                self._candidate(CONTACT, str(contact), contact, match, report)
            case SetDocumentType(document_type_id=document_type):
                self._candidate(DOCUMENT_TYPE, str(document_type), document_type, match, report)
            case SetTopic(topic_id=topic):
                self._candidate(TOPIC, str(topic), topic, match, report)
            case SetTitle():
                self._titles.append((report, action, match))
            case AddTags(tag_ids=tags) | RemoveTags(tag_ids=tags):
                target = self._adds if isinstance(action, AddTags) else self._removes
                tree = s.taxonomy.tree
                for tag in sorted(tags):
                    if tag not in s.existing:
                        report.notes.append(
                            Note(TAGS, NoteKind.SKIPPED, f"tag {tag} no longer exists")
                        )
                    elif tag in tree and tree.tags[tag].scope is not TagScope.DOCUMENT:
                        reason = f"tag {self._tag(tag)} is a group, not a document tag"
                        report.notes.append(Note(TAGS, NoteKind.SKIPPED, reason))
                    else:
                        target.setdefault(tag, []).append(report)
            case SetField(field_id=field, value=value):
                name = field_key(field)
                definition = s.definitions.get(field)
                if definition is None:
                    report.notes.append(Note(name, NoteKind.SKIPPED, "the field no longer exists"))
                    return
                if definition.data_type is FieldType.TEXT and isinstance(value, str):
                    self._texts.append((report, action, match))
                    return
                try:
                    field_from_json(definition, value)
                except ValidationError as error:
                    report.notes.append(Note(name, NoteKind.SKIPPED, str(error)))
                    return
                self._candidates.setdefault(name, []).append(_Candidate(report, value, match))
            case ForceReview(reason=reason):
                self._review_reasons.append((report, reason))

    def _candidate(
        self, field_name: str, value: str, id: object, match: Match, report: RuleReport
    ) -> None:
        if id not in self._s.existing:
            report.notes.append(
                Note(field_name, NoteKind.SKIPPED, f"{field_name} {value} no longer exists")
            )
        else:
            self._candidates.setdefault(field_name, []).append(_Candidate(report, value, match))

    def _space(self, match: Match, report: RuleReport, space: SpaceId) -> None:
        s = self._s
        target = s.spaces.get(space)
        rule = match.rule
        if rule.scope is RuleScope.SPACE and rule.space_id != self._document.space_id:
            report.notes.append(Note(SPACE, NoteKind.REFUSED, "the rule belongs to another space"))
        elif target is None:
            report.notes.append(Note(SPACE, NoteKind.SKIPPED, f"space {space} no longer exists"))
        elif not target.open_to(rule.current.created_by):
            reason = f"no right to file into space '{target.name}' (any more)"
            report.notes.append(Note(SPACE, NoteKind.REFUSED, reason))
            if s.mode is Mode.INGEST and SPACE not in s.locked:
                self._uncertain(SPACE, f"rule '{report.name}': {reason}", suggestion=None)
        elif s.mode is Mode.RETROACTIVE and not target.open_to(s.applier):
            # Applying a rule moves no document where the person could not move it by hand.
            reason = f"you have no right to file into space '{target.name}'"
            report.notes.append(Note(SPACE, NoteKind.REFUSED, reason))
        elif target.widens and not match.trusted and s.mode is Mode.RETROACTIVE:
            # The person sees the move in the preview and may accept it, as any conflict.
            fields = ", ".join(match.distrusted)
            if s.accept_conflicts:
                self._candidates.setdefault(SPACE, []).append(_Candidate(report, str(space), match))
            else:
                reason = (
                    f"files into the space '{target.name}', which more people see, with an "
                    f"unconfirmed {fields}; not accepted"
                )
                report.notes.append(Note(SPACE, NoteKind.CONFLICT, reason))
        elif target.widens and not match.trusted:
            fields = ", ".join(match.distrusted)
            reason = (
                f"files into the space '{target.name}', which more people see, only with a "
                f"confirmed {fields}"
            )
            report.notes.append(Note(SPACE, NoteKind.REFUSED, reason))
            if s.mode is Mode.INGEST:
                for name in match.distrusted:
                    self._uncertain(
                        name,
                        f"rule '{report.name}' {reason}",
                        suggestion=self._current(name),
                    )
        else:
            self._candidates.setdefault(SPACE, []).append(_Candidate(report, str(space), match))

    def _review(self, report: RuleReport, reason: str) -> None:
        s = self._s
        if s.mode is not Mode.INGEST:
            report.notes.append(
                Note(REVIEW, NoteKind.SKIPPED, "reviews are forced on arrival only")
            )
        elif report.rule_id in s.reviewed:
            report.notes.append(Note(REVIEW, NoteKind.OVERRULED, "a person confirmed the review"))
        else:
            report.notes.append(Note(REVIEW, NoteKind.REVIEW, reason))
            self._reviews.append(f"rule '{report.name}': {reason}")
            self._uncertain(REVIEW, f"rule '{report.name}': {reason}", suggestion=None)

    # --- resolving ----------------------------------------------------------------------------

    def _single(self, field_name: str, result: dict[str, JsonValue]) -> None:
        candidates = self._candidates.get(field_name, [])
        if not candidates:
            return
        s = self._s
        current = self._current(field_name)
        values = list(dict.fromkeys(_key(candidate.value) for candidate in candidates))
        if len(values) > 1:
            listed = ", ".join(
                f"'{candidate.report.name}': {self._shown(field_name, candidate.value)}"
                for candidate in candidates
            )
            disagree = f"rules set different values ({listed})"
            for candidate in candidates:
                candidate.report.notes.append(Note(field_name, NoteKind.CONFLICT, disagree))
            if s.mode is Mode.INGEST and field_name not in s.locked:
                self._uncertain(field_name, disagree, suggestion=candidates[0].value)
            return
        value = candidates[0].value
        if _key(value) == _key(current):
            return
        reason: str | None = None
        kind = NoteKind.CONFLICT
        if s.mode is Mode.RETROACTIVE:
            if not self._empty(field_name, current) and not s.accept_conflicts:
                reason = (
                    f"the document has another value ({self._shown(field_name, current)}); "
                    "not accepted"
                )
        elif field_name in s.locked:
            kind, reason = NoteKind.OVERRULED, "a person decided this field"
        elif field_name in s.model_values and _key(s.model_values[field_name]) == _key(current):
            reason = f"the model set another value ({self._shown(field_name, current)})"
            if s.mode is Mode.INGEST:
                self._uncertain(field_name, f"rules: {reason}", suggestion=value)
        if reason is not None:
            for candidate in candidates:
                candidate.report.notes.append(Note(field_name, kind, reason))
            return
        result[field_name] = value
        for candidate in candidates:
            candidate.report.applied.append(Effect(field_name, current, value))
        if s.mode is Mode.INGEST:
            self._checks.setdefault(
                field_name,
                FieldCheck(
                    field=field_name, outcome=Outcome.OK, confidence=1, value=value, proposed=value
                ),
            )

    def _person_topic(self) -> None:
        """A contact a rule sets that does not enable the topic a person chose is overruled:
        the person's topic stays, and so does the contact that enables it."""
        topic = self._document.topic_id
        if TOPIC not in self._s.locked or topic is None or CONTACT not in self._candidates:
            return
        kept = []
        for candidate in self._candidates[CONTACT]:
            if topic in self._s.taxonomy.topics_of(UUID(str(candidate.value))):
                kept.append(candidate)
            else:
                reason = f"a person chose the topic {self._tag(topic)}, which it does not enable"
                candidate.report.notes.append(Note(CONTACT, NoteKind.OVERRULED, reason))
        if kept:
            self._candidates[CONTACT] = kept
        else:
            del self._candidates[CONTACT]

    def _topic(self, result: dict[str, JsonValue]) -> None:
        """The topic the rules set, if the contact they leave enables it; a contact set that
        does not enable the document's topic clears it (an effect of the rules that set the
        contact)."""
        contact = result.get(CONTACT, self._current(CONTACT))
        contact_id = None if contact is None else UUID(str(contact))
        enabled = self._s.taxonomy.topics_of(contact_id)
        candidates = self._candidates.get(TOPIC, [])
        for candidate in candidates:
            if TagId(UUID(str(candidate.value))) not in enabled:
                named = self._shown(TOPIC, candidate.value)
                reason = (
                    "the document has no contact"
                    if contact_id is None
                    else f"its contact does not enable the topic {named}"
                )
                candidate.report.notes.append(Note(TOPIC, NoteKind.SKIPPED, reason))
        kept = [item for item in candidates if TagId(UUID(str(item.value))) in enabled]
        if kept:
            self._candidates[TOPIC] = kept
        else:
            self._candidates.pop(TOPIC, None)
        self._single(TOPIC, result)
        topic = self._document.topic_id
        if TOPIC in result or CONTACT not in result or topic is None or topic in enabled:
            return
        result[TOPIC] = None
        for candidate in self._candidates.get(CONTACT, []):
            candidate.report.applied.append(Effect(TOPIC, str(topic), None))

    def _tags(self) -> frozenset[TagId] | None:
        s = self._s
        current = frozenset(self._document.tag_ids)
        both = set(self._adds) & set(self._removes)
        for tag in sorted(both):
            reason = f"tag {self._tag(tag)} is added and removed by rules"
            for report in self._adds[tag] + self._removes[tag]:
                report.notes.append(Note(TAGS, NoteKind.CONFLICT, reason))
            if s.mode is Mode.INGEST and TAGS not in s.locked:
                self._uncertain(TAGS, reason, suggestion=None)
        added: set[TagId] = set()
        removed: set[TagId] = set()
        for tag, reports in self._adds.items():
            if tag in both or tag in current:
                continue
            if tag in s.person_removed_tags:
                for report in reports:
                    reason = f"a person removed tag {self._tag(tag)}"
                    report.notes.append(Note(TAGS, NoteKind.OVERRULED, reason))
                continue
            added.add(tag)
        for tag, reports in self._removes.items():
            if tag in both or tag not in current:
                continue
            if tag in s.person_added_tags:
                for report in reports:
                    reason = f"a person set tag {self._tag(tag)}"
                    report.notes.append(Note(TAGS, NoteKind.OVERRULED, reason))
                continue
            removed.add(tag)
            for report in reports:
                report.applied.append(Effect(TAGS, str(tag), None))
        if not added and not removed:
            return None
        # A tag above one the document keeps or gets says nothing more: it is not added.
        result = s.taxonomy.tree.normalise((current | added) - removed)
        for tag in sorted(added):
            for report in self._adds[tag]:
                if tag in result:
                    report.applied.append(Effect(TAGS, None, str(tag)))
                else:
                    reason = f"tag {self._tag(tag)} is above a tag the document has"
                    report.notes.append(Note(TAGS, NoteKind.SKIPPED, reason))
        return None if result == current else result

    def _title(self, result: dict[str, JsonValue], values: Mapping[str, TemplateValue]) -> None:
        if not self._titles:
            return
        patterns: list[_Candidate] = []
        for report, action, match in self._titles:
            pattern = match.rule.managed_by is not None
            rendered = self._render(report, TITLE, action.template, values)
            if rendered is None:
                continue
            title = " ".join(rendered.split())
            if not title:
                report.notes.append(Note(TITLE, NoteKind.SKIPPED, "the title would be empty"))
                continue
            candidate = _Candidate(report, title, match)
            if pattern:
                patterns.append(candidate)
            else:
                self._candidates.setdefault(TITLE, []).append(candidate)
        # The type's title pattern gives way to a rule of its own that sets the title.
        if TITLE in self._candidates:
            for candidate in patterns:
                candidate.report.notes.append(
                    Note(TITLE, NoteKind.YIELDED, "another rule sets the title")
                )
        elif patterns:
            self._candidates[TITLE] = patterns
        self._single(TITLE, result)

    def _text_fields(
        self, result: Mapping[str, JsonValue], type_after: DocumentTypeId | None
    ) -> None:
        """The templates of text fields, with the contact, type and space the rules set (the
        fields as they were: rules do not see each other's fields)."""
        if not self._texts:
            return
        values = self._values(result, type_after, {}, None)
        for report, action, match in self._texts:
            name = field_key(action.field_id)
            rendered = self._render(report, name, str(action.value), values)
            if rendered is None:
                continue
            if not rendered.strip():
                report.notes.append(Note(name, NoteKind.SKIPPED, "the value would be empty"))
                continue
            value = rendered.strip()
            try:
                field_from_json(self._s.definitions[action.field_id], value)
            except ValidationError as error:
                report.notes.append(Note(name, NoteKind.SKIPPED, str(error)))
                continue
            self._candidates.setdefault(name, []).append(_Candidate(report, value, match))

    def _values(
        self,
        result: Mapping[str, JsonValue],
        type_after: DocumentTypeId | None,
        fields: Mapping[FieldId, object],
        tags: frozenset[TagId] | None,
    ) -> dict[str, TemplateValue]:
        """What templates see: the document as the rules leave it."""
        document, s = self._document, self._s
        contact = result.get(CONTACT, self._current(CONTACT))
        contact_id = None if contact is None else ContactId(UUID(str(contact)))
        topic = result.get(TOPIC, self._current(TOPIC))
        topic_id = None if topic is None else TagId(UUID(str(topic)))
        space = SpaceId(UUID(str(result[SPACE]))) if SPACE in result else document.space_id
        current: dict[FieldId, object] = {**document.fields, **fields}
        tree = s.taxonomy.tree

        def group_names(id: UUID | None) -> list[str]:
            return [tree.tags[tag].name for tag in s.taxonomy.groups_of(id) if tag in tree]

        return template_values(
            document,
            contact=None if contact_id is None else s.names.get(contact_id),
            document_type=None if type_after is None else s.names.get(type_after),
            space=s.names.get(space),
            uploaded_by=s.uploader_name,
            tags=[
                s.names[tag]
                for tag in (document.tag_ids if tags is None else tags)
                if tag in s.names
            ],
            contact_groups=group_names(contact_id),
            document_type_groups=group_names(type_after),
            topic=tree.tags[topic_id].name if topic_id is not None and topic_id in tree else None,
            document_date=document.document_date,
            fields=[
                (definition, _field_value(current.get(definition.id)))
                for definition in s.definitions.values()
                if definition.applies_to(type_after)
            ],
        )

    def _reason(self, template: str, values: Mapping[str, TemplateValue]) -> str:
        """A review's reason; as written where it cannot be rendered (the review holds)."""
        try:
            return " ".join(self._s.render(template, values).split()) or template
        except (MissingValueError, ValidationError):
            return template

    def _render(
        self,
        report: RuleReport,
        field_name: str,
        template: str,
        values: Mapping[str, TemplateValue],
    ) -> str | None:
        """The rendered template; None, and why in the report, if a value is missing or the
        template cannot be rendered."""
        try:
            return self._s.render(template, values)
        except (MissingValueError, ValidationError) as error:
            report.notes.append(Note(field_name, NoteKind.SKIPPED, str(error)))
            return None

    # --- helpers ------------------------------------------------------------------------------

    def _shown(self, field_name: str, value: JsonValue) -> str:
        """`value` of `field_name` as a reason names it: a contact, type, topic or space by its
        name, a title quoted, a field's value as written (`_value_text`); the id where no name
        is known."""
        s = self._s
        if value is None:
            return "none"
        if field_name in (CONTACT, DOCUMENT_TYPE, SPACE, TOPIC):
            try:
                id = UUID(str(value))
            except ValueError:
                return str(value)
            if field_name == TOPIC:
                return self._tag(TagId(id))
            name = s.names.get(id)
            return str(value) if name is None else f"'{name}'"
        if field_name == TITLE:
            return f"'{value}'"
        field = field_id_of(field_name)
        definition = None if field is None else s.definitions.get(field)
        return str(value) if definition is None else _value_text(definition, value)

    def _tag(self, tag: TagId) -> str:
        """A tag (of any scope) as a reason names it: its name quoted; its id if it is gone."""
        tree = self._s.taxonomy.tree
        name = tree.tags[tag].name if tag in tree else self._s.names.get(tag)
        return str(tag) if name is None else f"'{name}'"

    def _type_after(self, result: Mapping[str, JsonValue]) -> DocumentTypeId | None:
        if DOCUMENT_TYPE in result:
            return DocumentTypeId(UUID(str(result[DOCUMENT_TYPE])))
        return self._document.document_type_id

    def _current(self, field_name: str) -> JsonValue:
        document = self._document
        match field_name:
            case CheckField.CONTACT:
                return None if document.contact_id is None else str(document.contact_id)
            case CheckField.DOCUMENT_TYPE:
                return None if document.document_type_id is None else str(document.document_type_id)
            case CheckField.TOPIC:
                return None if document.topic_id is None else str(document.topic_id)
            case CheckField.SPACE:
                return str(document.space_id)
            case CheckField.TITLE:
                return document.title
            case CheckField.TAGS:
                return [str(tag) for tag in sorted(document.tag_ids)]
        if (field := field_id_of(field_name)) is not None:
            value = document.fields.get(field)
            return None if value is None else field_to_json(value)
        return None

    def _empty(self, field_name: str, current: JsonValue) -> bool:
        """For applying to existing documents: the field has no value of its own (a space
        counts as empty while the document lies in a personal space, a title as long as it is
        the file name or the machine's)."""
        if field_name == SPACE:
            return self._s.in_personal_space
        if field_name == TITLE:
            return current in (_default_title(self._document), self._s.machine_title)
        return current is None

    def _uncertain(self, field_name: str, reason: str, *, suggestion: JsonValue) -> None:
        existing = self._checks.get(field_name)
        if existing is not None and not existing.ok:
            reason = f"{existing.reason}; {reason}"
            suggestion = existing.suggestion if existing.suggestion is not None else suggestion
        self._checks[field_name] = FieldCheck(
            field=field_name,
            outcome=Outcome.UNCERTAIN,
            confidence=0,
            reason=reason,
            suggestion=suggestion,
        )


def _key(value: JsonValue) -> str:
    """Comparable form of a JSON value."""
    return repr(value)


def _value_text(definition: FieldDefinition, value: JsonValue) -> str:
    """A field's value (its JSON form) as written: text and choices quoted, numbers as they
    are, an amount with its currency, a date and a period in ISO 8601, yes or no."""
    try:
        parsed = field_from_json(definition, value)
    except ValidationError:
        return str(value)
    match parsed:
        case bool():
            return "yes" if parsed else "no"
        case str():
            return f"'{parsed}'"
        case Decimal():
            return decimal_text(parsed)
        case Money():
            return f"{decimal_text(parsed.amount)} {parsed.currency}"
        case Url():
            return parsed.value
        case Period():
            return parsed.notation
        case date():
            return parsed.isoformat()


def _field_value(value: object) -> FieldValue | None:
    match value:
        case str() | bool() | Decimal() | date() | Money() | Url() | Period():
            return value
    return None


def _default_title(document: Document) -> str:
    return document.file_title


def changed_fields(changes: DocumentChanges) -> frozenset[str]:
    """The fields a change sets (given, not left unset), named as in field checks."""
    given: set[str] = {
        field_name
        for field_name, attribute in CHANGE_FIELDS.items()
        if not isinstance(getattr(changes, attribute), Unset)
    }
    given.update(field_key(id) for id in changes.fields)
    return frozenset(given)
