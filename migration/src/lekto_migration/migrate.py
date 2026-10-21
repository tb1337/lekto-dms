"""The warm run (`run`): upload what is new, align what was migrated. It starts only when the
plan is complete and Lekto has everything it names (`prepare`), is resumable (what the state
file knows is not done twice), and never stops for one document.

A new document is uploaded in the name of its uploader, with space and metadata (the reviews
included), waited
for, and then aligned: the topic, which an upload cannot carry, is set then, and the rules see
it. A migrated document is aligned from three states (`align`); one deleted in Lekto is
reported, or uploaded again with `--reupload`."""

import asyncio
import json
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lekto_migration.align import KEPT, Alignment, align, current, uploaded
from lekto_migration.config import Config
from lekto_migration.expect import Expected
from lekto_migration.lekto import ApiError, Lekto
from lekto_migration.paperless import Paperless, PaperlessError
from lekto_migration.plan import norm
from lekto_migration.resolve import Resolved, resolve, space_of
from lekto_migration.session import Loaded, MigrationError, Progress, unmanaged
from lekto_migration.state import DOCUMENT_DONE, DocumentRow, State

DONE_PIPELINE = ("completed", "failed", "review")
FAILED = "failed"


@dataclass
class Totals:
    """What happened to the selected documents in this run."""

    documents: int = 0
    uploaded: int = 0
    aligned: int = 0
    resumed: int = 0
    duplicates: int = 0
    skipped: int = 0
    deleted: int = 0  # migrated, but deleted in Lekto since
    failed: int = 0
    stopped: int = 0
    seconds: dict[str, float] = field(default_factory=dict)


class Run:
    def __init__(
        self,
        config: Config,
        loaded: Loaded,
        source: Paperless,
        target: Lekto,
        state: State,
        *,
        stop: asyncio.Event | None = None,
        progress: Progress = lambda message: None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        poll: tuple[float, float] = (0.5, 5.0),
    ) -> None:
        self._config = config
        self._loaded = loaded
        self._source = source
        self._target = target
        self._state = state
        self._stop = stop or asyncio.Event()
        self._progress = progress
        self._clock = clock
        self._sleep = sleep
        self._poll = poll
        self.totals = Totals()
        directory = loaded.directory
        self._parents = {
            str(tag["id"]): tag.get("parent_id") for tag in directory.tags["document"].values()
        }
        self._types = {str(f["id"]): str(f.get("data_type")) for f in directory.fields.values()}
        self._unmanaged = unmanaged(state)
        self._sleeping: list[tuple[str, str]] = []  # users woken for this run: deactivate again

    async def execute(self) -> Totals:
        started = self._clock()
        await self._wake()
        await self._documents()
        if not self._stop.is_set():
            await self._deactivate()
        self.totals.seconds["total"] = self._clock() - started
        return self.totals

    # --- users -------------------------------------------------------------------------------

    def _pending(self) -> list[Expected]:
        out = []
        for item in self._loaded.expected.values():
            row = self._state.document(item.id)
            if item.skip is None and not (row is not None and row.status in DOCUMENT_DONE):
                out.append(item)
        return out

    async def _wake(self) -> None:
        """Users the migration created and deactivated before who upload documents still to come
        or are members of their spaces: active for this run, deactivated again at its end."""
        directory = self._loaded.directory
        needed = set()
        for item in self._pending():
            needed.add(norm(item.uploader or directory.admin["username"]))
            needed |= {norm(name) for name, _ in item.members}
        for key in needed:
            user = directory.users.get(key)
            if user is None or user.get("active") is not False:
                continue
            if str(user["id"]) in self._loaded.ours:
                await self._target.set_active(str(user["id"]), True)
                user["active"] = True
                self._sleeping.append((str(user["id"]), str(user["username"])))

    async def _deactivate(self) -> None:
        """The users inactive in Paperless are inactive in Lekto too, now that nothing of
        theirs is left to upload (users the migration did not create stay as they are)."""
        plan, directory = self._loaded.plan, self._loaded.directory
        targets: dict[str, str] = {}
        if plan.settings.deactivate_inactive_users:
            for user in self._loaded.snapshot.users:
                entry = plan.entry("users", str(user["username"]))
                if user.get("is_active", True) or entry is None or entry.dropped:
                    continue
                name = next(t.name for t in entry.targets if t.to == "user")
                found = directory.find("user", name or "")
                if found is not None and str(found["id"]) in self._loaded.ours:
                    targets[str(found["id"])] = str(found["username"])
        targets.update(dict(self._sleeping))
        for id, name in targets.items():
            found = directory.by_id("user", id)
            if found is not None and found.get("active") is False:
                continue
            try:
                await self._target.set_active(id, False)
            except ApiError as error:
                self._progress(f"cannot deactivate {name}: {error}")

    # --- documents ---------------------------------------------------------------------------

    async def _documents(self) -> None:
        items = list(self._loaded.expected.values())
        self.totals.documents = len(items)
        done = 0
        gate = asyncio.Semaphore(self._config.concurrency)

        async def one(item: Expected) -> None:
            nonlocal done
            async with gate:
                if self._stop.is_set():
                    self.totals.stopped += 1
                    return
                try:
                    await self._document(item)
                except Exception as error:  # one document never stops the others
                    self.totals.failed += 1
                    row = self._state.document(item.id)
                    # An upload stays `uploaded`: the next run waits for it, it does not repeat
                    # it; a migrated one stays migrated.
                    keep = row is not None and row.status in ("uploaded", *DOCUMENT_DONE)
                    self._state.put_document(
                        item.id,
                        row.status if keep and row is not None else FAILED,
                        lane=row.lane if row is not None else None,
                        reason=f"{type(error).__name__}: {error}"[:300],
                    )
                done += 1
                if done % 25 == 0 or done == len(items):
                    self._progress(f"{done}/{len(items)} documents handled")

        await asyncio.gather(*(one(item) for item in items))

    def _detail(self, item: Expected) -> dict[str, Any]:
        return {
            "title": item.title,
            "uploaded_by": item.uploader,
            "owner": item.owner_source,
            "space": item.space or "personal",
            "media_type": item.media_type,
        }

    async def _document(self, item: Expected) -> None:
        detail = self._detail(item)
        if item.skip:
            self._state.put_document(
                item.id, "skipped", reason=item.skip, notes=item.notes, detail=detail
            )
            self.totals.skipped += 1
            return
        resolved = resolve(item, self._loaded.directory)
        if resolved.missing:  # `run` checks before; Lekto changed meanwhile
            raise MigrationError("Lekto lacks " + ", ".join(resolved.missing))
        row = self._state.document(item.id)
        if row is not None and row.lekto_id and row.status in ("done", "duplicate"):
            await self._existing(item, row, resolved)
            return
        lekto_id = row.lekto_id if row is not None and row.status == "uploaded" else None
        if lekto_id is not None:
            try:
                await self._target.document(lekto_id)
            except ApiError as error:
                if error.status != 404:
                    raise
                lekto_id = None
            else:
                self.totals.resumed += 1
        if lekto_id is None:
            began = self._clock()
            sent = await self._upload(item, resolved, detail)
            if sent is None:
                return
            lekto_id, sha256, duplicate = sent
            detail = {**detail, "duplicate": duplicate}
            self._state.put_document(
                item.id,
                "uploaded",
                lekto_id=lekto_id,
                sha256=sha256,
                notes=[*item.notes, *resolved.notes],
                detail=detail,
                upload_seconds=self._clock() - began,
                applied=None if duplicate else self._sent(resolved),
            )
            if duplicate:
                await self._duplicate(item, lekto_id, resolved)
                return
            self.totals.uploaded += 1
        waited = self._clock()
        finished = await self._wait(lekto_id)
        if finished is None:
            if not self._stop.is_set():
                self.totals.failed += 1
                timeout = int(self._config.pipeline_timeout)
                self._state.put_document(
                    item.id,
                    "uploaded",
                    lekto_id=lekto_id,
                    reason=f"processing did not finish in {timeout} s",
                )
            else:
                self.totals.stopped += 1
            return
        row = self._state.document(item.id)
        base = (row.applied if row is not None else None) or self._sent(resolved)
        alignment = await self._align(lekto_id, finished, base, resolved)
        await self._finish(item.id, "done", lekto_id, alignment, waited)

    async def _upload(
        self, item: Expected, resolved: Resolved, detail: dict[str, Any]
    ) -> tuple[str, str, bool] | None:
        """Download the original and upload it with uploader, space and metadata: the Lekto id,
        the file's SHA-256 and whether Lekto had the file already. None: not taken over."""
        fields = {
            "channel": "migration",
            "uploaded_by": resolved.uploader_id,
            "metadata": json.dumps(resolved.metadata()),
        }
        if resolved.space_id is not None:
            fields["space_id"] = resolved.space_id
        with tempfile.TemporaryDirectory(prefix="lekto-migration-") as directory:
            path = Path(directory) / "original"
            try:
                download = await self._source.download_original(item.id, path)
            except PaperlessError as error:
                self.totals.failed += 1
                self._state.put_document(
                    item.id, FAILED, reason=str(error), notes=item.notes, detail=detail
                )
                return None
            try:
                accepted = await self._target.upload(path, item.filename, fields)
            except ApiError as error:
                if error.status == 409 and error.existing:
                    self.totals.duplicates += 1
                    return error.existing, download.sha256, True
                status = "skipped" if error.status == 415 else FAILED
                if status == "skipped":
                    self.totals.skipped += 1
                else:
                    self.totals.failed += 1
                self._state.put_document(
                    item.id,
                    status,
                    sha256=download.sha256,
                    reason=error.detail if error.status == 415 else str(error),
                    notes=item.notes,
                    detail=detail,
                )
                return None
        return str(accepted["id"]), download.sha256, False

    async def _duplicate(self, item: Expected, lekto_id: str, resolved: Resolved) -> None:
        """Lekto has the file already (in the target or a space the uploader is a member of):
        that document stands for this one; if it is a migrated one, it is aligned like one."""
        details = await self._target.document(lekto_id)
        alignment = None
        if details.get("channel") == "migration":
            base = await self._baseline(lekto_id, None, details)
            alignment = await self._align(lekto_id, details, base, resolved)
        await self._finish(item.id, "duplicate", lekto_id, alignment, None, details=details)

    async def _existing(self, item: Expected, row: DocumentRow, resolved: Resolved) -> None:
        assert row.lekto_id is not None
        try:
            details = await self._target.document(row.lekto_id)
        except ApiError as error:
            if error.status != 404:
                raise
            if self._config.reupload:
                self._state.put_document(item.id, "deleted", reason="deleted in Lekto")
                self._state.forget(item.id)
                await self._document(item)
                return
            self.totals.deleted += 1
            self._state.put_document(item.id, row.status, lane=row.lane, reason="deleted in Lekto")
            return
        self.totals.resumed += 1
        if details["processing"]["status"] not in DONE_PIPELINE:
            return  # reprocessed meanwhile: aligned the next time
        if details.get("channel") != "migration":
            self._state.put_document(
                item.id,
                row.status,
                lane=details.get("lane"),
                reason="not taken over by the migration: not aligned",
            )
            return
        base = await self._baseline(row.lekto_id, row.applied, details)
        alignment = await self._align(row.lekto_id, details, base, resolved)
        await self._finish(item.id, row.status, row.lekto_id, alignment, None, details=details)

    async def _baseline(
        self, lekto_id: str, applied: dict[str, Any] | None, details: dict[str, Any]
    ) -> dict[str, Any]:
        """What the migration set last: the state's, else the upload's from the log (its
        space is taken as it is now: the migration never moved documents then)."""
        if applied is not None:
            return applied
        log = await self._target.log(lekto_id)
        return uploaded(log, details.get("space_id")) or current(details)

    def _sent(self, resolved: Resolved) -> dict[str, Any]:
        """What the upload sets: its metadata (no topic), in the space it goes to."""
        return {**self._want(resolved), "topic_id": None}

    def _want(self, resolved: Resolved) -> dict[str, Any]:
        return {**resolved.values, "space_id": space_of(resolved, self._loaded.directory)}

    async def _align(
        self,
        lekto_id: str,
        details: dict[str, Any],
        base: dict[str, Any],
        resolved: Resolved,
    ) -> Alignment:
        alignment = align(
            base,
            current(details),
            self._want(resolved),
            parents=self._parents,
            types=self._types,
            unmanaged=self._unmanaged,
        )
        if alignment.changes:
            await self._target.align(lekto_id, alignment.changes)
        if alignment.move is not None:
            await self._target.move(lekto_id, alignment.move)
        if alignment.needed:
            self.totals.aligned += 1
        return alignment

    async def _finish(
        self,
        source_id: int,
        status: str,
        lekto_id: str,
        alignment: Alignment | None,
        waited: float | None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        details = details or await self._target.document(lekto_id)
        if alignment is not None and alignment.needed:
            details = await self._target.document(lekto_id)
        lane = details.get("lane")
        reasons = []
        if status == "duplicate":
            reasons.append("Lekto has the file already, in a space the uploader sees")
        if lane != "green":
            reasons.append(await self._why_not_green(lekto_id))
        kept = [d.what for d in alignment.differences if d.action == KEPT] if alignment else []
        if kept:
            reasons.append("changed in Lekto since, kept: " + ", ".join(kept))
        row = self._state.document(source_id)
        self._state.put_document(
            source_id,
            status,
            lekto_id=lekto_id,
            lane=lane,
            reason="; ".join(reasons) or None,
            pipeline_seconds=None if waited is None else self._clock() - waited,
            applied=alignment.applied if alignment is not None else None,
            detail={**(row.detail if row else {}), "aligned": bool(alignment and alignment.needed)},
        )

    async def _wait(self, lekto_id: str) -> dict[str, Any] | None:
        """The document once its pipeline is through (or has stopped); None if the run is
        stopped or the time is up."""
        deadline = self._clock() + self._config.pipeline_timeout
        delay = self._poll[0]
        while not self._stop.is_set():
            document = await self._target.document(lekto_id)
            if document["processing"]["status"] in DONE_PIPELINE:
                return document
            if self._clock() > deadline:
                return None
            await self._sleep(delay)
            delay = min(delay * 1.5, self._poll[1])
        return None

    async def _why_not_green(self, lekto_id: str) -> str:
        try:
            log = await self._target.log(lekto_id)
        except ApiError:
            return "not green (the log could not be read)"
        reasons = [
            f"{entry['node']}: {entry['reason']}"
            for entry in log
            if entry["outcome"] != "ok" and entry.get("reason")
        ]
        return "; ".join(dict.fromkeys(reasons)) or "not green"


__all__ = ["DONE_PIPELINE", "MigrationError", "Run", "Totals"]
