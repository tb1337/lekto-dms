"""The inbox: what stands in whose inbox, by tab (`domain.inbox`), and seen per user
(`InboxService`); what is open in a yellow or red document, and how an editor's decision on the
open fields turns into a metadata change.

What the signals proposed and how each field was checked lies in the processing log (output
of the judge and the fields node). These functions read it from there; the rules (M7) use
`field_checks` for the values of the latest run.
"""

import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any
from uuid import UUID

from lekto.core.domain.classification import (
    CHANGE_FIELDS,
    CHECKS,
    CONTACT,
    REVIEW,
    SPACE,
    TITLE,
    CheckField,
    FieldCheck,
    checks_from_json,
    field_id_of,
)
from lekto.core.domain.documents import Document, DocumentChanges, Unset
from lekto.core.domain.errors import OpenFieldsError, ValidationError
from lekto.core.domain.fields import FieldDefinition, field_from_json
from lekto.core.domain.ids import (
    ContactId,
    DocumentId,
    DocumentTypeId,
    FieldId,
    SpaceId,
    TagId,
    UserId,
)
from lekto.core.domain.inbox import (
    DONE_PERIOD,
    OPEN_TABS,
    InboxState,
    InboxTab,
    inbox_state,
    is_unseen,
    left_at,
    open_tab,
    worst_lane,
)
from lekto.core.domain.json_value import JsonObject, JsonValue
from lekto.core.domain.permissions import can_edit_document, document_access
from lekto.core.domain.pipeline import (
    ACCEPTED,
    CONFIRMED_BY,
    ENTERED,
    KEPT,
    NODES,
    PERSON,
    TRUNCATED,
    Lane,
    Node,
    NodeResult,
    NodeRun,
    Outcome,
    ProcessingHistory,
)
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import User
from lekto.core.ports.clock import Clock
from lekto.core.ports.repository import PAGE_LIMIT, PAGE_SIZE, InboxPosition
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import (
    load_actor,
    load_lister,
    readable_document,
    readable_log,
)

log = logging.getLogger(__name__)

ALWAYS_SET = frozenset({SPACE, TITLE, REVIEW})
"""Open fields of the rules that always have a value: confirming keeps it."""

MODEL_NODES = (Node.JUDGE, Node.FIELDS)
"""The nodes whose output holds field checks."""


@dataclass(frozen=True)
class OpenNode:
    """A node whose result is uncertain or failed: why, and the fields an editor has to decide
    (uncertain fields of the judge or the fields node; none for other nodes)."""

    node: Node
    outcome: Outcome
    reason: str | None
    fields: tuple[FieldCheck, ...] = ()


@dataclass(frozen=True)
class NodeReview:
    """The latest run of a model node: what was sent, what came back and how it was checked."""

    node: Node
    run: int
    outcome: Outcome
    reason: str | None
    model_version: str | None
    truncated: bool | None
    fields: tuple[FieldCheck, ...]


@dataclass(frozen=True)
class InboxItem:
    """A document in the caller's inbox: where it stands (with how it left, under done), and
    what is open in it."""

    document: Document
    access: SpaceRole  # the caller's, as in `DocumentView`
    open: tuple[OpenNode, ...]
    state: InboxState


@dataclass(frozen=True)
class InboxSummary:
    """How many documents stand under each tab of the caller's inbox, and the worst lane among
    the open ones (`domain.inbox.worst_lane`)."""

    counts: Mapping[InboxTab, int]
    worst_lane: Lane | None

    @property
    def open(self) -> int:
        """Everything open: what the badge counts."""
        return sum(self.counts.get(tab, 0) for tab in OPEN_TABS)


@dataclass(frozen=True)
class Review:
    document: Document
    access: SpaceRole  # the caller's, as in `DocumentView`
    open: tuple[OpenNode, ...]
    nodes: tuple[NodeReview, ...]


@dataclass(frozen=True)
class Decision:
    """A person's decision on the open fields: the change to apply, and which fields were
    accepted as suggested, entered by the person, or kept with the value the document has, by
    node."""

    changes: DocumentChanges
    accepted: Mapping[Node, tuple[str, ...]]
    entered: Mapping[Node, tuple[str, ...]]
    kept: Mapping[Node, tuple[str, ...]]


def latest_entries(log: Sequence[NodeRun], *, by_model: bool = False) -> dict[Node, NodeRun]:
    """The latest log entry of each node written by processing, in graph order; with
    `by_model`, leaving out confirmations too (`ProcessingHistory.latest`)."""
    history = ProcessingHistory(log)
    latest = {node: history.latest(node, by_model=by_model) for node in NODES}
    return {node: entry for node, entry in latest.items() if entry is not None}


def field_checks(log: Sequence[NodeRun]) -> dict[str, FieldCheck]:
    """The field checks of the latest judge and fields node, by field."""
    latest = latest_entries(log, by_model=True)
    checks: dict[str, FieldCheck] = {}
    for node in MODEL_NODES:
        if node in latest:
            checks.update((check.field, check) for check in _checks(latest[node].result))
    return checks


def open_nodes(document: Document, log: Sequence[NodeRun]) -> tuple[OpenNode, ...]:
    """The uncertain and failed nodes of the document's current state, in graph order."""
    latest = latest_entries(log)
    result = []
    for node in NODES:
        outcome = document.processing.outcome(node)
        if outcome not in (Outcome.UNCERTAIN, Outcome.FAILED):
            continue
        entry = latest.get(node)
        reason = entry.result.reason if entry is not None else None
        fields: tuple[FieldCheck, ...] = ()
        if entry is not None and outcome is Outcome.UNCERTAIN:
            fields = tuple(check for check in _checks(entry.result) if not check.ok)
        result.append(OpenNode(node, outcome, reason, fields))
    return tuple(result)


def node_reviews(log: Sequence[NodeRun]) -> tuple[NodeReview, ...]:
    latest = latest_entries(log, by_model=True)
    reviews = []
    for node in MODEL_NODES:
        entry = latest.get(node)
        if entry is None:
            continue
        truncated = entry.result.input.get(TRUNCATED)
        reviews.append(
            NodeReview(
                node=node,
                run=entry.run,
                outcome=entry.result.outcome,
                reason=entry.result.reason,
                model_version=entry.result.model_version,
                truncated=truncated if isinstance(truncated, bool) else None,
                fields=tuple(_checks(entry.result)),
            )
        )
    return tuple(reviews)


def decide(
    open: Sequence[OpenNode],
    document: Document,
    changes: DocumentChanges,
    *,
    accept_suggestions: bool,
    definitions: Mapping[FieldId, FieldDefinition],
    given: Collection[str] = (),
) -> Decision:
    """Every open field needs a decision: a value (or None) in `changes` (or named in `given`,
    such as the space), a value the document has (a person set it meanwhile; it is kept), or,
    with `accept_suggestions`, a suggestion that can be taken as it is. Suggestions never
    replace a value. OpenFieldsError lists the fields without a decision. Fields whose definition
    no longer exists need none. The rules' space, title and review always have a value:
    confirming keeps them."""
    accepted: dict[Node, list[str]] = {}
    entered: dict[Node, list[str]] = {}
    kept: dict[Node, list[str]] = {}
    suggested: dict[str, Any] = {}
    fields = dict(changes.fields)
    undecided: list[str] = []
    for item in open:
        for check in item.fields:
            field_id = field_id_of(check.field)
            if field_id is not None and field_id not in definitions:
                continue
            if _left_empty_by_hand(check, field_id, changes, definitions):
                # A required field set by hand needs its value; none is no decision.
                undecided.append(_label(check.field, field_id, definitions))
            elif check.field in given or _given(changes, check.field, field_id):
                entered.setdefault(item.node, []).append(check.field)
            elif _has_value(document, check.field, field_id):
                kept.setdefault(item.node, []).append(check.field)
            elif accept_suggestions and check.suggestion is not None:
                value = _suggested(check, field_id, definitions)
                if field_id is not None:
                    fields[field_id] = value
                else:
                    suggested[check.field] = value
                accepted.setdefault(item.node, []).append(check.field)
            else:
                undecided.append(_label(check.field, field_id, definitions))
    if undecided:
        raise OpenFieldsError(tuple(undecided))
    combined = replace(
        changes,
        fields=fields,
        **{CHANGE_FIELDS[name]: value for name, value in suggested.items()},
    )
    return Decision(
        changes=combined,
        accepted={node: tuple(fields) for node, fields in accepted.items()},
        entered={node: tuple(fields) for node, fields in entered.items()},
        kept={node: tuple(fields) for node, fields in kept.items()},
    )


LEARNED_ALIAS = "learned_alias"
"""Key of the alias a confirmation taught a contact, in the output of its `apply_rules` entry."""
_LONGEST_ALIAS = 100  # characters; longer proposals are not learned


def alias_to_learn(
    open: Sequence[OpenNode], decision: Decision, document: Document
) -> tuple[ContactId, str] | None:
    """The contact a person chose for an open contact field, and the name the model read for
    it: the person entered the contact or accepted the suggestion. None if the field was not
    open, the model read no name, or the document has no contact."""
    for item in open:
        if item.node is not Node.JUDGE:
            continue
        decided = (*decision.entered.get(item.node, ()), *decision.accepted.get(item.node, ()))
        for check in item.fields:
            if check.field != CONTACT or CONTACT not in decided:
                continue
            proposed = check.proposed
            if (
                isinstance(proposed, str)
                and proposed.strip()
                and len(proposed) <= _LONGEST_ALIAS
                and document.contact_id is not None
            ):
                return document.contact_id, proposed.strip()
    return None


def confirmation(
    node: Node, before: Outcome | None, decision: Decision, confirmed_by: UUID
) -> NodeResult:
    """The log entry's result for a node a person confirmed."""
    output: JsonObject = {
        CONFIRMED_BY: str(confirmed_by),
        "outcome_before": None if before is None else before.value,
        ACCEPTED: list(decision.accepted.get(node, ())),
        ENTERED: list(decision.entered.get(node, ())),
        KEPT: list(decision.kept.get(node, ())),
    }
    return NodeResult(outcome=Outcome.OK, model_version=PERSON, output=output)


def _checks(result: NodeResult) -> list[FieldCheck]:
    try:
        return checks_from_json(result.output.get(CHECKS))
    except ValidationError:
        return []


def _given(changes: DocumentChanges, field: str, field_id: FieldId | None) -> bool:
    if field_id is not None:
        return field_id in changes.fields
    name = CHANGE_FIELDS.get(field)
    return name is not None and not isinstance(getattr(changes, name), Unset)


def _left_empty_by_hand(
    check: FieldCheck,
    field_id: FieldId | None,
    changes: DocumentChanges,
    definitions: Mapping[FieldId, FieldDefinition],
) -> bool:
    """Whether `check` is a field set by hand that `changes` leaves empty."""
    if field_id is None or field_id not in changes.fields or changes.fields[field_id] is not None:
        return False
    return not definitions[field_id].is_read


def _has_value(document: Document, field: str, field_id: FieldId | None) -> bool:
    if field in ALWAYS_SET:
        return True
    if field_id is not None:
        return field_id in document.fields
    name = CHANGE_FIELDS.get(field)
    return name is not None and getattr(document, name) not in (None, set())


def _suggested(
    check: FieldCheck,
    field_id: FieldId | None,
    definitions: Mapping[FieldId, FieldDefinition],
) -> object:
    value: JsonValue = check.suggestion
    try:
        if field_id is not None:
            return field_from_json(definitions[field_id], value)
        match check.field:
            case CheckField.CONTACT:
                return ContactId(UUID(str(value)))
            case CheckField.DOCUMENT_TYPE:
                return DocumentTypeId(UUID(str(value)))
            case CheckField.TOPIC:
                return TagId(UUID(str(value)))
            case CheckField.TAGS if isinstance(value, list):
                return frozenset(TagId(UUID(str(item))) for item in value)
            case CheckField.DOCUMENT_DATE:
                return date.fromisoformat(str(value))
    except ValueError:
        pass
    raise ValidationError(f"the suggestion for {check.field} cannot be taken: {value!r}")


def _label(
    field: str,
    field_id: FieldId | None,
    definitions: Mapping[FieldId, FieldDefinition],
) -> str:
    if field_id is None:
        return field
    return f"{field} ({definitions[field_id].name})"


class InboxService:
    """The inbox (`domain.inbox`): what stands in the caller's, by tab, newest first; its
    summary; seen per user. An admin with `all_users` has every user's inbox, with their own
    seen. Seen changes nothing but the inbox: not `confirmed_at`, the training, rules or the
    lane."""

    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def items(
        self,
        actor: UserId,
        *,
        tab: InboxTab | None = None,
        after: DocumentId | None = None,
        limit: int = PAGE_SIZE,
        all_users: bool = False,
    ) -> list[InboxItem]:
        """The documents under `tab` of the caller's inbox (None: under any open tab), newest
        first (by arrival; under done by when they left), after the page ending at the document
        `after`; with `all_users` (admins only), of every user. Each with what is open in it,
        and under done how, when and by whom it left. ValidationError for a page of done after
        a document that is no longer done (seen marks taken back)."""
        limit = max(1, min(limit, PAGE_LIMIT))
        async with self._uow() as uow:
            user = await load_lister(uow, actor, all_users, "see the inboxes of all users")
            since = self._clock.now() - DONE_PERIOD
            entries = await uow.inbox.query(
                actor,
                editor=None if all_users else actor,
                tab=tab,
                since=since,
                after=await _position(uow, actor, tab, after),
                limit=limit,
            )
            spaces: dict[SpaceId, Space] = {}
            items = []
            for entry in entries:
                document = entry.document
                state = inbox_state(
                    document,
                    viewer=actor,
                    seen_at=entry.seen_at,
                    confirmation=entry.confirmation,
                    since=since,
                    silent=entry.silent,
                )
                if state is None:
                    log.error(
                        "the repository listed a document that is not in the inbox",
                        extra={"document_id": str(document.id), "user_id": str(actor)},
                    )
                    continue
                if document.space_id not in spaces:
                    spaces[document.space_id] = await uow.spaces.get(document.space_id)
                access = document_access(user, document, spaces[document.space_id])
                assert access is not None  # an editor's, or any to an admin
                items.append(InboxItem(document, access, await _open(uow, user, document), state))
        return items

    async def summary(self, actor: UserId, *, all_users: bool = False) -> InboxSummary:
        """How many documents stand under each tab of the caller's inbox (with `all_users`,
        admins only: every user's), and the worst lane among the open ones."""
        async with self._uow() as uow:
            await load_lister(uow, actor, all_users, "see the inboxes of all users")
            counts = await uow.inbox.count(
                actor,
                editor=None if all_users else actor,
                since=self._clock.now() - DONE_PERIOD,
            )
        return InboxSummary(counts, worst_lane(counts))

    async def mark_seen(self, actor: UserId, id: DocumentId) -> None:
        """The caller saw the document: the web UI reports it when the document view opens
        (reading a document through the API or MCP does not). NotFoundError if they cannot read
        it. Only a document that is new and unseen by the caller counts: one they saw since it
        became new keeps when they saw it (it left their inbox then), and nothing changes for
        one that is new for no one, or that cannot stand in the caller's inbox (a document in
        reach through reading its space only)."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document, space = await readable_document(uow, user, id)
            if document.new_at is None or not can_edit_document(user, document, space):
                return
            seen = await uow.inbox.seen(actor, [id])
            if not is_unseen(document, seen.get(id)):
                return
            await uow.inbox.mark_seen(actor, id, self._clock.now())
            await uow.commit()

    async def mark_unseen(self, actor: UserId, id: DocumentId) -> None:
        """Mark the document as new again: the caller's seen is forgotten, and it stands new in
        their inbox while it is new. NotFoundError if they cannot read it."""
        async with self._uow() as uow:
            await readable_document(uow, await load_actor(uow, actor), id)
            await uow.inbox.unmark_seen(actor, id)
            await uow.commit()

    async def mark_all_seen(self, actor: UserId, *, all_users: bool = False) -> int:
        """Mark everything new in the caller's inbox (with `all_users`, admins only: in every
        user's) as seen by them; returns how many documents."""
        async with self._uow() as uow:
            await load_lister(uow, actor, all_users, "see the inboxes of all users")
            count = await uow.inbox.mark_all_seen(
                actor, editor=None if all_users else actor, at=self._clock.now()
            )
            await uow.commit()
        return count


async def in_inbox(
    uow: UnitOfWork, viewer: UserId, documents: Sequence[Document], *, all_users: bool
) -> set[DocumentId]:
    """Those of `documents` that stand open in `viewer`'s inbox (with `all_users`, an admin's:
    of every user), for marking them in lists and search: one query for the viewer's seen marks
    of the new ones."""
    edited: set[SpaceId] = set()
    if not all_users:
        edited = {
            space.id
            for space in await uow.spaces.list_accessible(viewer)
            if space.role_of(viewer) is SpaceRole.EDIT
        }
    theirs = [document for document in documents if all_users or document.space_id in edited]
    new = [item.id for item in theirs if item.lane is Lane.GREEN and item.new_at is not None]
    seen = await uow.inbox.seen(viewer, new) if new else {}
    return {item.id for item in theirs if open_tab(item, seen.get(item.id)) is not None}


async def arrived(
    uow: UnitOfWork, document: Document, source: Space, now: datetime, by: UserId | None = None
) -> None:
    """`document` was moved out of `source` into the space it lies in now: while green, it is
    new for the editors there who could not read it before. The members of `source` keep
    their state (whoever had nothing new in it is marked as having seen it now, moving is no
    seeing); `by`, who moved it from outside the space (an admin), has seen it. These marks
    are silent: the document does not stand under done for anyone who did not look at it
    (Tobi, 22.10.2026)."""
    if document.lane is not Lane.GREEN:
        return
    unseen = {
        user: is_unseen(document, (await uow.inbox.seen(user, [document.id])).get(document.id))
        for user in source.members
    }
    document.mark_new(now)
    outside = [] if by is None or by in source.members else [by]
    for user in [*(user for user, new in unseen.items() if not new), *outside]:
        await uow.inbox.mark_seen(user, document.id, now, silent=True)


async def confirmed_into(
    uow: UnitOfWork, document: Document, source: Space, target: Space, now: datetime, by: UserId
) -> None:
    """`document`, decided in the inbox by `by`, was moved out of `source` into `target`: once
    processing ends green it is new for the editors of `target` who could not read it in
    `source`, where it waited for a decision (a hand-over arrives as new for the receiver).
    The editors of `source` had it before them (a silent mark: done only for who decided);
    `by` decided it; confirming makes it new for no one else."""
    newcomers = target.editors - source.editors - {by}
    if not newcomers:
        return
    document.mark_new(now)
    for user in sorted(source.editors - {by}, key=str):
        await uow.inbox.mark_seen(user, document.id, now, silent=True)
    await uow.inbox.mark_seen(by, document.id, now)


async def _position(
    uow: UnitOfWork, viewer: UserId, tab: InboxTab | None, after: DocumentId | None
) -> InboxPosition | None:
    """Where a page of the inbox ended: by the last document's id, and under done when it left
    the viewer's inbox (`domain.inbox.left_at`), looked up as `GET /documents` looks up a sort
    value."""
    if after is None:
        return None
    if tab is not InboxTab.DONE:
        return InboxPosition(after)
    entry = await uow.inbox.entry(viewer, after)
    left = (
        None
        if entry is None
        else left_at(entry.document, None if entry.silent else entry.seen_at, entry.confirmation)
    )
    if left is None:
        raise ValidationError("cursor: its document is no longer done; start from the first page")
    return InboxPosition(after, left)


async def _open(uow: UnitOfWork, user: User, document: Document) -> tuple[OpenNode, ...]:
    """What is open in the document, as `user` may see it (`_access.readable_log`); its log is
    read only if a node is uncertain or failed."""
    outcomes = document.processing.outcomes.values()
    if not any(outcome in (Outcome.UNCERTAIN, Outcome.FAILED) for outcome in outcomes):
        return ()
    entries = await readable_log(uow, user, await uow.processing_log.list_for(document.id))
    return open_nodes(document, entries)
