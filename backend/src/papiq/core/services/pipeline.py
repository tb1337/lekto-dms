"""Ingest and processing: receive a document, run its nodes as jobs, retry and reprocess."""

import asyncio
import copy
import hashlib
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol, Self
from uuid import UUID

from papiq.core.domain import media_types
from papiq.core.domain.classification import CLASSIFIER_LABELS, SPACE
from papiq.core.domain.documents import (
    Channel,
    Document,
    DocumentChanges,
    Sha256,
)
from papiq.core.domain.errors import (
    ConflictError,
    DuplicateDocumentError,
    InvalidTransitionError,
    NotFoundError,
    OpenFieldsError,
    PermissionDeniedError,
    SpaceWriteDeniedError,
    UnprocessableDocumentError,
    UnsupportedMediaTypeError,
    ValidationError,
)
from papiq.core.domain.ids import DocumentId, JobId, SpaceId, TagId, UserId
from papiq.core.domain.imports import IMPORTED, ImportedMetadata
from papiq.core.domain.jobs import Job, RetryPolicy
from papiq.core.domain.json_value import JsonObject
from papiq.core.domain.permissions import can_file_into
from papiq.core.domain.pipeline import (
    CHOSEN_SPACE,
    NODES,
    Lane,
    Node,
    NodeResult,
    NodeRun,
    NodeStatus,
    Outcome,
    ProcessingStatus,
)
from papiq.core.domain.reading import (
    NO_TEXT_REASON,
    DocumentReading,
    OcrOutput,
    vision_advice,
)
from papiq.core.domain.rule_engine import changed_fields
from papiq.core.ports import Clock, ObjectStore, UnitOfWork, UnitOfWorkFactory
from papiq.core.ports.ocr import VisionModel
from papiq.core.services._access import (
    checked_changes,
    controllable_document,
    field_definitions,
    load_actor,
    may_file,
    require_admin,
    visible_space,
)
from papiq.core.services._jobs import STORE_ATTEMPTS, JobRunner, retrying
from papiq.core.services.inbox import (
    LEARNED_ALIAS,
    alias_to_learn,
    confirmation,
    decide,
    open_nodes,
)
from papiq.core.services.master_data import learn_alias
from papiq.core.services.objects import original_key
from papiq.core.services.rules.running import corrected_fields, person_record, space_choice

log = logging.getLogger(__name__)

NODE_JOB = "pipeline.node"
"""Job kind of a pipeline node; payload: `NodeJob`."""
CATCH_UP_JOB = "pipeline.catch_up"
"""Job kind of a node skipped in the document's current run that is run afterwards, outside
processing (`PipelineService.catch_up`); payload: `NodeJob`."""
REPARSE_JOB = "pipeline.reparse"
"""Job kind of reading a document's text again (`PipelineService.reparse`); payload: `NodeJob`
of the node `parse`."""
FACTS_JOB = "pipeline.facts"
"""Job kind of reading a document's facts outside processing (`read-codes`): the codes on its
pages and the identifiers it shows; payload: document id. Processing and log stay as they are."""


@dataclass(frozen=True)
class NodeJob:
    """The payload of a job that runs a node of a document in a processing run."""

    document_id: DocumentId
    node: Node
    run: int

    def to_json(self) -> JsonObject:
        return {"document_id": str(self.document_id), "node": self.node.value, "run": self.run}

    @classmethod
    def from_json(cls, payload: JsonObject) -> Self:
        """KeyError, TypeError or ValueError for a payload that is none."""
        run = payload["run"]
        if not isinstance(run, int):
            raise ValueError(f"invalid node job payload {payload!r}")
        return cls(DocumentId(UUID(str(payload["document_id"]))), Node(str(payload["node"])), run)


class DeferredResult(Protocol):
    """A node result that is completed in the transaction that stores it, on the state that is
    stored (applying metadata, running rules)."""

    async def apply(self, uow: UnitOfWork, document: Document, now: datetime) -> NodeResult: ...


@dataclass(frozen=True)
class MetadataResult:
    """A node result together with a change of the document's metadata (classification).
    Both are stored in the same transaction. If the change no longer fits (master data was
    removed meanwhile), nothing is changed and the node is uncertain. `add_tags` are added to
    the tags the document has when the result is stored, so tags set meanwhile stay. A new
    contact that does not enable the document's topic clears it (`checked_changes`).

    `confirms`: metadata taken over from the source system, which counts as confirmed;
    otherwise it is the pipeline's, and a document whose contact, type, topic or tags it
    changes is no longer confirmed."""

    result: NodeResult
    changes: DocumentChanges
    add_tags: frozenset[TagId] = frozenset()
    confirms: bool = False

    async def apply(self, uow: UnitOfWork, document: Document, now: datetime) -> NodeResult:
        changes = self.changes
        if not self.add_tags <= document.tag_ids:
            changes = replace(changes, tag_ids=frozenset(document.tag_ids | self.add_tags))
        try:
            changes = await checked_changes(uow, changes, document)
            definitions = await field_definitions(uow)
            changed = document.apply_changes(changes, definitions, now)
        except (NotFoundError, ValidationError) as error:
            reason = f"the master data changed during the node; nothing was applied ({error})"
            return replace(self.result, outcome=Outcome.UNCERTAIN, reason=reason)
        if self.confirms:
            document.mark_confirmed(now)
        elif CLASSIFIER_LABELS & set(changed):
            document.drop_confirmation()
        return self.result


class NodeExecutor(Protocol):
    """Does the work of one pipeline node (OCR, parsing, classification, ...).

    Runs outside any transaction and may take long. Returns what the node decided, or a result
    to complete when it is stored; raising an exception counts as a failed attempt and is
    retried, except UnprocessableDocumentError, which fails the node at once.
    """

    async def run(self, document: Document) -> NodeResult | DeferredResult: ...


class PlaceholderNode:
    """A node that does nothing and passes: for tests, and for nodes a composition leaves
    out."""

    async def run(self, document: Document) -> NodeResult:
        return NodeResult(outcome=Outcome.OK)


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
        facts: NodeExecutor | None = None,
    ) -> None:
        """`suggest_contact`: the similarity from which a name suggests a contact; an alias
        learned on confirmation must be at least that related to the contact's names;
        `vision`: the vision language model the OCR can read pages with, if any;
        `poor_reading`: the share of unsure words from which a page counts as poorly read;
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
        self._jobs = JobRunner(uow, clock)
        self._vision = vision
        self._poor_reading = poor_reading
        self._facts = facts

    @property
    def vision(self) -> VisionModel | None:
        """The vision language model a person can have documents read with, if any."""
        return self._vision

    # --- ingest ---------------------------------------------------------------------------------

    async def receive(
        self,
        actor: UserId,
        file: IncomingFile,
        *,
        filename: str,
        space: SpaceId | None = None,
        channel: Channel = Channel.API,
        owner: UserId | None = None,
        imported: ImportedMetadata | None = None,
    ) -> Document:
        """Store the original, then create the document, its first events and the jobs of the
        nodes after receiving in one transaction.

        The media type is recognised from the content; an unsupported type raises
        UnsupportedMediaTypeError and nothing is stored. Without `space` the document goes to
        the owner's default space; otherwise the owner needs write access to it. A file the
        owner already has is rejected with DuplicateDocumentError, also if the same file arrives
        twice at the same moment. An
        original that is stored already (another owner has the same file) is not stored again.
        `channel`: how the document arrived (for rules).

        `owner`: an active admin may receive the document on behalf of another active user, who
        becomes its owner (the duplicate check, the default space and the write access to
        `space` are the owner's). `imported`: metadata of a document taken over from another
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
            owner = await self._owner(uow, actor, owner, channel, imported)
            target = await self._target_space(uow, owner, space, sha256)
            if imported is not None:
                await _check_imported(uow, owner, imported, started)
        key = original_key(sha256)
        if not await self._store.exists(key):
            await self._store.upload(key, file.path, content_type=media_type)

        output: JsonObject = {"sha256": sha256.hex, "size": file.size, "media_type": media_type}
        if owner != actor:
            output["uploaded_by"] = str(actor)
        if imported is not None:
            output[IMPORTED] = imported.to_json()
        result = NodeResult(outcome=Outcome.OK, output=output)
        try:
            return await self._create(
                actor,
                owner,
                target,
                sha256,
                file.path,
                filename,
                media_type,
                channel,
                result,
                started,
                chosen=space is not None,
            )
        except ConflictError:
            # The same file arrived twice at the same moment; the other upload won.
            async with self._uow() as uow:
                existing = await uow.documents.find_by_sha256(owner, sha256)
            if existing is None:
                raise
            raise DuplicateDocumentError(existing.id) from None

    async def _create(
        self,
        actor: UserId,
        owner: UserId,
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
    ) -> Document:
        """`chosen`: the person chose the space; rules leave it."""
        now = self._clock.now()
        key = original_key(sha256)
        async with self._uow() as uow:
            # The removal of a deleted document's files may have taken the original meanwhile;
            # under the lock of its key, store it again if so.
            await uow.lock(key)
            if not await self._store.exists(key):
                await self._store.upload(key, path, content_type=media_type)
            # Check again: rights or a duplicate may have changed while the file was stored.
            await self._target_space(uow, owner, target, sha256)
            document = Document.receive(
                owner_id=owner,
                space_id=target,
                sha256=sha256,
                original_filename=filename,
                media_type=media_type,
                result=result,
                now=now,
                channel=channel,
            )
            await uow.documents.add(document)
            await self._log(uow, document.id, Node.RECEIVE, 1, result, started, now)
            if chosen:
                await uow.processing_log.append(
                    space_choice(
                        document,
                        node=Node.RECEIVE,
                        actor=actor,
                        trigger="upload",
                        version=self._version,
                        now=now,
                    )
                )
            await _enqueue(uow, document, document.processing.due(), now)
            await uow.outbox.add(document.pull_events())
            await uow.commit()
        return document

    async def _owner(
        self,
        uow: UnitOfWork,
        actor: UserId,
        owner: UserId | None,
        channel: Channel,
        imported: ImportedMetadata | None,
    ) -> UserId:
        """Who will own the document: the caller, or for an admin the user they name."""
        uploader = await load_actor(uow, actor)
        if imported is not None:
            if channel is not Channel.MIGRATION:
                raise ValidationError("metadata: only with the channel 'migration'")
            if not uploader.is_active_admin:
                raise PermissionDeniedError("only admins can give metadata with an upload")
        if owner is None or owner == actor:
            return actor
        if not uploader.is_active_admin:
            raise PermissionDeniedError("only admins can upload on behalf of another user")
        target = await uow.users.find(owner)
        if target is None or not target.active:
            raise NotFoundError("user", owner)
        return owner

    async def _target_space(
        self, uow: UnitOfWork, actor: UserId, space: SpaceId | None, sha256: Sha256
    ) -> SpaceId:
        """The space for a document of `actor` (its owner)."""
        user = await load_actor(uow, actor)
        existing = await uow.documents.find_by_sha256(actor, sha256)
        if existing is not None:
            raise DuplicateDocumentError(existing.id)
        if space is None:
            return (await uow.spaces.get_default(actor)).id
        target = await visible_space(uow, user, space)
        if not can_file_into(user, target):
            raise SpaceWriteDeniedError(target.id, target.name)
        return target.id

    # --- retry and reprocess --------------------------------------------------------------------

    async def retry(self, actor: UserId, id: DocumentId) -> Document:
        """Owner or admin: repeat the failed nodes and continue from there."""
        async with self._uow() as uow:
            document = await controllable_document(
                uow, await load_actor(uow, actor), id, f"control the processing of document {id}"
            )
            document.retry(self._clock.now())
            await self._restart(uow, document)
        return document

    async def reprocess_from(self, actor: UserId, id: DocumentId, node: Node) -> Document:
        """Owner or admin: discard the results of `node` and the nodes after it and process
        them again."""
        async with self._uow() as uow:
            document = await controllable_document(
                uow, await load_actor(uow, actor), id, f"control the processing of document {id}"
            )
            document.reprocess_from(node, self._clock.now())
            await self._restart(uow, document)
        return document

    async def read_with_vision(self, actor: UserId, id: DocumentId) -> Document:
        """Owner or admin: have the vision language model read every page, and process the
        document again from OCR (`Document.read_with_vision`). Sending the pages out is a
        person's decision; nothing else asks for it. InvalidTransitionError without a model,
        and where reprocessing from OCR is not possible."""
        if self._vision is None:
            raise InvalidTransitionError("no vision language model is configured")
        async with self._uow() as uow:
            document = await controllable_document(
                uow, await load_actor(uow, actor), id, f"control the processing of document {id}"
            )
            document.read_with_vision(self._clock.now())
            await self._restart(uow, document)
        return document

    async def reading(self, actor: UserId, id: DocumentId) -> DocumentReading:
        """Owner or admin, as the log: how the archive's text was read (its latest OCR that
        made one), and whether reading it with the vision language model is advised: the
        document waits for a person because no text was found, or with a poorly read page."""
        async with self._uow() as uow:
            document = await controllable_document(
                uow, await load_actor(uow, actor), id, f"control the processing of document {id}"
            )
            log = await uow.processing_log.list_for(id)
        ocr = _latest(log, Node.OCR, made=True)
        parse = _latest(log, Node.PARSE)
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
    ) -> Document:
        """Owner or admin, for a document in the inbox: decide its open fields, apply `changes`
        (as a metadata change), move it into `space` (one the owner may write to; an admin
        chooses any space, and filing accepts it) and let processing continue from `resume_at`,
        up to filing.

        Each uncertain field of the nodes before `resume_at`, and of the rules when processing
        resumes with them, needs a decision (see `inbox.decide`). The nodes whose results the
        owner overruled get a log entry; so do the rules, with what the owner decided and
        changed: the rules that run next leave it as it is.

        Choosing a contact for an open contact field teaches it the name the model read as an
        alias (`master_data.learn_alias`), so the next document with that name finds it.

        If the fields node does not run again, the type's title pattern is rendered with the
        decided values, as long as the document has the machine's title (`titles`)."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            document = await controllable_document(
                uow, user, id, f"control the processing of document {id}"
            )
            log = await uow.processing_log.list_for(id)
            outcomes = dict(document.processing.outcomes)
            again = {resume_at, *resume_at.descendants}
            open = [
                item
                for item in open_nodes(document, log)
                if item.node not in again
                or (item.node is Node.APPLY_RULES and resume_at is Node.APPLY_RULES)
            ]
            target = None if space is None else await visible_space(uow, user, space)
            if target is not None and not (user.is_active_admin or can_file_into(user, target)):
                raise SpaceWriteDeniedError(target.id, target.name)
            if target is None and not await may_file(
                uow, document, await uow.spaces.get(document.space_id)
            ):
                # Filing would stop again: someone has to choose another space.
                raise OpenFieldsError((SPACE,))
            now = self._clock.now()
            tags_before = frozenset(document.tag_ids)
            overruled = document.confirm(resume_at, now)
            definitions = await field_definitions(uow)
            decision = decide(
                open,
                document,
                changes,
                accept_suggestions=accept_suggestions,
                definitions=definitions,
                given=() if target is None else (SPACE,),
            )
            # The person decided the change as given (with the suggestions they accepted); a
            # topic the new contact does not enable is cleared, but not by their decision.
            decided = changed_fields(decision.changes)
            checked = await checked_changes(uow, decision.changes, document, user)
            decision = replace(decision, changes=checked)
            before = copy.deepcopy(document)
            document.apply_changes(decision.changes, definitions, now)
            corrected = corrected_fields(before, document, decided=decided)
            if target is not None:
                document.move_to(target.id, now)
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
            await self._restart(uow, document)
        return document

    async def _restart(self, uow: UnitOfWork, document: Document) -> None:
        await uow.documents.update(document)
        await _enqueue(uow, document, document.processing.due(), self._clock.now())
        await uow.outbox.add(document.pull_events())
        await uow.commit()

    async def catch_up(self, node: Node) -> int:
        """Queue a job for every document whose `node` is skipped in its current run (the
        command `render-pages`: page images of documents from before the node existed).
        Returns how many were queued; a document with such a job already is not queued
        again. A document that starts a new run meanwhile keeps the node skipped; its job is
        stale then, and the next call queues it again."""
        now = self._clock.now()
        queued = 0
        async with self._uow() as uow:
            for document in await uow.documents.list_all():
                run = document.processing.run
                if not document.is_skipped(node, run):
                    continue
                job = await uow.jobs.enqueue(
                    CATCH_UP_JOB,
                    NodeJob(document.id, node, run).to_json(),
                    run_at=now,
                    dedup_key=f"{document.id}:{run}:{node.value}:catch-up",
                )
                queued += job is not None
            await uow.commit()
        return queued

    async def request_reparse(self, actor: UserId) -> int:
        """Admins only: `reparse`."""
        async with self._uow() as uow:
            await require_admin(uow, actor, "read the text of all documents again")
        return await self.reparse()

    async def reparse(self) -> int:
        """Read the text of every document again (after an update of the parser): a job for
        each document whose text was read in its current run and that is not being processed.
        Returns how many were queued; a document with such a job already is not queued again.
        Its nodes, status, lane and metadata stay as they are; its log gets the new reading, and
        the search index takes up the new text. A document that starts a new run meanwhile has
        its text read there; its job is stale then."""
        now = self._clock.now()
        queued = 0
        async with self._uow() as uow:
            for document in await uow.documents.list_all():
                run = document.processing.run
                if not _reparsable(document, run):
                    continue
                job = await uow.jobs.enqueue(
                    REPARSE_JOB,
                    NodeJob(document.id, Node.PARSE, run).to_json(),
                    run_at=now,
                    dedup_key=f"{document.id}:{run}:reparse",
                )
                queued += job is not None
            await uow.commit()
        return queued

    async def request_facts(self) -> int:
        """Queue reading the facts of every document whose text was read and that is not being
        processed (the command `read-codes`): the codes on its pages and the identifiers it
        shows, for documents from before codes were read. Returns how many were queued; one
        queued already is not queued twice."""
        if self._facts is None:
            return 0
        now = self._clock.now()
        queued = 0
        async with self._uow() as uow:
            for document in await uow.documents.list_all():
                processing = document.processing
                if processing.status is ProcessingStatus.PROCESSING:
                    continue
                if processing.outcome(Node.PARSE) not in (Outcome.OK, Outcome.UNCERTAIN):
                    continue
                job = await uow.jobs.enqueue(
                    FACTS_JOB,
                    {"document_id": str(document.id)},
                    run_at=now,
                    dedup_key=f"{document.id}:facts",
                )
                queued += job is not None
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
            [NODE_JOB, CATCH_UP_JOB, REPARSE_JOB, FACTS_JOB], self._lease, self._run_claimed
        )

    async def _run_claimed(self, job: Job) -> None:
        if job.kind == FACTS_JOB:
            await self._read_facts(job)
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
            document = await self._start(document_id, node, run, started)
        if document is None:
            await self._jobs.end(job)
            return
        if job.tries > self._retry.max_attempts:
            reason = (
                f"node did not finish in {self._retry.max_attempts} attempts "
                "(the worker died or ran out of time each time)"
            )
            await self._record(job, document_id, node, run, _failed(reason), started)
            return
        try:
            outcome: NodeResult | DeferredResult = await self._executors[node].run(document)
        except UnprocessableDocumentError as error:
            outcome = _failed(str(error))
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
            retry_at = self._retry.next_run(job.tries, self._clock.now())
            log.warning(
                "pipeline node failed",
                extra={"document_id": str(document_id), "node": node, "attempt": job.tries},
                exc_info=True,
            )
            if retry_at is None:
                await self._record(job, document_id, node, run, _failed(reason), started)
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
            document_id = DocumentId(UUID(str(job.payload["document_id"])))
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
                await outcome.apply(uow, current, self._clock.now())

        await self._jobs.end(job, also=apply)

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
            outcome = _failed(str(error))
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
                    await uow.jobs.fail(job, error=result.reason or "failed")
                else:
                    await uow.jobs.complete(job)
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
        self, document_id: DocumentId, node: Node, run: int, now: datetime
    ) -> Document | None:
        """Mark the node as running and return the document; None if the job is stale. A
        concurrent change of the document (another node of it finishing) is retried."""

        async def start() -> Document | None:
            async with self._uow() as uow:
                document = await uow.documents.find(document_id)
                if document is None or not document.is_awaiting(node, run):
                    return None
                document.start_node(node, run, now)
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
                await uow.jobs.complete(job)
                await uow.commit()
                return
            if isinstance(outcome, NodeResult):
                result = outcome
            else:
                result = await outcome.apply(uow, document, now)
            if catching_up:
                document.catch_up(node, run, result, started, now)
                due: tuple[Node, ...] = ()
            else:
                due = document.record_result(node, run, result, now)
            await uow.documents.update(document)
            await self._log(uow, document.id, node, run, result, started, now)
            await _enqueue(uow, document, due, now)
            if result.outcome is Outcome.FAILED:
                await uow.jobs.fail(job, error=result.reason or "failed")
            else:
                await uow.jobs.complete(job)
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


def _latest(log: Iterable[NodeRun], node: Node, *, made: bool = False) -> NodeRun | None:
    """The latest run of `node` in the log; with `made`, the latest that did not fail (whose
    result the document still has)."""
    runs = [
        entry
        for entry in log
        if entry.node is node and not (made and entry.result.outcome is Outcome.FAILED)
    ]
    return runs[-1] if runs else None


async def _enqueue(
    uow: UnitOfWork, document: Document, nodes: Iterable[Node], now: datetime
) -> list[JobId]:
    """One job per node, due now, in the document's current run."""
    run = document.processing.run
    jobs = []
    for node in nodes:
        job = await uow.jobs.enqueue(
            NODE_JOB,
            NodeJob(document.id, node, run).to_json(),
            run_at=now,
            dedup_key=f"{document.id}:{run}:{node.value}",
        )
        if job is not None:
            jobs.append(job)
    return jobs


async def _check_imported(
    uow: UnitOfWork, owner: UserId, imported: ImportedMetadata, now: datetime
) -> None:
    """ValidationError if the metadata does not fit the master data: unknown contact, type or
    tag, or field values that do not fit their definition or the document type."""
    changes = replace(imported.classification(), tag_ids=imported.tag_ids)
    changes = replace(changes, fields=dict(imported.fields))
    try:
        changes = await checked_changes(uow, changes)
        definitions = await field_definitions(uow)
        scratch = Document.receive(
            owner_id=owner,
            space_id=SpaceId(owner),
            sha256=Sha256("0" * 64),
            original_filename="scratch",
            media_type="application/pdf",
            result=NodeResult(outcome=Outcome.OK),
            now=now,
        )
        scratch.apply_changes(changes, definitions, now)
    except NotFoundError as error:
        raise ValidationError(f"metadata: {error}") from None


def _failed(reason: str) -> NodeResult:
    return NodeResult(outcome=Outcome.FAILED, reason=reason)


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
