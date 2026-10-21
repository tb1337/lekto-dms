"""The command line: `plan` (the migration plan), `check` (cold run), `prepare` (master data in
Lekto) and `run` (the migration, resumable)."""

import argparse
import asyncio
import os
import signal
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import httpx2

from lekto_migration import plan as plans
from lekto_migration import report as reports
from lekto_migration.check import check
from lekto_migration.config import Config, ConfigError, env_file, public
from lekto_migration.expect import Context, expect, field_infos
from lekto_migration.lekto import DELAYS, ApiError, Lekto
from lekto_migration.masterdata import (
    CREATE,
    CREATED,
    FAILED,
    MISSING,
    OPEN,
    UPDATE,
    Action,
    needs,
    prepare,
)
from lekto_migration.migrate import Run
from lekto_migration.paperless import Paperless, PaperlessError, Snapshot
from lekto_migration.session import Ask, Loaded, MigrationError, Progress, bound, load, read
from lekto_migration.state import DOCUMENT_DONE, State, StateError
from lekto_migration.survey import Changes, draft, merge

DESCRIPTION = """\
Takes over a Paperless-ngx archive into Lekto, in phases: `plan` writes the migration plan (what
is taken over, and how), `check` shows what would happen, `prepare` creates the master data in
Lekto, `run` takes the documents over. It reads Paperless through its REST API and writes
through the Lekto API, with an admin's API token. API keys come from the environment only:
LEKTO_MIGRATION_PAPERLESS_TOKEN and LEKTO_MIGRATION_LEKTO_TOKEN (or ..._FILE with a path), the
addresses from --paperless-url / --lekto-url or LEKTO_MIGRATION_PAPERLESS_URL / ..._LEKTO_URL.
"""
COMMANDS = (
    ("plan", "write the migration plan, or add to it what is new in Paperless"),
    ("check", "cold run: what prepare and run would do; nothing is written"),
    ("prepare", "create in Lekto what the plan needs before the documents come"),
    ("run", "take the documents over and align the migrated ones; continues where it stopped"),
)


ENV_FILE = (
    "take the LEKTO_MIGRATION_ settings from this file of KEY=value lines, before or after the "
    "command (the development instance: .devcontainer/dev.local.env)"
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="lekto-migration",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    root.add_argument("--env-file", type=Path, metavar="FILE", help=ENV_FILE)
    commands = root.add_subparsers(dest="command", required=True)
    for name, text in COMMANDS:
        command = commands.add_parser(name, help=text, description=text)
        command.add_argument("--paperless-url", help="e.g. http://localhost:8000")
        command.add_argument("--lekto-url", help="e.g. http://localhost:8001")
        command.add_argument("--plan", type=Path, default=Path("migration-plan.yaml"))
        command.add_argument("--state", type=Path, default=Path("migration-state.sqlite"))
        command.add_argument("--report-dir", type=Path, default=Path("migration-reports"))
        command.add_argument("--limit", type=int, help="only the first N selected documents")
        command.add_argument("--concurrency", type=int, default=4, help="documents at a time")
        command.add_argument(
            "--env-file", type=Path, metavar="FILE", help=ENV_FILE, default=argparse.SUPPRESS
        )
        if name != "check":
            command.add_argument("--yes", action="store_true", help="write without asking")
        if name == "check":
            command.add_argument(
                "--download", action="store_true", help="download the originals and check them"
            )
        if name == "run":
            command.add_argument(
                "--pipeline-timeout", type=float, default=3600.0, metavar="SECONDS"
            )
            command.add_argument(
                "--reupload", action="store_true", help="upload documents deleted in Lekto again"
            )
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        environ = os.environ if args.env_file is None else env_file(args.env_file, os.environ)
        config = Config.load(
            paperless_url=args.paperless_url,
            lekto_url=args.lekto_url,
            state=args.state,
            report_dir=args.report_dir,
            plan=args.plan,
            concurrency=args.concurrency,
            limit=args.limit,
            pipeline_timeout=getattr(args, "pipeline_timeout", 3600.0),
            download=getattr(args, "download", False),
            yes=getattr(args, "yes", False),
            reupload=getattr(args, "reupload", False),
            env=environ,
        )
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return asyncio.run(_with_signals(config, args.command))


async def _with_signals(config: Config, command: str) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(number, _stop, stop, number)
    return await execute(config, command, stop=stop)


def _stop(stop: asyncio.Event, number: signal.Signals) -> None:
    if stop.is_set():
        raise KeyboardInterrupt
    print(
        f"\n{number.name}: stopping after the uploads in progress; run again to continue",
        file=sys.stderr,
    )
    stop.set()


def say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def terminal(config: Config) -> Ask:
    """Ask on the terminal; without one, only `--yes` writes."""

    def ask(question: str) -> bool:
        if config.yes:
            return True
        if not sys.stdin.isatty():
            say(f"{question} Not asked without a terminal: nothing written (use --yes).")
            return False
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes", "j", "ja")

    return ask


async def execute(
    config: Config,
    command: str,
    *,
    stop: asyncio.Event | None = None,
    paperless_transport: httpx2.AsyncBaseTransport | None = None,
    lekto_transport: httpx2.AsyncBaseTransport | None = None,
    progress: Progress = say,
    ask: Ask | None = None,
    poll: tuple[float, float] = (0.5, 5.0),
    delays: tuple[float, ...] = DELAYS,
    today: date | None = None,
) -> int:
    """Run one command; returns the exit code (0 fine, 1 problems, failures or nothing
    written, 2 cannot go on, 130 stopped)."""
    stop = stop or asyncio.Event()
    ask = ask or terminal(config)
    source = Paperless(config.paperless_url, config.paperless_token, transport=paperless_transport)
    target = (
        Lekto(config.lekto_url, config.lekto_token, transport=lekto_transport, delays=delays)
        if config.lekto_url and config.lekto_token
        else None
    )
    existed = config.state.exists()
    state: State | None = None
    try:
        if command in ("prepare", "run") and target is None:
            raise MigrationError("the Lekto URL and API key are needed (LEKTO_MIGRATION_LEKTO_*)")
        state = State(
            config.state if existed or command in ("prepare", "run") else Path(":memory:")
        )
        if existed or command in ("prepare", "run"):
            state.bind(
                paperless=public(config.paperless_url) or "", lekto=public(config.lekto_url) or ""
            )
        if command == "plan":
            return await _plan(config, source, target, progress, ask, today or date.today())
        loaded = await load(
            config, source, target, state, write=command != "check", progress=progress
        )
        if command == "check":
            return await _check(config, loaded, source, target, state, progress)
        assert target is not None
        if command == "prepare":
            return await _prepare(config, loaded, target, state, progress, ask)
        return await _run(config, loaded, source, target, state, stop, progress, ask, poll)
    except (MigrationError, PaperlessError, StateError, ApiError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    finally:
        if state is not None:
            state.close()
        await source.close()
        if target is not None:
            await target.close()


def _write(config: Config, name: str, report: dict[str, object]) -> None:
    config.report_dir.mkdir(parents=True, exist_ok=True)
    (config.report_dir / f"{name}.md").write_text(reports.to_markdown(report), encoding="utf-8")
    (config.report_dir / f"{name}.json").write_text(reports.to_json(report), encoding="utf-8")
    say(f"report: {config.report_dir / (name + '.md')}")


def _head(config: Config, command: str, snapshot: Snapshot) -> dict[str, object]:
    return reports.head(
        command, snapshot, public(config.paperless_url) or "", public(config.lekto_url)
    )


# --- plan -------------------------------------------------------------------------------------


async def _plan(
    config: Config,
    source: Paperless,
    target: Lekto | None,
    progress: Progress,
    ask: Ask,
    today: date,
) -> int:
    snapshot, directory = await read(source, target, write=False, progress=progress)
    path, written = config.plan, False
    if path.exists():
        try:
            document = plans.yaml().load(path.read_text(encoding="utf-8"))
        except Exception as error:  # ruamel.yaml raises several of its own
            raise MigrationError(f"{path} is no valid YAML: {error}") from None
        bound(document, config)
        changes = merge(document, snapshot, directory, today)
        if changes:
            for name in changes.added:
                progress(f"  new in Paperless: {name}")
            for name in changes.gone:
                progress(f"  not in Paperless any more: {name}")
            counts = f"{len(changes.added)} new, {len(changes.gone)} gone"
            if ask(f"The plan {path} changes ({counts}). Write it?"):
                plans.dump(document, path)
                written = True
        else:
            progress(f"the plan {path} is up to date with Paperless")
    else:
        document = draft(
            snapshot,
            directory,
            source=public(config.paperless_url) or "",
            target=public(config.lekto_url) or "",
        )
        plans.dump(document, path)
        written = True
        changes = Changes()
        progress(f"the plan was written to {path}: read it, change it, then run check")
    problems: list[str] = []
    entries: dict[str, dict[str, int]] = {}
    try:
        plan = plans.parse(document)
    except plans.PlanError as error:
        problems = error.problems
    else:
        for section, items in plan.entries.items():
            entries[section] = {
                "entries": len(items),
                "dropped": sum(1 for e in items.values() if e.dropped),
            }
        fields = field_infos(plan, directory, snapshot)
        context = Context(
            plan=plan, snapshot=snapshot, fields=fields, admin=str(directory.admin["username"])
        )
        expected = [expect(d, context) for d in snapshot.documents]
        for action in needs(plan, directory, snapshot, expected, fields):
            if action.status == MISSING:
                problems.append(
                    f"{action.kind.replace('_', ' ')} '{action.name}' does not exist in Lekto "
                    f"and the plan may not create it ({action.source})"
                )
    for problem in problems:
        progress(f"  problem: {problem}")
    report = {
        **_head(config, "plan", snapshot),
        "path": str(path),
        "written": written,
        "changes": {"added": changes.added, "gone": changes.gone},
        "problems": problems,
        "entries": entries,
        "source_counts": reports.source_counts(snapshot),
    }
    _write(config, "plan", report)
    return 1 if problems or (changes and not written) else 0


# --- check ------------------------------------------------------------------------------------


async def _check(
    config: Config,
    loaded: Loaded,
    source: Paperless,
    target: Lekto | None,
    state: State,
    progress: Progress,
) -> int:
    result = await check(config, loaded, source, target, state, progress=progress)
    report = {
        **_head(config, "check", loaded.snapshot),
        **result,
        "source_counts": reports.source_counts(loaded.snapshot),
    }
    _write(config, "check", report)
    counts = ", ".join(f"{k} {v}" for k, v in sorted(result["document_results"].items()))
    progress(f"check: {counts}; {len(result['problems'])} problems")
    return 1 if result["problems"] else 0


# --- prepare ----------------------------------------------------------------------------------


def _ready(loaded: Loaded) -> None:
    """The plan knows every Paperless object and names nothing Lekto lacks for good."""
    if loaded.outdated:
        raise MigrationError(
            f"the plan lacks {len(loaded.outdated)} Paperless objects "
            f"({', '.join(loaded.outdated[:5])}): run plan first"
        )
    missing = [a for a in loaded.actions if a.status == MISSING]
    if missing:
        raise MigrationError(
            "the plan names what Lekto lacks and may not create: "
            + ", ".join(f"{a.kind} '{a.name}'" for a in missing[:10])
        )


async def _prepare(
    config: Config,
    loaded: Loaded,
    target: Lekto,
    state: State,
    progress: Progress,
    ask: Ask,
) -> int:
    _ready(loaded)
    pending = [a for a in loaded.actions if a.status in (CREATE, UPDATE)]
    report = {**_head(config, "prepare", loaded.snapshot), "actions": []}
    if not pending:
        progress("Lekto has everything the plan needs")
        report["actions"] = reports.actions(loaded.actions)
        _write(config, "prepare", report)
        return 0
    counts = Counter((a.kind, a.status) for a in pending)
    for (kind, status), count in sorted(counts.items()):
        progress(f"  {status} {count} {kind.replace('_', ' ')}")
    if not ask(f"Create and change {len(pending)} things in Lekto?"):
        return 1

    def record(action: Action, id: str) -> None:
        if action.kind in ("choices", "group"):
            return
        status = "new" if action.status == CREATED else "updated"
        state.put_object(action.kind, action.name, action.name, id, status, action.notes)

    await prepare(
        loaded.actions,
        target,
        loaded.directory,
        ours=frozenset(loaded.ours),
        record=record,
        progress=progress,
    )
    report["actions"] = reports.actions(loaded.actions)
    _write(config, "prepare", report)
    failed = [a for a in loaded.actions if a.status == FAILED]
    progress(f"prepare: {len(pending) - len(failed)} done, {len(failed)} failed")
    return 1 if failed else 0


# --- run --------------------------------------------------------------------------------------


async def _run(
    config: Config,
    loaded: Loaded,
    source: Paperless,
    target: Lekto,
    state: State,
    stop: asyncio.Event,
    progress: Progress,
    ask: Ask,
    poll: tuple[float, float],
) -> int:
    _ready(loaded)
    if any(a.status in OPEN for a in loaded.actions):
        open_ = sum(1 for a in loaded.actions if a.status in OPEN)
        raise MigrationError(f"Lekto lacks {open_} things the plan needs: run prepare first")
    rows = {row.source_id: row for row in state.documents()}
    new = sum(
        1
        for item in loaded.expected.values()
        if item.skip is None
        and (rows.get(item.id) is None or rows[item.id].status not in DOCUMENT_DONE)
    )
    migrated = sum(
        1 for id in loaded.expected if id in rows and rows[id].status in ("done", "duplicate")
    )
    if not ask(f"Take {new} documents over and align {migrated} migrated ones?"):
        return 1
    migration = Run(config, loaded, source, target, state, stop=stop, progress=progress, poll=poll)
    totals = await migration.execute()
    documents = reports.run_documents(state, set(loaded.expected))
    report = {
        **_head(config, "run", loaded.snapshot),
        "totals": reports.totals(totals),
        "document_results": dict(Counter(d["status"] for d in documents)),
        "lanes": reports.lanes(documents),
        "documents": documents,
        "seconds": {k: round(v, 1) for k, v in totals.seconds.items()},
        "source_counts": reports.source_counts(loaded.snapshot),
    }
    _write(config, "run", report)
    progress(
        f"run: {totals.documents} documents, {totals.uploaded} uploaded, {totals.aligned} aligned, "
        f"{totals.resumed} resumed, {totals.duplicates} duplicates, {totals.skipped} skipped, "
        f"{totals.deleted} deleted in Lekto, {totals.failed} failed, {totals.stopped} not started"
    )
    if stop.is_set():
        return 130
    return 1 if totals.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
