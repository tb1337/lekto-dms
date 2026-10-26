"""Ingest and processing: receive a document, run its nodes as jobs, retry and reprocess."""

import asyncio
import copy
import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from lekto.core.domain import media_types
from lekto.core.domain.classification import CLASSIFIER_LABELS, SPACE
from lekto.core.domain.documents import (
    MAX_TITLE,
    Channel,
    Document,
    DocumentChanges,
    Sha256,
    checked_fields,
    received_at,
)
from lekto.core.domain.errors import (
    ConcurrencyError,
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    PermissionDeniedError,
    SpaceWriteDeniedError,
    UnprocessableDocumentError,
    UnsupportedMediaTypeError,
    ValidationError,
)
from lekto.core.domain.events import DocumentUpdated
from lekto.core.domain.first_runs import FACTS, Decision
from lekto.core.domain.ids import DocumentId, SpaceId, TagId, UserId
from lekto.core.domain.imports import IMPORTED, ImportedMetadata
from lekto.core.domain.inbox import Confirmation
from lekto.core.domain.jobs import Job, RetryPolicy
from lekto.core.domain.json_value import JsonObject
from lekto.core.domain.permissions import (
    can_file_into,
    can_hand_over,
    document_access,
    space_role,
)
from lekto.core.domain.pipeline import (
    CHOSEN_SPACE,
    NODES,
    TRIGGER_UPLOAD,
    Lane,
    Node,
    NodeResult,
    NodeRun,
    NodeStatus,
    Outcome,
    ProcessingHistory,
    ProcessingStatus,
)
from lekto.core.domain.reading import (
    NO_TEXT_REASON,
    DocumentReading,
    OcrOutput,
    vision_advice,
)
from lekto.core.domain.reasons import Action, Reason, ReasonCode, because
from lekto.core.domain.rule_planner import changed_fields
from lekto.core.domain.spaces import Space
from lekto.core.domain.users import User
from lekto.core.domain.validation import require_name
from lekto.core.ports.clock import Clock
from lekto.core.ports.object_store import ObjectStore
from lekto.core.ports.ocr import VisionModel
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import (
    access_to,
    checked_changes,
    controllable_document,
    duplicate_of,
    field_definitions,
    load_actor,
    require_admin,
    visible_space,
)
from lekto.core.services._first_runs import keep_first_run, keep_verdicts
from lekto.core.services._jobs import (
    NODE_JOB,
    STORE_ATTEMPTS,
    JobRunner,
    NodeJob,
    document_payload,
    enqueue_nodes,
    lost,
    payload_document,
    retrying,
)
from lekto.core.services._pages import document_pages
from lekto.core.services.documents import DocumentView
from lekto.core.services.inbox import (
    LEARNED_ALIAS,
    alias_to_learn,
    confirmation,
    confirmed_into,
    decide,
    open_nodes,
    suggested_spaces,
)
from lekto.core.services.master_data import learn_alias
from lekto.core.services.objects import original_key
from lekto.core.services.relating import RELATE_JOB, RELATIONS_LOCK, queue_relate, relate
from lekto.core.services.rules.running import corrected_fields, person_record, space_choice
from lekto.core.services.tasks.settling import Delegation, cancel_tasks

log = logging.getLogger(__name__)

CATCH_UP_JOB = "pipeline.catch_up"
"""Job kind of a node skipped in the document's current run that is run afterwards, outside
processing (`PipelineService.catch_up`); payload: `NodeJob`."""
REPARSE_JOB = "pipeline.reparse"
"""Job kind of reading a document's text again (`PipelineService.reparse`); payload: `NodeJob`
of the node `parse`."""
FACTS_JOB = "pipeline.facts"
"""Job kind of reading a document's facts outside processing (`read-codes`): the codes on its
pages and the identifiers it shows; payload: document id. Processing and log stay as they are."""


class DeferredResult(Protocol):
    """A node result that is completed in the transaction that stores it, on the state that is
    stored (applying metadata, running rules). A `Delegation` instead of a result: the node
    handed work to tasks and waits for their answers ("running externally"); it runs anew
    when one of them ends (`services.tasks`)."""

    async def apply(
        self, uow: UnitOfWork, document: Document, now: datetime
    ) -> NodeResult | Delegation: ...


@dataclass(frozen=True)
class MetadataResult:
    """A node result together with a change of the document's metadata (classification).
    Both are stored in the same transaction. If the change no longer fits (master data was
    removed meanwhile), nothing is changed and the node is uncertain. `add_tags` are added to
    the tags the document has when the result is stored, so tags set meanwhile stay. A new
    contact that does not enable the document's topic clears it (`checked_changes`).

    `confirms`: metadata taken over from the source system, which counts as confirmed;
    otherwise it is the pipeline's, and a document whose contact, type, topic or tags it
    changes is no longer confirmed.

    `space`: the judge moves the document there (a space that shows it to no one new and keeps
    it with its uploader, no one else's personal space). If that no longer holds, it stays
    and the node is uncertain."""

    result: NodeResult
    changes: DocumentChanges
    add_tags: frozenset[TagId] = frozenset()
    confirms: bool = False
    space: SpaceId | None = None

    async def apply(self, uow: UnitOfWork, document: Document, now: datetime) -> NodeResult:
        changes = self.changes
        if not self.add_tags <= document.tag_ids:
            changes = replace(changes, tag_ids=frozenset(document.tag_ids | self.add_tags))
        try:
            changes = await checked_changes(uow, changes, document)
            definitions = await field_definitions(uow)
            changed = document.apply_changes(changes, definitions, now)
        except (NotFoundError, ValidationError) as error:
            meanwhile = because(ReasonCode.MASTER_DATA_CHANGED, detail=str(error))
            return replace(self.result, outcome=Outcome.UNCERTAIN, reasons=(meanwhile,))
        if self.confirms:
            document.mark_confirmed(now)
            document.confirm_space(now)  # the source system's permissions placed it
        elif CLASSIFIER_LABELS & set(changed):
            document.drop_confirmation()
        if self.space is not None and self.space != document.space_id:
            stays = await _judged_move(uow, document, self.space, now)
            if stays is not None:
                return replace(
                    self.result, outcome=Outcome.UNCERTAIN, reasons=(*self.result.reasons, stays)
                )
        return self.result


async def _judged_move(
    uow: UnitOfWork, document: Document, target: SpaceId, now: datetime
) -> Reason | None:
    """Move the document into `target`, where the judge put it; why not, if it stays."""
    here = await uow.spaces.find(document.space_id)
    there = await uow.spaces.find(target)
    uploader = document.uploaded_by
    if (
        here is None
        or there is None
        or here.widens(there)
        or there.personal_of not in (None, uploader)
        or (uploader is not None and there.role_of(uploader) is None)
    ):
        return because(ReasonCode.SPACE_CHANGED_MEANWHILE)
    document.move_to(target, now)
    return None


class NodeExecutor(Protocol):
    """Does the work of one pipeline node (OCR, parsing, classification, ...).

    Runs outside any transaction and may take long. Returns what the node decided, or a result
    to complete when it is stored; raising an exception counts as a failed attempt and is
    retried, except UnprocessableDocumentError, which fails the node at once.
    """

    async def run(self, document: Document) -> NodeResult | DeferredResult: ...


@dataclass(frozen=True)
class IncomingFile:
    """A received file in a local temporary location. The receiving adapter computes the
    SHA-256 and size while it writes the file, so the content is read only once."""

    path: Path
    sha256: Sha256
    size: int

    @classmethod
    def of(cls, path: Path) -> "IncomingFile":
        """Hash an existing file (blocking; for tools and tests)."""
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return cls(path=path, sha256=Sha256(digest.hexdigest()), size=size)


class PipelineService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        object_store: ObjectStore,
        executors: Mapping[Node, NodeExecutor],
        *,
        pipeline_version: str,
        suggest_contact: float,
        retry: RetryPolicy,
        poor_reading: float,
        lease: timedelta = timedelta(minutes=10),
        vision: VisionModel | None = None,
        vision_lease: timedelta | None = None,
        facts: NodeExecutor | None = None,
    ) -> None:
        """`suggest_contact`: the similarity from which a name suggests a contact; an alias
        learned on confirmation must be at least that related to the contact's names;
        `lease`: how long a worker holds the job of a node, longer than any node may take;
        `vision`: the vision language model the OCR can read pages with, if any;
        `vision_lease`: how long a worker holds the OCR of a document the vision model reads
        (`Document.read_with_vision`), if longer than `lease`: it extends the claim when the
        node starts, so a job whose worker died runs again after `lease`, not after this;
        `poor_reading`: the share of unsure (content) words from which a page counts as
        poorly read;
        `facts`: the facts signal for reading facts outside processing (`request_facts`)."""
        missing = set(NODES) - {Node.RECEIVE} - set(executors)
        if missing:
            raise ValueError(f"no executor for nodes: {', '.join(sorted(missing))}")
        self._uow = uow
        self._clock = clock
        self._store = object_store
        self._executors = dict(executors)
        self._version = pipeline_version
        self._suggest_contact = suggest_contact
        self._retry = retry
        self._lease = lease
        self._vision_lease = vision_lease
        self._jobs = JobRunner(uow, clock)
        self._vision = vision
        self._poor_reading = poor_reading
        self._facts = facts

    @property
    def vision(self) -> VisionModel | None:
        """The vision language model a person can have documents read with, if any."""
        return self._vision

    @property
    def retry_policy(self) -> RetryPolicy:
        """How often and when a node that raised runs again."""
        return self._retry

    @property
    def lease(self) -> timedelta:
        """How long a worker holds the job of a node."""
        return self._lease

    @property
    def vision_lease(self) -> timedelta | None:
        """How long a worker holds the OCR of a document the vision model reads, if longer."""
        return self._vision_lease

    # --- ingest ---------------------------------------------------------------------------------

    async def receive(
        self,
        actor: UserId,
        file: IncomingFile,
        *,
        filename: str,
        space: SpaceId | None = None,
        channel: Channel = Channel.API,
        uploaded_by: UserId | None = None,
        imported: ImportedMetadata | None = None,
    ) -> Document:
        """Store the original, then create the document, its first events and the jobs of the
        nodes after receiving in one transaction.

        The media type is recognised from the content; an unsupported type raises
        UnsupportedMediaTypeError and nothing is stored. Without `space` the document goes to
        the uploader's personal space; otherwise the caller needs to edit `space`. Every file
        exists once per installation: one that lies in Lekto already is rejected with
        DuplicateDocumentError (naming the document if the caller may read it), also if the
        same file arrives twice at the same moment. An original left in the store (its document
        deleted, its files not removed yet) is not stored again.
        `channel`: how the document arrived (for rules).

        `uploaded_by`: an active admin may receive the document on behalf of another active
        user, who is named as its uploader (the document goes to their personal space unless
        `space` says otherwise). `imported`: metadata of a document taken over from another
        system, for an active admin and the channel `migration` only; it is checked against the
        master data now and applied by the classification nodes instead of the language model.
        """
        started = self._clock.now()
        sha256 = file.sha256
        media_type = media_types.detect(await asyncio.to_thread(_head, file.path))
        if media_type is None:
            raise UnsupportedMediaTypeError(
                f"unsupported file type; supported: {', '.join(media_types.SUPPORTED)}"
            )
        async with self._uow() as uow:
            uploader = await self._uploader(uow, actor, uploaded_by, channel, imported)
            target = await self._target_space(uow, actor, uploader, space, sha256)
            if imported is not None:
                await _check_imported(uow, imported)
                if imported.created_at is not None:
                    received_at(imported.created_at, started)  # before anything is stored
        key = original_key(sha256)
        if not await self._store.exists(key):
            await self._store.upload(key, file.path, content_type=media_type)

        output: JsonObject = {"sha256": sha256.hex, "size": file.size, "media_type": media_type}
        if uploader != actor:
            output["uploaded_by"] = str(actor)
        if imported is not None:
            output[IMPORTED] = imported.to_json()
        result = NodeResult(outcome=Outcome.OK, output=output)
        try:
            return await self._create(
                actor,
                uploader,
                target,
                sha256,
                file.path,
                filename,
                media_type,
                channel,
                result,
                started,
                chosen=space is not None,
                received=None if imported is None else imported.created_at,
            )
        except ConflictError:
            # The same file arrived twice at the same moment; the other upload won.
            async with self._uow() as uow:
                error = await duplicate_of(uow, await load_actor(uow, actor), sha256)
            if error is None:
                raise
            raise error from None

    async def _create(
        self,
        actor: UserId,
        uploader: UserId,
        target: SpaceId,
        sha256: Sha256,
        path: Path,
        filename: str,
        media_type: str,
        channel: Channel,
        result: NodeResult,
        started: datetime,
        *,
        chosen: bool,
        received: datetime | None = None,
    ) -> Document:
        """`chosen`: the person chose the space; rules leave it. `received`: when it came in,
        if not now (taken over from the source system)."""
        now = self._clock.now()
        key = original_key(sha256)
        async with self._uow() as uow:
            # The removal of a deleted document's files may have taken the original meanwhile;
            # under the lock of its key, store it again if so.
            await uow.lock(key)
            if not await self._store.exists(key):
                await self._store.upload(key, path, content_type=media_type)
            # Check again: rights or a duplicate may have changed while the file was stored.
            await self._target_space(uow, actor, uploader, target, sha256)
            document = Document.receive(
                uploaded_by=uploader,
                space_id=target,
                sha256=sha256,
                original_filename=filename,
                media_type=media_type,
                result=result,
                now=now,
                channel=channel,
                received=received,
                space_chosen=chosen,
            )
            await uow.documents.add(document)
            await self._log(uow, document.id, Node.RECEIVE, 1, result, started, now)
            if chosen:
                await uow.processing_log.append(
                    space_choice(
                        document,
                        node=Node.RECEIVE,
                        actor=actor,
                        trigger=TRIGGER_UPLOAD,
                        version=self._version,
                        now=now,
                    )
                )
            await enqueue_nodes(uow, document, document.processing.due(), now)
            await uow.outbox.add(document.pull_events())
            await uow.commit()
        return document

    async def _uploader(
        self,
        uow: UnitOfWork,
        actor: UserId,
        uploaded_by: UserId | None,
        channel: Channel,
        imported: ImportedMetadata | None,
    ) -> UserId:
        """Who is named as the document's uploader: the caller, or for an admin the user they
        name."""
        caller = await load_actor(uow, actor)
        if imported is not None:
            if channel is not Channel.MIGRATION:
                raise ValidationError("metadata: only with the channel 'migration'")
            if not caller.is_active_admin:
                raise PermissionDeniedError(
                    because(ReasonCode.ADMINS_ONLY, action=Action.GIVE_UPLOAD_METADATA.value)
                )
        if uploaded_by is None or uploaded_by == actor:
            return actor
        if not caller.is_active_admin:
            raise PermissionDeniedError(
                because(ReasonCode.ADMINS_ONLY, action=Action.UPLOAD_FOR_OTHERS.value)
            )
        named = await uow.users.find(uploaded_by)
        if named is None or not named.active:
            raise NotFoundError("user", uploaded_by)
        return uploaded_by

    async def _target_space(
        self,
        uow: UnitOfWork,
        actor: UserId,
        uploader: UserId,
        space: SpaceId | None,
        sha256: Sha256,
    ) -> SpaceId:
        """The space for a document `actor` uploads in the name of `uploader`: `space`, which
        the actor edits, or else the uploader's personal space. DuplicateDocumentError if the
        file lies in Lekto already, wherever (every file exists once per installation); it
        names the document if the actor may read it."""
        user = await load_actor(uow, actor)
        if space is None:
            target = await uow.spaces.get_personal(uploader)
        else:
            target = await visible_space(uow, user, space)
            if not can_file_into(user, target):
                raise SpaceWriteDeniedError(target.id, target.name)
        if (error := await duplicate_of(uow, user, sha256)) is not None:
            raise error
        return target.id

    # --- retry and reprocess --------------------------------------------------------------------

    async def retry(self, actor: UserId, id: DocumentId) -> DocumentView:
        """Editors and admins: repeat the failed nodes and continue from there."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document, _ = await controllable_document(uow, user, id, Action.CONTROL_PROCESSING)
            access = await access_to(uow, user, document)
            document.retry(self._clock.now())
            await self._restart(uow, document)
        return DocumentView(document, access)

    async def reprocess_from(self, actor: UserId, id: DocumentId, node: Node) -> DocumentView:
        """Editors and admins: discard the results of `node` and the nodes after it and process
        them again."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document, _ = await controllable_document(uow, user, id, Action.CONTROL_PROCESSING)
            access = await access_to(uow, user, document)
            document.reprocess_from(node, self._clock.now())
            await self._restart(uow, document)
        return DocumentView(document, access)

    async def read_with_vision(self, actor: UserId, id: DocumentId) -> DocumentView:
        """Editors and admins: have the vision language model read every page, and process the
        document again from OCR (`Document.read_with_vision`). Sending the pages out is a
        person's decision; nothing else asks for it. InvalidTransitionError without a model,
        and where reprocessing from OCR is not possible."""
        if self._vision is None:
            raise InvalidTransitionError(because(ReasonCode.NO_VISION_MODEL))
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document, _ = await controllable_document(uow, user, id, Action.CONTROL_PROCESSING)
            access = await access_to(uow, user, document)
            document.read_with_vision(self._clock.now())
            await self._restart(uow, document)
        return DocumentView(document, access)

    async def reading(self, actor: UserId, id: DocumentId) -> DocumentReading:
        """Editors and admins, as the log: how the archive's text was read (its latest OCR that
        made one), and whether reading it with the vision language model is advised: the
        document waits for a person because no text was found, or with a poorly read page."""
        async with self._uow() as uow:
            document, _ = await controllable_document(
                uow, await load_actor(uow, actor), id, Action.CONTROL_PROCESSING
            )
            log = await uow.processing_log.list_for(id)
        history = ProcessingHistory(log)
        ocr = history.latest(Node.OCR, made=True)
        parse = history.latest(Node.PARSE)
        read = None if ocr is None else OcrOutput.from_json(ocr.result.output)
        vision = read is not None and read.vision is not None
        pages = () if read is None else read.readings
        poor = tuple(page.page for page in pages if page.poor(self._poor_reading))
        needs_person = document.lane in (Lane.YELLOW, Lane.RED) and (
            document.processing.status is not ProcessingStatus.PROCESSING
        )
        no_text = (
            parse is not None
            and parse.result.outcome is Outcome.FAILED
            and parse.result.reason == NO_TEXT_REASON
        )
        return DocumentReading(
            vision=vision,
            pages=pages,
            poor=poor,
            advice=vision_advice(
                vision=vision, poor=poor, needs_person=needs_person, no_text=no_text
            ),
        )

    async def confirm(
        self,
        actor: UserId,
        id: DocumentId,
        changes: DocumentChanges,
        *,
        accept_suggestions: bool = False,
        resume_at: Node = Node.APPLY_RULES,
        space: SpaceId | None = None,
    ) -> DocumentView | None:
        """Editors and admins, for a document in the inbox: decide its open fields, apply
        `changes` (as a metadata change), move it into `space` (as `DocumentService.move`: one
        the caller edits, or another user's personal space; an admin chooses any space), or
        with `accept_suggestions` into a suggested space, and let processing continue from
        `resume_at`, up to filing. Its space counts as a person's decision then (kept or
        chosen).

        Each uncertain field of the nodes before `resume_at`, and of the rules when processing
        resumes with them, needs a decision (see `inbox.decide`). The nodes whose results the
        person overruled get a log entry; so do the rules, with what the person decided and
        changed: the rules that run next leave it as it is.

        Choosing a contact for an open contact field teaches it the name the model read as an
        alias (`master_data.learn_alias`), so the next document with that name finds it.

        The document leaves the inbox for everyone and is new for no one, except for the
        editors of `space` who could not read it before (`inbox.confirmed_into`); who confirmed
        it, and when, is kept for done (`domain.inbox`). None: the caller cannot read the
        document where it lies now (handed over, or moved into a space they only read, where
        it is not green yet).

        If the fields node does not run again, the type's title pattern is rendered with the
        decided values, as long as the document has the machine's title (`titles`)."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document, source = await controllable_document(uow, user, id, Action.CONTROL_PROCESSING)
            log = await uow.processing_log.list_for(id)
            outcomes = dict(document.processing.outcomes)
            again = {resume_at, *resume_at.descendants}
            open = [
                item
                for item in open_nodes(document, log)
                if item.node not in again
                or (item.node is Node.APPLY_RULES and resume_at is Node.APPLY_RULES)
            ]
            target = None if space is None else await self._move_target(uow, user, source, space)
            now = self._clock.now()
            tags_before = frozenset(document.tag_ids)
            space_decided = document.space_confirmed_at is not None
            overruled = document.confirm(resume_at, now)
            await uow.inbox.record_confirmation(id, Confirmation(user.id, now))
            definitions = await field_definitions(uow)
            # A suggested space the person may not move the document into is kept with the
            # suggestions, not taken: the rest is confirmed.
            movable = [
                suggested
                for suggested in suggested_spaces(open)
                if accept_suggestions
                and target is None
                and await self._movable(uow, user, source, suggested)
            ]
            decision = decide(
                open,
                document,
                changes,
                accept_suggestions=accept_suggestions,
                definitions=definitions,
                given=() if target is None else (SPACE,),
                movable=movable,
            )
            if target is None and decision.space not in (None, document.space_id):
                assert decision.space is not None
                target = await self._move_target(uow, user, source, decision.space)
            # The person decided the change as given (with the suggestions they accepted); a
            # topic the new contact does not enable is cleared, but not by their decision.
            decided = changed_fields(decision.changes)
            checked = await checked_changes(uow, decision.changes, document, user)
            decision = replace(decision, changes=checked)
            before = copy.deepcopy(document)
            document.apply_changes(decision.changes, definitions, now)
            corrected = corrected_fields(before, document, decided=decided)
            if target is not None:
                document.move_to(
                    target.id,
                    now,
                    by_person=True,
                    handed_over=target.personal_of not in (None, user.id),
                )
                await confirmed_into(uow, document, source, target, now, user.id)
            await keep_verdicts(
                uow,
                Decision.INBOX,
                before=before,
                after=document,
                given=decided | ({SPACE} if target else set()),
                definitions=definitions,
                now=now,
                log=log,
                space_decided=space_decided,
            )
            run = document.processing.run
            for node in overruled:
                result = confirmation(node, outcomes.get(node), decision, user.id)
                await self._log(uow, id, node, run, result, now, now)
            result = confirmation(
                Node.APPLY_RULES, outcomes.get(Node.APPLY_RULES), decision, user.id
            )
            person = person_record(
                changed=decided | ({SPACE} if target else set()),
                tags_before=tags_before,
                tags_after=document.tag_ids,
                corrected=corrected,
            )
            chosen: JsonObject = {} if target is None else {CHOSEN_SPACE: str(target.id)}
            learned = alias_to_learn(open, decision, document)
            if (
                learned is not None
                and await learn_alias(uow, *learned, threshold=self._suggest_contact) is not None
            ):
                chosen[LEARNED_ALIAS] = {"contact_id": str(learned[0]), "alias": learned[1]}
            result = replace(result, output={**result.output, **person, **chosen})
            await self._log(uow, id, Node.APPLY_RULES, run, result, now, now)
            access = document_access(user, document, source if target is None else target)
            # The person decided what its relations rest on: they are found again.
            await queue_relate(uow, document.id, now)
            await self._restart(uow, document)
        return None if access is None else DocumentView(document, access)

    async def _movable(self, uow: UnitOfWork, user: User, source: Space, id: SpaceId) -> bool:
        """Whether `user` may move a document of `source` into the space `id` on confirming
        it."""
        try:
            await self._move_target(uow, user, source, id)
        except (NotFoundError, SpaceWriteDeniedError):
            return False
        return True

    async def _move_target(self, uow: UnitOfWork, user: User, source: Space, id: SpaceId) -> Space:
        """The space `user` moves a document of `source` into on confirming it (as
        `DocumentService.move`)."""
        target = await uow.spaces.find(id)
        if target is None or not (space_role(user, target) or can_hand_over(user, target)):
            raise NotFoundError("space", id)
        if not (can_file_into(user, target) or can_hand_over(user, target)):
            raise SpaceWriteDeniedError(target.id, target.name)
        if target.personal_of is not None and target.role_of(user.id) is None:
            receiver = await uow.users.find(target.personal_of)
            if receiver is None or not receiver.active:
                raise NotFoundError("space", id)
        return target

    async def _restart(self, uow: UnitOfWork, document: Document) -> None:
        """Store the document's new run: the tasks of the runs before end (a late answer is
        refused)."""
        await cancel_tasks(uow, document.id, self._clock.now())
        await uow.documents.update(document)
        await enqueue_nodes(uow, document, document.processing.due(), self._clock.now())
        await uow.outbox.add(document.pull_events())
        await uow.commit()

    async def catch_up(self, node: Node) -> int:
        """Queue a job for every document whose `node` is skipped in its current run (the
        command `render-pages`: page images of documents from before the node existed).
        Returns how many were queued; a document with such a job already is not queued
        again. A document that starts a new run meanwhile keeps the node skipped; its job is
        stale then, and the next call queues it again."""

        def catch_up(document: Document) -> tuple[JsonObject, str] | None:
            run = document.processing.run
            if not document.is_skipped(node, run):
                return None
            return (
                NodeJob(document.id, node, run).to_json(),
                f"{document.id}:{run}:{node.value}:catch-up",
            )

        return await self._queue_each(CATCH_UP_JOB, catch_up)

    async def request_reparse(self, actor: UserId) -> int:
        """Admins only: `reparse`."""
        async with self._uow() as uow:
            await require_admin(uow, actor, Action.REPARSE_ALL)
        return await self.reparse()

    async def reparse(self) -> int:
        """Read the text of every document again (after an update of the parser): a job for
        each document whose text was read in its current run and that is not being processed.
        Returns how many were queued; a document with such a job already is not queued again.
        Its nodes, status, lane and metadata stay as they are; its log gets the new reading, and
        the search index takes up the new text. A document that starts a new run meanwhile has
        its text read there; its job is stale then."""

        def reparse(document: Document) -> tuple[JsonObject, str] | None:
            run = document.processing.run
            if not _reparsable(document, run):
                return None
            return NodeJob(document.id, Node.PARSE, run).to_json(), f"{document.id}:{run}:reparse"

        return await self._queue_each(REPARSE_JOB, reparse)

    async def request_facts(self) -> int:
        """Queue reading the facts of every document whose text was read and that is not being
        processed (the command `read-codes`): the codes on its pages and the identifiers it
        shows, for documents from before codes were read. Returns how many were queued; one
        queued already is not queued twice."""
        if self._facts is None:
            return 0

        def facts(document: Document) -> tuple[JsonObject, str] | None:
            processing = document.processing
            if processing.status is ProcessingStatus.PROCESSING:
                return None
            if processing.outcome(Node.PARSE) not in (Outcome.OK, Outcome.UNCERTAIN):
                return None
            return document_payload(document.id), f"{document.id}:facts"

        return await self._queue_each(FACTS_JOB, facts)

    async def _queue_each(
        self, kind: str, job: Callable[[Document], tuple[JsonObject, str] | None]
    ) -> int:
        """A `kind` job for each document `job` gives a payload and a dedup key for; returns
        how many were queued (one queued already is not queued twice)."""
        queued = 0
        async for page in document_pages(self._uow):
            async with self._uow() as uow:
                for document in page:
                    found = job(document)
                    if found is None:
                        continue
                    payload, dedup = found
                    queued += (
                        await uow.jobs.enqueue(
                            kind, payload, run_at=self._clock.now(), dedup_key=dedup
                        )
                        is not None
                    )
                await uow.commit()
        return queued

    # --- worker ---------------------------------------------------------------------------------

    def executor(self, node: Node) -> NodeExecutor:
        """What runs `node`."""
        return self._executors[node]

    def replace_executor(self, node: Node, executor: NodeExecutor) -> NodeExecutor:
        """Let `executor` run `node` from now on, for tests and tools; returns the one it
        replaces."""
        replaced, self._executors[node] = self._executors[node], executor
        return replaced

    async def run_next_job(self) -> bool:
        """Claim the next due node job and run it. Returns False if no job was due.

        The node is marked as running first (its own transaction, with the event), so the
        state shows where work happens. The node's work runs outside any transaction; its
        result, the processing log entry, the events and the jobs of the nodes due next are
        stored in one transaction with the job's completion. A job whose node is no longer due
        (stale) is just completed. A job that was claimed more often than the retry policy
        allows (the worker died or overran its lease each time) fails without running again.

        If the caller is cancelled after the claim (the worker shuts down), the job is released
        at once to run again, instead of waiting for its lease to expire; the interrupted claim
        does not count as an attempt.

        A node whose attempt raised waits (`document.node_deferred`) until the job runs again.
        A catch-up job (`catch_up`) runs the same way, except that its node is not marked as
        running and its result changes neither the status nor the lane.
        """
        return await self._jobs.run_next(
            [NODE_JOB, CATCH_UP_JOB, REPARSE_JOB, FACTS_JOB, RELATE_JOB],
            self._lease,
            self._run_claimed,
        )

    async def _run_claimed(self, job: Job) -> None:
        if job.kind == FACTS_JOB:
            await self._read_facts(job)
            return
        if job.kind == RELATE_JOB:
            await self._relate_aside(job)
            return
        try:
            target = NodeJob.from_json(job.payload)
        except (KeyError, TypeError, ValueError) as error:
            await self._jobs.invalid(job, error)
            return
        document_id, node, run = target.document_id, target.node, target.run
        if job.kind == REPARSE_JOB:
            await self._reparse(job, document_id, run)
            return
        started = self._clock.now()
        if job.kind == CATCH_UP_JOB:
            document = await self._skipped(document_id, node, run)
        else:
            document = await self._start(job, document_id, node, run, started)
        if document is None:
            await self._jobs.end(job)
            return
        if job.tries > self._retry.max_attempts:
            exhausted = because(
                ReasonCode.NODE_ATTEMPTS_EXHAUSTED, attempts=self._retry.max_attempts
            )
            await self._record(job, document_id, node, run, _failed(exhausted), started)
            return
        try:
            outcome: NodeResult | DeferredResult = await self._executors[node].run(document)
        except UnprocessableDocumentError as error:
            outcome = _failed(error.reason)
        except Exception as error:
            crashed = because(
                ReasonCode.NODE_CRASHED, error=type(error).__name__, detail=str(error)
            )
            reason = crashed.text
            retry_at = self._retry.next_run(job.tries, self._clock.now())
            log.warning(
                "pipeline node failed",
                extra={"document_id": str(document_id), "node": node, "attempt": job.tries},
                exc_info=True,
            )
            if retry_at is None:
                await self._record(job, document_id, node, run, _failed(crashed), started)
                return
            await self._defer(job, document_id, node, run, retry_at, reason)
            return

        await self._record(job, document_id, node, run, outcome, started)

    async def _defer(
        self,
        job: Job,
        document_id: DocumentId,
        node: Node,
        run: int,
        retry_at: datetime,
        reason: str,
    ) -> None:
        """Let the job run again at `retry_at` and show the node as waiting meanwhile (a
        catch-up job has nothing to show). Nothing changes if the job's claim was lost."""

        async def defer() -> None:
            async with self._uow() as uow:
                await uow.jobs.reschedule(job, run_at=retry_at, error=reason)
                document = await uow.documents.find(document_id)
                if (
                    job.kind != CATCH_UP_JOB
                    and document is not None
                    and document.is_awaiting(node, run)
                    and document.processing.nodes[node].status is NodeStatus.RUNNING
                ):
                    document.defer_node(node, run, retry_at, self._clock.now())
                    await uow.documents.update(document)
                    await uow.outbox.add(document.pull_events())
                await uow.commit()

        await self._jobs.storing(job, defer)

    async def _read_facts(self, job: Job) -> None:
        """Read a document's facts outside processing and keep what they apply (the
        identifiers it shows); the result itself is not recorded. An attempt that raises runs
        again later, like a node."""
        try:
            document_id = payload_document(job.payload)
        except (KeyError, ValueError) as error:
            await self._jobs.invalid(job, error)
            return
        async with self._uow() as uow:
            document = await uow.documents.find(document_id)
        if document is None or self._facts is None:
            await self._jobs.end(job)
            return
        try:
            outcome = await self._facts.run(document)
        except Exception as error:
            await self._failed_aside(job, "reading the facts failed", document_id, error)
            return
        if isinstance(outcome, NodeResult):
            await self._jobs.end(job)
            return

        async def apply(uow: UnitOfWork) -> None:
            current = await uow.documents.find(document_id)
            if current is not None:
                now = self._clock.now()
                await outcome.apply(uow, current, now)
                # Its facts changed outside processing: the search index takes them in.
                updated = DocumentUpdated(document_id=document_id, occurred_at=now, fields=(FACTS,))
                await uow.outbox.add([updated])

        await self._jobs.end(job, also=apply)

    async def _relate_aside(self, job: Job) -> None:
        """Find a document's relations outside processing (`relating.RELATE_JOB`); nothing is
        recorded in its log. An attempt that raises runs again later, like a node."""
        try:
            document_id = payload_document(job.payload)
        except (KeyError, ValueError) as error:
            await self._jobs.invalid(job, error)
            return
        try:
            async with self._uow() as uow:
                await uow.lock(RELATIONS_LOCK)
                document = await uow.documents.find(document_id)
                now = self._clock.now()
                made = [] if document is None else await relate(uow, document, now)
                await uow.jobs.complete(job, now=now, result={"relations": len(made)})
                await uow.commit()
        except ConcurrencyError:
            lost(job)
        except Exception as error:
            await self._failed_aside(job, "finding the relations failed", document_id, error)

    async def request_relations(self) -> int:
        """Queue finding the relations of every document that is not being processed (the
        command `relate`): for documents from before the node `relate`, and after a relation
        target was marked. Returns how many were queued; one queued already is not queued
        twice."""

        def relations(document: Document) -> tuple[JsonObject, str] | None:
            if document.processing.status is ProcessingStatus.PROCESSING:
                return None
            return document_payload(document.id), f"{document.id}:relate"

        return await self._queue_each(RELATE_JOB, relations)

    async def _reparse(self, job: Job, document_id: DocumentId, run: int) -> None:
        """Read a document's text again (`reparse`) and record the reading beside processing.
        An attempt that raises runs again later, like a node; the reading of a document that
        was changed meanwhile is recorded again."""
        async with self._uow() as uow:
            document = await uow.documents.find(document_id)
        if document is None or not _reparsable(document, run):
            await self._jobs.end(job)
            return
        started = self._clock.now()
        try:
            outcome = await self._executors[Node.PARSE].run(document)
        except UnprocessableDocumentError as error:
            outcome = _failed(error.reason)
        except Exception as error:
            await self._failed_aside(job, "reading the text again failed", document_id, error)
            return
        assert isinstance(outcome, NodeResult), "parsing applies nothing"
        result = replace(outcome, input={**outcome.input, "reparse": True})

        async def record() -> None:
            now = self._clock.now()
            async with self._uow() as uow:
                document = await uow.documents.find(document_id)
                if document is not None and _reparsable(document, run):
                    document.text_read_again(run, result.outcome, now)
                    await uow.documents.update(document)
                    await self._log(uow, document.id, Node.PARSE, run, result, started, now)
                    await uow.outbox.add(document.pull_events())
                if result.outcome is Outcome.FAILED:
                    await uow.jobs.fail(job, now=now, error=result.reason or "failed")
                else:
                    await uow.jobs.complete(job, now=now)
                await uow.commit()

        await self._jobs.storing(job, record)

    async def _failed_aside(
        self, job: Job, message: str, document_id: DocumentId, error: Exception
    ) -> None:
        """An attempt of a job beside processing (facts, reading again) raised: it runs again
        later, like a node, and is given up after as many attempts."""
        log.warning(
            message, extra={"document_id": str(document_id), "attempt": job.tries}, exc_info=True
        )
        reason = f"{type(error).__name__}: {error}"
        await self._jobs.again(job, reason, self._retry.next_run(job.tries, self._clock.now()))

    async def _skipped(self, document_id: DocumentId, node: Node, run: int) -> Document | None:
        """The document, if its `node` is still to catch up on; None if the job is stale."""
        async with self._uow() as uow:
            document = await uow.documents.find(document_id)
        if document is None or not document.is_skipped(node, run):
            return None
        return document

    async def _start(
        self, job: Job, document_id: DocumentId, node: Node, run: int, now: datetime
    ) -> Document | None:
        """Mark the node as running and return the document; None if the job is stale. The
        OCR of a document the vision model reads holds its job for `vision_lease`. A
        concurrent change of the document (another node of it finishing) is retried."""

        async def start() -> Document | None:
            async with self._uow() as uow:
                document = await uow.documents.find(document_id)
                if document is None or not document.is_awaiting(node, run):
                    return None
                document.start_node(node, run, now)
                if (
                    node is Node.OCR
                    and document.processing.vision
                    and self._vision_lease is not None
                ):
                    await uow.jobs.extend(job, until=now + self._vision_lease)
                await uow.documents.update(document)
                await uow.outbox.add(document.pull_events())
                await uow.commit()
            return document

        return await retrying(start, attempts=STORE_ATTEMPTS, backoff=True)

    async def _record(
        self,
        job: Job,
        document_id: DocumentId,
        node: Node,
        run: int,
        result: NodeResult | DeferredResult,
        started: datetime,
    ) -> None:
        """Store a node result (completing a deferred one on the stored state). A concurrent
        change of the document (e.g. a metadata edit) is retried; if the job's claim was lost,
        another worker owns the node and nothing is stored."""
        await self._jobs.storing(
            job, lambda: self._record_once(job, document_id, node, run, result, started)
        )

    async def _record_once(
        self,
        job: Job,
        document_id: DocumentId,
        node: Node,
        run: int,
        outcome: NodeResult | DeferredResult,
        started: datetime,
    ) -> None:
        now = self._clock.now()
        catching_up = job.kind == CATCH_UP_JOB
        async with self._uow() as uow:
            document = await uow.documents.find(document_id)
            if document is None or not (
                document.is_skipped(node, run) if catching_up else document.is_awaiting(node, run)
            ):
                await uow.jobs.complete(job, now=now)
                await uow.commit()
                return
            if isinstance(outcome, NodeResult):
                result = outcome
            else:
                applied = await outcome.apply(uow, document, now)
                if isinstance(applied, Delegation):
                    assert not catching_up, "a catch-up delegates nothing"
                    document.delegate_node(node, run, applied.deadline, now)
                    again = applied.again and document.resume_node(node, run, now)
                    await uow.documents.update(document)
                    await uow.jobs.complete(job, now=now)
                    if again:  # after this job: a running one would hold the new one back
                        await enqueue_nodes(uow, document, [node], now)
                    await uow.outbox.add(document.pull_events())
                    await uow.commit()
                    return
                result = applied
            first_lane = document.first_lane
            if catching_up:
                document.catch_up(node, run, result, started, now)
                due: tuple[Node, ...] = ()
            else:
                due = document.record_result(node, run, result, now)
            await uow.documents.update(document)
            await self._log(uow, document.id, node, run, result, started, now)
            await keep_first_run(uow, document, first_lane, now)
            await enqueue_nodes(uow, document, due, now)
            if result.outcome is Outcome.FAILED:
                await uow.jobs.fail(job, now=now, error=result.reason or "failed")
            else:
                await uow.jobs.complete(job, now=now)
            await uow.outbox.add(document.pull_events())
            await uow.commit()

    async def _log(
        self,
        uow: UnitOfWork,
        document: DocumentId,
        node: Node,
        run: int,
        result: NodeResult,
        started: datetime,
        now: datetime,
    ) -> None:
        await uow.processing_log.append(
            NodeRun(
                document_id=document,
                node=node,
                run=run,
                result=result,
                pipeline_version=self._version,
                started_at=started,
                duration=now - started,
            )
        )


async def _check_imported(uow: UnitOfWork, imported: ImportedMetadata) -> None:
    """ValidationError if the metadata does not fit the master data: unknown contact, type or
    tag, or field values that do not fit their definition or the document type; or if its
    title is empty or too long."""
    changes = replace(imported.classification(), tag_ids=imported.tag_ids)
    changes = replace(changes, fields=dict(imported.fields))
    try:
        await checked_changes(uow, changes)
        if imported.title is not None:
            require_name(imported.title, "title", max_length=MAX_TITLE)
        checked_fields(changes, await field_definitions(uow), imported.document_type_id)
    except NotFoundError as error:
        raise ValidationError(f"metadata: {error}") from None


def _failed(reason: Reason) -> NodeResult:
    return NodeResult(outcome=Outcome.FAILED, reasons=(reason,))


def _head(path: Path) -> bytes:
    with path.open("rb") as file:
        return file.read(media_types.SNIFF_SIZE)


def _reparsable(document: Document, run: int) -> bool:
    """Whether the document's text can be read again in `run`: it is its current run, the text
    was read in it, and the document is not being processed."""
    processing = document.processing
    return (
        processing.run == run
        and processing.status is not ProcessingStatus.PROCESSING
        and processing.nodes[Node.PARSE].status is NodeStatus.DONE
    )
