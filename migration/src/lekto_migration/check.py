"""The cold run (`check`): what `prepare` and `run` would do, nothing written. For every Paperless
document: not selected, skipped, new (what it becomes, and where each value comes from),
migrated and the same, migrated and different (what the alignment would change, with the
rules it sets off, and what was changed in Lekto since and stays), or deleted in Lekto.
Migrated documents have their texts compared; with `--download`, the files are checked."""

import asyncio
import re
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from lekto_migration.align import Alignment, align, current, foreign, uploaded
from lekto_migration.config import Config
from lekto_migration.directory import Directory
from lekto_migration.expect import Expected
from lekto_migration.lekto import ApiError, Lekto
from lekto_migration.mapping import EDIT, READ
from lekto_migration.masterdata import MISSING, Action, visible_to
from lekto_migration.paperless import Paperless, PaperlessError, checksum
from lekto_migration.plan import norm
from lekto_migration.resolve import resolve, space_of
from lekto_migration.session import Loaded, Progress, unmanaged
from lekto_migration.state import DocumentRow, State

MIGRATED = ("done", "duplicate", "uploaded")
_WORD = re.compile(r"\w{2,}")
# What the first bytes of a file say it is.
MAGIC = (
    (b"%PDF", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG", "image/png"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)


def words(text: str) -> int:
    """Words of two letters or more: layout, numbers of one digit and punctuation aside."""
    return len(_WORD.findall(text))


async def check(
    config: Config,
    loaded: Loaded,
    source: Paperless,
    target: Lekto | None,
    state: State,
    *,
    progress: Progress = lambda message: None,
) -> dict[str, Any]:
    started = time.monotonic()
    problems: list[str] = []
    if loaded.outdated:
        shown = ", ".join(loaded.outdated[:10]) + (" ..." if len(loaded.outdated) > 10 else "")
        problems.append(
            f"the plan lacks {len(loaded.outdated)} Paperless objects ({shown}): run plan"
        )
    for action in loaded.actions:
        if action.status == MISSING:
            problems.append(
                f"{action.kind.replace('_', ' ')} '{action.name}' does not exist in Lekto "
                f"and the plan may not create it ({action.source})"
            )
    in_lekto = await _lekto_documents(target)
    rows = {row.source_id: row for row in state.documents()}
    documents: list[dict[str, Any]] = []
    migrated: list[tuple[Expected, dict[str, Any]]] = []
    checker = _Checker(loaded, target, state)
    for document in loaded.snapshot.documents:
        id, row = int(document["id"]), rows.get(int(document["id"]))
        item = loaded.expected.get(id)
        if item is None:
            documents.append(_entry(id, document.get("title"), "not selected", row))
            continue
        if item.skip:
            documents.append(_entry(id, item.title, "skipped", row, reason=item.skip, item=item))
            continue
        if row is None or row.lekto_id is None or row.status not in MIGRATED:
            documents.append(checker.new(item, row))
            continue
        details = in_lekto.get(row.lekto_id)
        if details is None:
            documents.append(_entry(id, item.title, "deleted in Lekto", row, item=item))
            continue
        documents.append(await checker.migrated(item, row, details))
        migrated.append((item, details))
    known = {int(d["id"]) for d in loaded.snapshot.documents}
    for source_id, row in rows.items():
        if source_id not in known and row.lekto_id:
            documents.append(_entry(source_id, row.detail.get("title"), "gone from Paperless", row))
    progress(f"check: {len(documents)} documents looked at")
    texts = await _texts(loaded, source, target, migrated, progress) if migrated else []
    files: list[dict[str, Any]] = []
    if config.download:
        files = await _files(config, loaded, source, in_lekto, rows, progress)
        problems += [f"document {f['id']}: {f['problem']}" for f in files if f.get("problem")]
    return {
        "command": "check",
        "problems": problems,
        "actions": [
            {
                "kind": a.kind,
                "name": a.name,
                "status": a.status,
                "source": a.source,
                "detail": a.detail,
                "notes": a.notes,
            }
            for a in loaded.actions
        ],
        "documents": documents,
        "document_results": dict(Counter(d["status"] for d in documents)),
        "texts": texts,
        "files": files,
        "seconds": {"total": round(time.monotonic() - started, 1)},
    }


class _Checker:
    def __init__(self, loaded: Loaded, target: Lekto | None, state: State) -> None:
        self._loaded = loaded
        self._target = target
        directory = loaded.directory
        self._parents = {
            str(tag["id"]): tag.get("parent_id") for tag in directory.tags["document"].values()
        }
        self._types = {str(f["id"]): str(f.get("data_type")) for f in directory.fields.values()}
        self._unmanaged = unmanaged(state)
        self._state = state

    def new(self, item: Expected, row: DocumentRow | None) -> dict[str, Any]:
        entry = _entry(item.id, item.title, "new", row, item=item)
        members, beyond = visible_to(item, self._loaded.actions, self._loaded.directory)
        entry["becomes"] = _becomes(item, members, beyond)
        missing = resolve(item, self._loaded.directory).missing
        if missing:
            entry["prepare"] = missing  # what `prepare` creates first
        return entry

    async def migrated(
        self, item: Expected, row: DocumentRow, details: dict[str, Any]
    ) -> dict[str, Any]:
        assert row.lekto_id is not None
        resolved = resolve(item, self._loaded.directory)
        if details.get("channel") != "migration":
            reason = "the document in Lekto was not taken over by the migration"
            return _entry(item.id, item.title, "not aligned", row, item=item, reason=reason)
        space = space_of(resolved, self._loaded.directory)
        if row.status == "duplicate":
            claimant = self._state.claimant(row.lekto_id, item.id)
            why = foreign(claimant, details.get("space_id"), space)
            if why is not None:
                return _entry(item.id, item.title, "not aligned", row, item=item, reason=why)
        base = row.applied
        if base is None and self._target is not None:
            try:
                log = await self._target.log(row.lekto_id)
            except ApiError:
                log = []
            base = uploaded(log, details.get("space_id"))
        alignment = align(
            base or current(details),
            current(details),
            {**resolved.values, "space_id": space},
            parents=self._parents,
            types=self._types,
            unmanaged=self._unmanaged,
        )
        status = "differs" if alignment.differences else "same"
        entry = _entry(item.id, item.title, status, row, item=item)
        entry["lane"] = details.get("lane")
        if alignment.differences:
            entry["differences"] = [
                {"what": self._label(d.what), "lekto": d.lekto, "plan": d.plan, "action": d.action}
                for d in alignment.differences
            ]
        if resolved.missing:
            entry["prepare"] = resolved.missing
        elif alignment.changes and self._target is not None:
            entry["rules"] = await self._rules(row.lekto_id, alignment)
        return entry

    def _label(self, what: str) -> str:
        """A difference by name: `tag:<id>` as `tag tax`, `field:<id>` as `field Amount`."""
        directory = self._loaded.directory
        kind, _, id = what.partition(":")
        if kind in ("tag", "field") and id:
            found = directory.by_id(kind, id)
            return f"{kind} {found['name']}" if found else what
        return what

    async def _rules(self, lekto_id: str, alignment: Alignment) -> list[str]:
        """What the rules would do when the alignment changes the document."""
        assert self._target is not None
        try:
            preview = await self._target.align(lekto_id, alignment.changes, dry_run=True)
        except ApiError as error:
            return [f"(the dry run failed: {error})"]
        return [
            f"{rule['name']}: " + ", ".join(str(e.get("field")) for e in rule.get("applied") or [])
            for rule in preview.get("rules") or []
            if rule.get("applied")
        ]


def _entry(
    id: int,
    title: Any,
    status: str,
    row: DocumentRow | None,
    *,
    reason: str | None = None,
    item: Expected | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "title": str(title or ""),
        "status": status,
        "lekto_id": None if row is None else row.lekto_id,
        "reason": reason,
        "notes": [] if item is None else item.notes,
    }


def _becomes(item: Expected, members: list[tuple[str, str]], beyond: list[str]) -> dict[str, Any]:
    """What a new document becomes, by Lekto's names, and where each value comes from: who
    sees it once `prepare` has run, and who of them Paperless kept it from (`beyond`)."""
    return {
        "uploaded_by": item.uploader or "(you)",
        "space": item.space or "personal",
        "members": [f"{name}: {role}" for name, role in members],
        "beyond": beyond,
        "contact": item.contact,
        "document_type": item.document_type,
        "topic": item.topic,
        "tags": sorted(item.tags),
        "contact_groups": sorted(item.contact_groups),
        "type_groups": sorted(item.type_groups),
        "document_date": item.document_date,
        "created_at": item.created_at,
        "fields": item.fields,
        "review": [reason for reason, _ in item.review],
        "sources": item.sources,
    }


async def _lekto_documents(target: Lekto | None) -> dict[str, dict[str, Any]]:
    if target is None:
        return {}
    found: dict[str, dict[str, Any]] = {}
    cursor = None
    while True:
        page = await target.documents(cursor=cursor)
        found.update({item["id"]: item for item in page["items"]})
        cursor = page.get("next_cursor")
        if not cursor:
            return found


async def _texts(
    loaded: Loaded,
    source: Paperless,
    target: Lekto | None,
    migrated: list[tuple[Expected, dict[str, Any]]],
    progress: Progress,
) -> list[dict[str, Any]]:
    """Migrated documents whose text Lekto read worse than Paperless, or that Lekto itself
    would have read with the vision language model (only a person asks for that)."""
    if target is None:
        return []
    threshold = loaded.plan.settings.text_threshold
    try:
        contents = await source.contents({item.id for item, _ in migrated})
    except PaperlessError as error:
        progress(f"the texts of Paperless could not be read: {error}")
        return []
    found = []
    for item, details in migrated:
        try:
            text = await target.text(details["id"])
            reading = await target.reading(details["id"])
        except ApiError:
            continue
        theirs, ours = words(contents.get(item.id, "")), words(text)
        advice = reading.get("advice")
        fewer = theirs > 0 and ours < threshold * theirs
        if fewer or advice:
            found.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "lekto_id": details["id"],
                    "words_paperless": theirs,
                    "words_lekto": ours,
                    "advice": advice,
                }
            )
    progress(f"texts of {len(migrated)} migrated documents compared")
    return found


async def _files(
    config: Config,
    loaded: Loaded,
    source: Paperless,
    in_lekto: dict[str, dict[str, Any]],
    rows: dict[int, DocumentRow],
    progress: Progress,
) -> list[dict[str, Any]]:
    """Download every original the plan takes over: its checksum, its type by content, and
    whether Lekto would see it as a duplicate (the same file in the space it goes to, or one
    its uploader can read: in a space they edit, or green in a space they read)."""
    directory = loaded.directory
    held: dict[str, dict[str, tuple[str, str | None]]] = {}  # sha256 -> space id -> (id, lane)
    for document in in_lekto.values():
        spaces = held.setdefault(str(document.get("sha256")), {})
        spaces[str(document.get("space_id"))] = (str(document["id"]), document.get("lane"))
    taken = [item for item in loaded.expected.values() if item.skip is None]
    planned = _planned_members(loaded.actions, directory)
    # sha256 -> (space key, Paperless id, green: True, or False if in Lekto and not green)
    seen: dict[str, list[tuple[str, int, bool]]] = {}
    gate = asyncio.Semaphore(config.concurrency)
    found: list[dict[str, Any]] = []
    documents = {int(d["id"]): d for d in loaded.selected}

    async def one(item: Expected) -> None:
        async with gate:
            with tempfile.TemporaryDirectory(prefix="lekto-check-") as folder:
                path = Path(folder) / "original"
                try:
                    download = await source.download_original(item.id, path)
                except PaperlessError as error:
                    found.append({"id": item.id, "title": item.title, "problem": str(error)})
                    return
                head = path.read_bytes()[:8]
                digest = download.sha256
        entry: dict[str, Any] = {"id": item.id, "title": item.title, "sha256": digest}
        kept = checksum(documents[item.id])
        if kept is not None and kept != digest:
            entry["problem"] = "the file differs from the checksum Paperless keeps"
        kind = next((media for magic, media in MAGIC if head.startswith(magic)), None)
        if kind is None:
            entry["problem"] = "Lekto would not take the file (not a PDF, JPEG, PNG or TIFF)"
        elif kind != item.media_type:
            entry["note"] = f"the file is {kind}, Paperless says {item.media_type}"
        edits, reads = _reach(item, directory, planned)
        row = rows.get(item.id)
        existing = next(
            (
                lekto_id
                for space, (lekto_id, lane) in held.get(digest, {}).items()
                if (space in edits or (space in reads and lane == "green"))
                and (row is None or row.lekto_id != lekto_id)
            ),
            None,
        )
        earlier = next(
            (
                id
                for key, id, green in seen.get(digest, [])
                if key in edits or (key in reads and green)
            ),
            None,
        )
        if existing is not None:
            entry["note"] = f"Lekto has the file already, in a space its uploader sees ({existing})"
        elif earlier is not None:
            entry["note"] = f"the same file as document {earlier}, in a space its uploader sees"
        else:
            # One not in Lekto yet counts as green: taken-over metadata usually make it so.
            details = in_lekto.get(row.lekto_id) if row is not None and row.lekto_id else None
            green = details is None or details.get("lane") == "green"
            seen.setdefault(digest, []).append((_space_key(item, directory), item.id, green))
        found.append(entry)

    await asyncio.gather(*(one(item) for item in taken))
    progress(f"{len(found)} originals downloaded and checked")
    return sorted((f for f in found if f.get("problem") or f.get("note")), key=lambda f: f["id"])


def _uploader_of(item: Expected, directory: Directory) -> str:
    return item.uploader or str(directory.admin["username"])


def _personal_key(uploader: str, directory: Directory) -> str:
    """The personal space of a user: its id, or a key while Lekto has none (a new user)."""
    user = directory.find("user", uploader)
    personal = directory.personal_space(str(user["id"])) if user is not None else None
    return str(personal["id"]) if personal is not None else f"personal:{norm(uploader)}"


def _space_key(item: Expected, directory: Directory) -> str:
    """The space a document goes to: its id, or a key while `prepare` has not created it."""
    if item.space is None:
        return _personal_key(_uploader_of(item, directory), directory)
    found = directory.space(item.space)
    return str(found["id"]) if found is not None else f"space:{norm(item.space)}"


def _planned_members(actions: list[Action], directory: Directory) -> dict[str, dict[str, str]]:
    """The members (norm(name) -> role) the shared spaces have once `prepare` has run, by the
    key of `_space_key`."""
    planned: dict[str, dict[str, str]] = {}
    for action in actions:
        if action.kind != "space":
            continue
        found = directory.space(action.name)
        key = str(found["id"]) if found is not None else f"space:{norm(action.name)}"
        planned[key] = {norm(name): role for name, role in action.data.get("after", ())}
    return planned


def _reach(
    item: Expected, directory: Directory, planned: dict[str, dict[str, str]]
) -> tuple[set[str], set[str]]:
    """The spaces Lekto compares a document's file with, now or after `prepare`: those where
    every file counts (the one it goes to and those its uploader edits), and those where only
    green documents count (those its uploader reads)."""
    uploader = _uploader_of(item, directory)
    edits = {_space_key(item, directory), _personal_key(uploader, directory)}
    reads: set[str] = set()
    user = directory.find("user", uploader)
    if user is not None:
        edits |= directory.member_spaces(str(user["id"]), EDIT)
        reads |= directory.member_spaces(str(user["id"]), READ)
    for key, members in planned.items():
        role = members.get(norm(uploader))
        if role == EDIT:
            edits.add(key)
        elif role == READ:
            reads.add(key)
    return edits, reads - edits
