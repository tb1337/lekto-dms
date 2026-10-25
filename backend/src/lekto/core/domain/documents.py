"""The document aggregate: metadata, processing state machine and lane."""

import hashlib
import json
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum, StrEnum
from pathlib import PurePath
from typing import Self

from lekto.core.domain.classification import (
    CHANGE_FIELDS,
    CONFIRMING,
    CONTACT,
    CUSTOM_FIELDS,
    DOCUMENT_DATE,
    DOCUMENT_TYPE,
    TAGS,
    TITLE,
    TOPIC,
)
from lekto.core.domain.errors import InvalidTransitionError, NotFoundError, ValidationError
from lekto.core.domain.events import (
    DocumentConfirmed,
    DocumentDeleted,
    DocumentEvent,
    DocumentFiled,
    DocumentMoved,
    DocumentReceived,
    DocumentUpdated,
    LaneChanged,
    NodeCompleted,
    NodeDeferred,
    NodeDelegated,
    NodeStarted,
    ReviewRequired,
)
from lekto.core.domain.fields import FieldDefinition, FieldValue, field_to_json
from lekto.core.domain.ids import (
    ContactId,
    DocumentId,
    DocumentTypeId,
    FieldId,
    SpaceId,
    TagId,
    UserId,
    new_id,
)
from lekto.core.domain.pipeline import (
    CURRENT_SIGNALS,
    NOT_GREEN,
    SIGNALS,
    Lane,
    Node,
    NodeResult,
    NodeState,
    NodeStatus,
    Outcome,
    Processing,
    ProcessingStatus,
)
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.validation import require_name, require_utc

_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Sha256:
    """SHA-256 of a document's original, lower-case hex. Also the original's object key."""

    hex: str

    def __post_init__(self) -> None:
        if not isinstance(self.hex, str) or not _SHA256.fullmatch(self.hex):
            raise ValidationError(f"invalid SHA-256 {self.hex!r}")

    @classmethod
    def of(cls, data: bytes) -> Self:
        return cls(hashlib.sha256(data).hexdigest())

    def __str__(self) -> str:
        return self.hex


MAX_TITLE = 500
"""Characters of a document's title; the REST schemas, the MCP tool and the model's answers
keep to it."""


class Channel(StrEnum):
    """How a document came in (its intake channel). Further connectors (mail, folder) follow."""

    WEB = "web"  # uploaded with a session (web UI)
    API = "api"  # uploaded with an API token
    MIGRATION = "migration"  # taken over from Paperless-ngx


class Unset(Enum):
    UNSET = "unset"


UNSET = Unset.UNSET
"""Marks a field of DocumentChanges that is left as it is."""


@dataclass(frozen=True, kw_only=True)
class DocumentChanges:
    """A metadata change. Fields left UNSET stay unchanged.

    `fields` maps field ids to new raw values (checked against the definition) or to
    None to remove the value.
    """

    title: str | Unset = UNSET
    contact_id: ContactId | Unset | None = UNSET
    document_type_id: DocumentTypeId | Unset | None = UNSET
    tag_ids: frozenset[TagId] | Unset = UNSET
    document_date: date | Unset | None = UNSET
    fields: Mapping[FieldId, object] = field(default_factory=dict)
    topic_id: TagId | Unset | None = UNSET
    # When the document came in (`Document.created_at`, the receipt): a person corrects it,
    # say, for a letter scanned days after it arrived. Not in the future.
    created_at: datetime | Unset = UNSET

    @property
    def only_receipt(self) -> bool:
        """Whether all it changes is when the document came in: no metadata a person
        confirms, and nothing the rules decide on."""
        return (
            self.created_at is not UNSET
            and not self.fields
            and all(
                value is UNSET
                for value in (
                    self.title,
                    self.contact_id,
                    self.document_type_id,
                    self.tag_ids,
                    self.document_date,
                    self.topic_id,
                )
            )
        )


RECEIPT = "created_at"
"""The attribute of `Document` and `DocumentChanges` that holds when the document came in, as
`Document.apply_changes` names it among the changed fields."""


def received_at(value: datetime, now: datetime) -> datetime:
    """When a document came in, as given (by a person, or a migration from the source
    system): in UTC and not in the future."""
    value = require_utc(value, RECEIPT)
    if value > now:
        raise ValidationError(because(ReasonCode.RECEIPT_IN_FUTURE))
    return value


def confirms(
    changed: Collection[str],
    tags_before: Collection[TagId],
    tags_after: Collection[TagId],
    manual: Collection[TagId],
) -> bool:
    """Whether a person's change confirms the metadata: it changed a value in `CONFIRMING`
    (`changed` as `Document.apply_changes` names them), unless all it changed are tags set by
    hand (`manual`), added or removed. A status tag such as "to pay" says nothing about contact
    and type; a change that also adds or removes an automatic tag, or changes any other
    confirming value, confirms."""
    touched = CONFIRMING & set(changed)
    if touched != {CHANGE_FIELDS[TAGS]}:
        return bool(touched)
    return not set(tags_before) ^ set(tags_after) <= set(manual)


def checked_fields(
    changes: DocumentChanges,
    definitions: Mapping[FieldId, FieldDefinition],
    document_type_id: DocumentTypeId | None,
) -> dict[FieldId, FieldValue]:
    """The field values `changes` sets, checked against their definitions and the document
    type after the change; a field it removes (None) needs a definition, but no check.
    NotFoundError for a field without a definition, ValidationError for a value that does not
    fit its definition or a field that does not apply to the type."""
    checked: dict[FieldId, FieldValue] = {}
    for field_id, raw in changes.fields.items():
        definition = _definition(definitions, field_id)
        if raw is None:
            continue
        if not definition.applies_to(document_type_id):
            raise ValidationError(because(ReasonCode.FIELD_NOT_FOR_TYPE, field=definition.name))
        checked[field_id] = definition.validate(raw)
    return checked


@dataclass(kw_only=True)
class Document:
    """A file with metadata.

    Invariants: exactly one space; at most one contact, one document type and one topic (a
    tag of scope `topic` its contact enables; the services see to that, `_access`); field
    values fit their definition, and type-bound fields only exist while the document has a
    matching type. `lane` is None while the pipeline runs and is set when it completes or
    fails; `first_lane` keeps the lane the first run ended in.

    State changes record domain events; `pull_events()` hands them over for the outbox.
    """

    id: DocumentId
    # Who put it into Lekto: information only, no rights come with it (`permissions`); None
    # once their account is deleted.
    uploaded_by: UserId | None
    space_id: SpaceId
    sha256: Sha256
    title: str
    original_filename: str
    media_type: str
    contact_id: ContactId | None = None
    document_type_id: DocumentTypeId | None = None
    topic_id: TagId | None = None
    tag_ids: set[TagId] = field(default_factory=set)
    fields: dict[FieldId, FieldValue] = field(default_factory=dict)
    document_date: date | None = None
    channel: Channel = Channel.API
    lane: Lane | None = None
    # The lane its first processing run ended in by itself (`record_result`), kept for good:
    # neither a person's confirmation nor a later run changes it, so reports can tell how many
    # documents went through without a person. None while the first run runs, and for documents
    # whose first run is not known (from before revision 0036, if their log does not tell).
    first_lane: Lane | None = None
    processing: Processing
    page_count: int | None = None  # known once the pages node has rendered the page images
    # When a person last set or confirmed its metadata (in the inbox, or by changing contact,
    # type, topic, tags, date or fields; tags set by hand alone do not count, `confirms`), or
    # it was taken over with the source system's; None while its metadata is the pipeline's
    # own. Confirmed documents train the classifier.
    confirmed_at: datetime | None = None
    # When a person last decided its space: confirmed it in the inbox, moved or handed it over,
    # chose it on upload, or it was taken over from the source system (its permissions). None
    # while the space is where it landed or where the pipeline put it. A decided space trains
    # the classifier's space and the judge leaves it (`verdict.judge_space`).
    space_confirmed_at: datetime | None = None
    # When processing last made it new for the inbox: a run ended green without a person's
    # decision in it (`Processing.decided`) that started on a document that was not green (its
    # first run, a retry from red, a reprocessing of a yellow one), or on a green one whose
    # metadata differ afterwards (`Processing.baseline`). None: new for no one (a person
    # confirmed it out of yellow or red since, or it never was; documents from before 0.4).
    # Who saw it since is per user (`domain.inbox`).
    new_at: datetime | None = None
    # When it came in: when it was received, unless a migration took over the source system's
    # date or a person corrected it since (`DocumentChanges.created_at`). The id still tells
    # when Lekto received it.
    created_at: datetime
    updated_at: datetime
    version: int = 1
    _events: list[DocumentEvent] = field(
        default_factory=list, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        self.title = require_name(self.title, "title", max_length=MAX_TITLE)
        self.original_filename = require_name(
            self.original_filename, "original filename", max_length=None
        )
        self.media_type = require_name(self.media_type, "media type", max_length=None)
        self.created_at = require_utc(self.created_at, "created_at")
        self.updated_at = require_utc(self.updated_at, "updated_at")
        if self.new_at is not None:
            self.new_at = require_utc(self.new_at, "new_at")
        if self.space_confirmed_at is not None:
            self.space_confirmed_at = require_utc(self.space_confirmed_at, "space_confirmed_at")

    # --- creation -------------------------------------------------------------------------------

    @property
    def file_title(self) -> str:
        """The name of the file it came in without the extension: the title it is received
        with."""
        return file_title(self.original_filename)

    @classmethod
    def receive(
        cls,
        *,
        uploaded_by: UserId | None,
        space_id: SpaceId,
        sha256: Sha256,
        original_filename: str,
        media_type: str,
        result: NodeResult,
        now: datetime,
        channel: Channel = Channel.API,
        received: datetime | None = None,
        space_chosen: bool = False,
    ) -> Self:
        """A newly received document. The receive node (hash, duplicate check, storage) is done;
        the nodes after it are due. `received`: when it came in, if not now (a migration takes
        over the source system's date). `space_chosen`: a person chose its space on upload."""
        if result.outcome is Outcome.FAILED:
            raise ValidationError("a document whose receive node failed is not created")
        filename = require_name(original_filename, "original filename", max_length=None)
        document = cls(
            id=DocumentId(new_id()),
            uploaded_by=uploaded_by,
            space_id=space_id,
            sha256=sha256,
            title=file_title(filename),
            original_filename=filename,
            media_type=media_type,
            channel=channel,
            processing=Processing.new(),
            space_confirmed_at=now if space_chosen else None,
            created_at=now if received is None else received_at(received, now),
            updated_at=now,
        )
        document._record(DocumentReceived(document_id=document.id, occurred_at=now))
        document.record_result(Node.RECEIVE, 1, result, now)
        return document

    # --- processing state machine ---------------------------------------------------------------

    def is_awaiting(self, node: Node, run: int) -> bool:
        """True if `node` of processing run `run` may run or is running; otherwise a job for it
        is stale. After a failure, the nodes still running finish, but nothing new starts."""
        processing = self.processing
        if run != processing.run:
            return False
        if processing.nodes[node].status is NodeStatus.RUNNING:
            return processing.status in (ProcessingStatus.PROCESSING, ProcessingStatus.FAILED)
        return processing.status is ProcessingStatus.PROCESSING and node in processing.due()

    def start_node(self, node: Node, run: int, now: datetime) -> None:
        """A worker takes the due node up (again, after a lost lease or a deferral)."""
        self._require_awaiting(node, run)
        self.processing.nodes[node] = NodeState(status=NodeStatus.RUNNING, started_at=now)
        self._record(NodeStarted(document_id=self.id, occurred_at=now, node=node, run=run))
        self._touch(now)

    def defer_node(self, node: Node, run: int, retry_at: datetime, now: datetime) -> None:
        """An attempt of the running node failed with an error: it waits until `retry_at`,
        when a worker takes it up again (`start_node`)."""
        self._require_awaiting(node, run)
        if self.processing.nodes[node].status is not NodeStatus.RUNNING:
            raise InvalidTransitionError(f"document {self.id}: node {node} is not running")
        self.processing.nodes[node] = NodeState()
        self._record(
            NodeDeferred(
                document_id=self.id, occurred_at=now, node=node, run=run, retry_at=retry_at
            )
        )
        self._touch(now)

    def delegate_node(self, node: Node, run: int, deadline: datetime | None, now: datetime) -> None:
        """The running node handed work to tasks: it waits for their answers without a worker
        ("running externally") until `resume_node`. `deadline`: when the last of its open
        tasks ends at the latest (None while they wait to be sent)."""
        self._require_awaiting(node, run)
        state = self.processing.nodes[node]
        if state.status is not NodeStatus.RUNNING:
            raise InvalidTransitionError(f"document {self.id}: node {node} is not running")
        self.processing.nodes[node] = NodeState(
            status=NodeStatus.DELEGATED, started_at=state.started_at, deadline=deadline
        )
        self._record(
            NodeDelegated(
                document_id=self.id, occurred_at=now, node=node, run=run, deadline=deadline
            )
        )
        self._touch(now)

    def resume_node(self, node: Node, run: int, now: datetime) -> bool:
        """A task of `node` in `run` was answered, ended or may be sent now: a delegated node
        is due again and runs anew with what its tasks brought. Returns whether it is due (a
        job is to run it). In any other state the document is only touched, so a run of the
        node that read its tasks before this change stores nothing (its version is stale) and
        reads them again."""
        self._touch(now)
        processing = self.processing
        if run != processing.run or processing.nodes[node].status is not NodeStatus.DELEGATED:
            return False
        processing.nodes[node] = NodeState()
        return processing.status is ProcessingStatus.PROCESSING and node in processing.due()

    def record_result(
        self, node: Node, run: int, result: NodeResult, now: datetime
    ) -> tuple[Node, ...]:
        """Store the result of a due or running node (a due node that was not started counts
        as started now). Returns the nodes that became due with it."""
        self._require_awaiting(node, run)
        processing = self.processing
        state = processing.nodes[node]
        processing.nodes[node] = NodeState(
            status=NodeStatus.DONE,
            outcome=result.outcome,
            started_at=state.started_at or now,
            finished_at=now,
        )
        self._record(
            NodeCompleted(
                document_id=self.id, occurred_at=now, node=node, run=run, outcome=result.outcome
            )
        )
        self._touch(now)
        if result.outcome is Outcome.FAILED:
            processing.status = ProcessingStatus.FAILED
            self._stopped(Lane.RED, now)
            return ()
        if processing.status is ProcessingStatus.FAILED:
            return ()  # a node that was still running after another failed
        if node is Node.FILE and result.outcome is Outcome.OK:
            self._record(
                DocumentFiled(document_id=self.id, occurred_at=now, space_id=self.space_id)
            )
        due = processing.due()
        if not due:
            if processing.is_open():
                return ()  # the rest waits for nodes still running
            processing.status = ProcessingStatus.COMPLETED
            lane = Lane.from_outcomes(processing.outcomes.values())
            self._stopped(lane, now)
            if lane is Lane.GREEN and self._becomes_new():
                self.new_at = now
            return ()
        if Node.FILE in due and self._uncertain_before(Node.FILE):
            # Filed only once an editor has confirmed what is uncertain.
            processing.status = ProcessingStatus.REVIEW
            self._stopped(Lane.YELLOW, now)
            return ()
        return tuple(following for following in due if node in following.requires)

    def retry(self, now: datetime) -> tuple[Node, ...]:
        """Repeat the failed nodes; processing then continues with the nodes after them.
        Returns the nodes that are due now."""
        if self.processing.status is not ProcessingStatus.FAILED:
            raise InvalidTransitionError(because(ReasonCode.ONLY_FAILED_RETRIED, id=str(self.id)))
        return self._reset(set(self.processing.failed()), now)

    def reprocess_from(self, node: Node, now: datetime) -> tuple[Node, ...]:
        """Discard the results of `node` and the nodes after it and process them again.
        Signals `node` needs that were skipped (a document from before they existed) run first,
        and so do those that ask no language model (`CURRENT_SIGNALS`): the judge sees the
        master data, the model and the index as they are now. Returns the nodes that are due
        now."""
        processing = self.processing
        if processing.status is ProcessingStatus.PROCESSING:
            raise InvalidTransitionError(because(ReasonCode.BEING_PROCESSED, id=str(self.id)))
        if node is Node.RECEIVE:
            raise InvalidTransitionError(because(ReasonCode.RECEIVE_NOT_REPEATABLE))
        again = self._reset_set({node})
        skipped = [failed for failed in processing.failed() if failed not in again]
        if skipped:
            raise InvalidTransitionError(because(ReasonCode.CANNOT_SKIP, nodes=skipped))
        if node is Node.FILE and self._uncertain_before(Node.FILE):
            raise InvalidTransitionError(
                because(ReasonCode.UNCERTAIN_BEFORE_FILING, id=str(self.id))
            )
        signals = {
            signal
            for signal in node.requires & SIGNALS
            if signal in CURRENT_SIGNALS or processing.nodes[signal].status is NodeStatus.SKIPPED
        }
        processing.vision = False
        return self._reset({node, *signals}, now)

    def read_with_vision(self, now: datetime) -> tuple[Node, ...]:
        """A person asked that the vision language model read the pages: process again from
        OCR, which reads every page with the model in this run and its retries. As
        `reprocess_from`; returns the nodes that are due now."""
        due = self.reprocess_from(Node.OCR, now)
        self.processing.vision = True
        return due

    def confirm(self, resume_at: Node, now: datetime) -> tuple[Node, ...]:
        """A person has decided what was uncertain or failed (the inbox): the results of the
        nodes that are not run again count as OK from now on, processing runs again from
        `resume_at` (applying rules, or extracting fields after a type correction) up to filing.
        Nodes that never ran and are not needed to resume run now, and so do the pages that
        never ran (after a failed OCR): the page images are not part of what a person decides.
        The metadata and the space count as confirmed (the person kept or chose it), and the
        document is new for no one: the run a person decided in never makes it new.
        Returns the nodes whose results the person overruled.

        Only for documents in the inbox (yellow or red, not being processed, no node still
        running after a failure). Extracting fields needs a parsed text."""
        processing = self.processing
        if self.lane not in (Lane.YELLOW, Lane.RED) or processing.status not in (
            ProcessingStatus.REVIEW,
            ProcessingStatus.FAILED,
            ProcessingStatus.COMPLETED,
        ):
            raise InvalidTransitionError(
                because(ReasonCode.NOT_WAITING_FOR_CONFIRMATION, id=str(self.id))
            )
        if running := processing.running() + processing.delegated():
            # Its result would overwrite what the person decided; it ends soon.
            raise InvalidTransitionError(
                because(ReasonCode.STILL_RUNNING, id=str(self.id), nodes=list(running))
            )
        if resume_at not in (Node.FIELDS, Node.APPLY_RULES):
            raise InvalidTransitionError(
                f"processing resumes with {Node.FIELDS} or {Node.APPLY_RULES}, not {resume_at}"
            )
        if resume_at is Node.FIELDS and processing.outcome(Node.PARSE) not in (
            Outcome.OK,
            Outcome.UNCERTAIN,
        ):
            raise InvalidTransitionError(because(ReasonCode.NO_TEXT_TO_EXTRACT, id=str(self.id)))
        again = self._reset_set({resume_at})
        overruled = []
        for node, state in processing.nodes.items():
            if node in again or state.status is NodeStatus.SKIPPED or state.outcome is Outcome.OK:
                continue
            if state.status is NodeStatus.WAITING and (
                node not in resume_at.ancestors or node is Node.PAGES
            ):
                continue  # never ran and not needed to resume, or the page images: it runs now
            overruled.append(node)
            processing.nodes[node] = NodeState(
                status=NodeStatus.DONE,
                outcome=Outcome.OK,
                started_at=state.started_at or now,
                finished_at=state.finished_at or now,
            )
        self._reset({resume_at}, now)
        self.confirmed_at = require_utc(now, "confirmed_at")
        self.space_confirmed_at = self.confirmed_at
        processing.decided = True
        self.new_at = None
        self._record(DocumentConfirmed(document_id=self.id, occurred_at=now))
        return tuple(overruled)

    def settle(self, node: Node, now: datetime) -> None:
        """A later node of the run answered what `node` left uncertain (the rules filed the
        document into the space the judge suggested): its result counts as OK."""
        state = self.processing.nodes[node]
        if state.status is NodeStatus.DONE and state.outcome is Outcome.UNCERTAIN:
            self.processing.nodes[node] = NodeState(
                status=NodeStatus.DONE,
                outcome=Outcome.OK,
                started_at=state.started_at,
                finished_at=state.finished_at,
            )
            self._touch(now)

    def set_page_count(self, count: int, now: datetime) -> None:
        """The pages node rendered `count` page images."""
        if count < 1:
            raise ValidationError(f"a document has at least one page, not {count}")
        self.page_count = count
        self._touch(now)

    def is_skipped(self, node: Node, run: int) -> bool:
        """True if `node` is skipped in run `run`: a catch-up may record its result
        (`catch_up`), also while other nodes of the run are processed."""
        processing = self.processing
        return run == processing.run and processing.nodes[node].status is NodeStatus.SKIPPED

    def catch_up(
        self, node: Node, run: int, result: NodeResult, started: datetime, now: datetime
    ) -> None:
        """Record the result of a node that is skipped in the current run, beside processing
        (the command `render-pages` catching up on page images). Status and lane stay as they
        are. A failure is recorded in the event and the log only: the node stays skipped, so
        nothing waits on it, nothing is blocked by it, and the next catch-up tries again."""
        if not self.is_skipped(node, run):
            raise InvalidTransitionError(
                f"document {self.id}: node {node} of run {run} is not skipped "
                f"({self.processing.nodes[node].status}, run {self.processing.run})"
            )
        if result.outcome is not Outcome.FAILED:
            self.processing.nodes[node] = NodeState(
                status=NodeStatus.DONE,
                outcome=result.outcome,
                started_at=started,
                finished_at=now,
            )
        self._record(
            NodeCompleted(
                document_id=self.id, occurred_at=now, node=node, run=run, outcome=result.outcome
            )
        )
        self._touch(now)

    def text_read_again(self, run: int, outcome: Outcome, now: datetime) -> None:
        """Its text was read again beside processing (the command `reparse`, after an update of
        the parser): an event for those who follow the document, so the search index takes up
        the new text. Its nodes, status and lane stay as they are."""
        if run != self.processing.run:
            raise InvalidTransitionError(
                f"document {self.id}: run {run} is not its current run {self.processing.run}"
            )
        self._record(
            NodeCompleted(
                document_id=self.id, occurred_at=now, node=Node.PARSE, run=run, outcome=outcome
            )
        )
        self._touch(now)

    def _require_awaiting(self, node: Node, run: int) -> None:
        if not self.is_awaiting(node, run):
            processing = self.processing
            raise InvalidTransitionError(
                f"document {self.id}: node {node} of run {run} is not due "
                f"({processing.status}, {processing.nodes[node].status}, run {processing.run})"
            )

    def _reset_set(self, nodes: Iterable[Node]) -> frozenset[Node]:
        """`nodes`, the nodes after them, and the nodes still running or delegated: what a new
        run repeats."""
        chosen = set(nodes)
        return frozenset(
            chosen
            | {later for node in chosen for later in node.descendants}
            | set(self.processing.running())
            | set(self.processing.delegated())
        )

    def _reset(self, nodes: Iterable[Node], now: datetime) -> tuple[Node, ...]:
        processing = self.processing
        for node in self._reset_set(nodes):
            processing.nodes[node] = NodeState()
        processing.run += 1
        processing.status = ProcessingStatus.PROCESSING
        processing.baseline = metadata_digest(self) if self.lane is Lane.GREEN else NOT_GREEN
        processing.decided = False
        self._set_lane(None, now)
        self._touch(now)
        return processing.due()

    def _uncertain_before(self, node: Node) -> bool:
        return any(
            self.processing.outcome(earlier) is Outcome.UNCERTAIN for earlier in node.ancestors
        )

    def _becomes_new(self) -> bool:
        """Whether the run that just ended green makes the document new (`Processing`)."""
        processing = self.processing
        if processing.decided:
            return False
        if processing.baseline is None:  # a run started before 0.4
            return processing.run == 1
        return processing.baseline == NOT_GREEN or processing.baseline != metadata_digest(self)

    # --- metadata -------------------------------------------------------------------------------

    def apply_changes(
        self,
        changes: DocumentChanges,
        definitions: Mapping[FieldId, FieldDefinition],
        now: datetime,
    ) -> tuple[str, ...]:
        """Apply a metadata change; returns the names of the changed fields.

        `definitions` must contain the definitions of all fields in the change and of all
        fields the document has. References to contacts, types, topics and tags are checked by
        the caller, and so is that the contact enables the topic (`_access.checked_changes`).
        Values of type-bound fields that no longer apply after a type change are removed.
        """
        title = require_name(_pick(changes.title, self.title), "title", max_length=MAX_TITLE)
        contact_id = _pick(changes.contact_id, self.contact_id)
        document_type_id = _pick(changes.document_type_id, self.document_type_id)
        topic_id = _pick(changes.topic_id, self.topic_id)
        tag_ids = set(_pick(changes.tag_ids, frozenset(self.tag_ids)))
        document_date = _pick(changes.document_date, self.document_date)
        created_at = (
            self.created_at
            if isinstance(changes.created_at, Unset)
            else received_at(changes.created_at, now)
        )

        checked = checked_fields(changes, definitions, document_type_id)
        fields = dict(self.fields)
        for field_id in changes.fields.keys() - checked.keys():  # removed
            fields.pop(field_id, None)
        fields.update(checked)
        fields = {
            field_id: value
            for field_id, value in fields.items()
            if _definition(definitions, field_id).applies_to(document_type_id)
        }

        # Everything is valid; apply it.
        new_values: dict[str, object] = {
            CHANGE_FIELDS[TITLE]: title,
            CHANGE_FIELDS[CONTACT]: contact_id,
            CHANGE_FIELDS[DOCUMENT_TYPE]: document_type_id,
            CHANGE_FIELDS[TOPIC]: topic_id,
            CHANGE_FIELDS[TAGS]: tag_ids,
            CHANGE_FIELDS[DOCUMENT_DATE]: document_date,
            CUSTOM_FIELDS: fields,
            RECEIPT: created_at,
        }
        changed = [name for name, value in new_values.items() if getattr(self, name) != value]
        self.title = title
        self.contact_id = contact_id
        self.document_type_id = document_type_id
        self.topic_id = topic_id
        self.tag_ids = tag_ids
        self.document_date = document_date
        self.fields = fields
        self.created_at = created_at
        if changed:
            self._record(
                DocumentUpdated(document_id=self.id, occurred_at=now, fields=tuple(changed))
            )
            self._touch(now)
        return tuple(changed)

    def mark_confirmed(self, now: datetime) -> None:
        """A person set or confirmed the metadata (or it was taken over); during processing,
        a decision in its run (`decided`)."""
        self.confirmed_at = require_utc(now, "confirmed_at")
        self.record_decision()
        self._touch(now)

    def record_decision(self) -> None:
        """A person changed what is confirmed (`CONFIRMING`), also tags set by hand alone, or
        it was taken over: while processing runs, a decision in its run (`Processing.decided`),
        which never makes the document new."""
        if self.processing.status is ProcessingStatus.PROCESSING:
            self.processing.decided = True

    def drop_confirmation(self) -> None:
        """The pipeline derived contact, type, topic or tags anew: they are no longer a
        person's."""
        self.confirmed_at = None

    def mark_new(self, now: datetime) -> None:
        """It became new for the inbox outside processing: moved into a space whose editors
        could not read it before (who could keeps their seen, `services.inbox.arrived`)."""
        self.new_at = require_utc(now, "new_at")
        self._touch(now)

    def confirm_space(self, now: datetime) -> None:
        """A person decided the space where it lies (or it was taken over with the source
        system's permissions)."""
        self.space_confirmed_at = require_utc(now, "space_confirmed_at")
        self._touch(now)

    def move_to(
        self,
        space_id: SpaceId,
        now: datetime,
        *,
        by_person: bool = False,
        handed_over: bool = False,
    ) -> None:
        """File the document into another space. Permissions are checked by the caller.
        `by_person`: a person moved or handed it over, which decides its space; a move of the
        pipeline (the judge, a rule) leaves the space undecided. `handed_over`: the space is
        another user's personal one (`events.DocumentMoved`)."""
        if space_id == self.space_id:
            if by_person:
                self.confirm_space(now)
            return
        self.space_id = space_id
        self.space_confirmed_at = require_utc(now, "space_confirmed_at") if by_person else None
        self._record(DocumentFiled(document_id=self.id, occurred_at=now, space_id=space_id))
        self._record(
            DocumentMoved(
                document_id=self.id,
                occurred_at=now,
                space_id=space_id,
                by_person=by_person,
                handed_over=handed_over,
            )
        )
        self._touch(now)

    def delete(self, now: datetime, readers: Iterable[UserId] = ()) -> None:
        """Record the deletion; the caller removes the document from the repository.
        `readers`: the users who may read the document now, for the event."""
        self._record(
            DocumentDeleted(
                document_id=self.id, occurred_at=now, readers=tuple(dict.fromkeys(readers))
            )
        )

    # --- events ---------------------------------------------------------------------------------

    def pull_events(self) -> list[DocumentEvent]:
        """Hand over the recorded events and forget them."""
        events, self._events = self._events, []
        return events

    def _record(self, event: DocumentEvent) -> None:
        self._events.append(event)

    def _stopped(self, lane: Lane, now: datetime) -> None:
        """Processing stopped in `lane`; where the first run first stopped is kept for good."""
        if self.processing.run == 1 and self.first_lane is None:
            self.first_lane = lane
        self._set_lane(lane, now)

    def _set_lane(self, lane: Lane | None, now: datetime) -> None:
        if lane is self.lane:
            return
        old, self.lane = self.lane, lane
        self._record(LaneChanged(document_id=self.id, occurred_at=now, old=old, new=lane))
        if lane in (Lane.YELLOW, Lane.RED):
            self._record(ReviewRequired(document_id=self.id, occurred_at=now, lane=lane))

    def _touch(self, now: datetime) -> None:
        self.updated_at = require_utc(now, "updated_at")


def _pick[T](change: T | Unset, current: T) -> T:
    return current if isinstance(change, Unset) else change


def _definition(
    definitions: Mapping[FieldId, FieldDefinition], field_id: FieldId
) -> FieldDefinition:
    try:
        return definitions[field_id]
    except KeyError:
        raise NotFoundError("field", field_id) from None


def file_title(filename: str) -> str:
    """A file name without its extension (all of it if that leaves nothing)."""
    return PurePath(filename).stem or filename


def metadata_digest(document: Document) -> str:
    """A digest of the metadata a person confirms (`CONFIRMING`): contact, type, topic, tags,
    date and fields. Equal metadata, equal digest; any change of them changes it."""
    values = {
        CHANGE_FIELDS[CONTACT]: _text(document.contact_id),
        CHANGE_FIELDS[DOCUMENT_TYPE]: _text(document.document_type_id),
        CHANGE_FIELDS[TOPIC]: _text(document.topic_id),
        CHANGE_FIELDS[TAGS]: sorted(str(tag) for tag in document.tag_ids),
        CHANGE_FIELDS[DOCUMENT_DATE]: _text(document.document_date),
        CUSTOM_FIELDS: {str(id): field_to_json(value) for id, value in document.fields.items()},
    }
    assert set(values) == CONFIRMING
    data = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def _text(value: object | None) -> str | None:
    return None if value is None else str(value)
