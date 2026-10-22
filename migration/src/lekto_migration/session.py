"""What `check`, `prepare` and `run` start from: Paperless and Lekto as they are, the plan, the
documents it selects and what each becomes, and what Lekto needs for them."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ruamel.yaml.comments import CommentedMap

from lekto_migration import plan as plans
from lekto_migration.config import Config, public
from lekto_migration.directory import Directory
from lekto_migration.expect import Context, Expected, FieldInfo, expect, field_infos
from lekto_migration.lekto import ApiError, Lekto
from lekto_migration.masterdata import Action, needs
from lekto_migration.paperless import Paperless, PaperlessError, Snapshot
from lekto_migration.plan import Plan, PlanError
from lekto_migration.select import Names, names_of, selected
from lekto_migration.state import State
from lekto_migration.survey import defaults

Progress = Callable[[str], None]
Ask = Callable[[str], bool]


class MigrationError(Exception):
    """The command cannot go on (a wrong key, an unreachable server, a plan that cannot be
    used); nothing more is done."""


@dataclass
class Loaded:
    snapshot: Snapshot
    plan: Plan
    document: CommentedMap
    directory: Directory
    names: Names
    selected: list[dict[str, Any]]  # the Paperless documents the plan takes over
    expected: dict[int, Expected]  # by Paperless id, for the selected ones
    fields: dict[str, FieldInfo]
    actions: list[Action]
    outdated: list[str] = field(default_factory=list)  # Paperless objects the plan lacks
    ours: set[str] = field(default_factory=set)  # Lekto users the migration created

    def is_selected(self, id: int) -> bool:
        return id in self.expected


async def admin(target: Lekto, *, write: bool) -> dict[str, Any]:
    """The executing admin; the key must be an admin's, and one that writes to write."""
    try:
        me = await target.me()
    except ApiError as error:
        raise MigrationError(f"Lekto refused the API key: {error}") from None
    if me["user"].get("role") != "admin":
        raise MigrationError("the Lekto API key must belong to an admin")
    if write and me.get("token_scope") != "read_write":
        raise MigrationError("the Lekto API key needs the scope read_write")
    return dict(me["user"])


async def read(
    source: Paperless, target: Lekto | None, *, write: bool, progress: Progress
) -> tuple[Snapshot, Directory]:
    try:
        snapshot = await source.snapshot()
    except PaperlessError as error:
        raise MigrationError(str(error)) from None
    progress(
        f"Paperless {snapshot.version}: {len(snapshot.documents)} documents, "
        f"{len(snapshot.users)} users"
    )
    me = await admin(target, write=write) if target is not None else None
    try:
        directory = await Directory.of(target, me)
    except ApiError as error:
        raise MigrationError(f"cannot read Lekto: {error}") from None
    return snapshot, directory


def load_plan(config: Config) -> tuple[Plan, CommentedMap]:
    """The plan, if it belongs to this Paperless and this Lekto."""
    if not config.plan.exists():
        raise MigrationError(f"there is no plan at {config.plan}: run `plan` first")
    try:
        plan, document = plans.load(config.plan)
    except PlanError as error:
        raise MigrationError(
            f"the plan {config.plan} cannot be used:\n  " + "\n  ".join(error.problems)
        ) from None
    bound(document, config)
    return plan, document


def bound(document: CommentedMap, config: Config) -> None:
    """A plan belongs to one Paperless and one Lekto: another one is refused."""
    for key, url in (("source", config.paperless_url), ("target", config.lekto_url)):
        written = str(document.get(key) or "").rstrip("/")
        if url is not None and written and written != (public(url) or "").rstrip("/"):
            raise MigrationError(
                f"the plan {config.plan} is for another {key} ({written}); use another --plan"
            )


def outdated(plan: Plan, snapshot: Snapshot, directory: Directory) -> list[str]:
    """The Paperless objects the plan has no entry for (`plan` adds them)."""
    missing = []
    for section, entries in defaults(snapshot, directory).items():
        for name in entries:
            if plan.entry(section, name) is None:
                missing.append(f"{section}.{name}")
    return missing


async def load(
    config: Config,
    source: Paperless,
    target: Lekto | None,
    state: State,
    *,
    write: bool,
    progress: Progress,
    now: datetime | None = None,
) -> Loaded:
    plan, document = load_plan(config)
    snapshot, directory = await read(source, target, write=write, progress=progress)
    names = names_of(snapshot)
    chosen = [d for d in snapshot.documents if selected(plan.selection, d, names)]
    if config.limit is not None:
        chosen = chosen[: config.limit]
    ours = {str(o["lekto_id"]) for o in state.objects("user") if o["status"] == "new"}
    inactive = frozenset(
        key
        for key, user in directory.users.items()
        if user.get("active") is False and str(user["id"]) not in ours
    )
    fields = field_infos(plan, directory, snapshot)
    context = Context(
        plan=plan,
        snapshot=snapshot,
        fields=fields,
        admin=str(directory.admin["username"]),
        inactive=inactive,
        now=now,
    )
    expected = {int(d["id"]): expect(d, context) for d in chosen}
    recorded = frozenset(str(o["lekto_id"]) for o in state.objects("space") if o["lekto_id"])
    profiled = frozenset(str(o["lekto_id"]) for o in state.objects("profile") if o["lekto_id"])
    actions = needs(
        plan,
        directory,
        snapshot,
        list(expected.values()),
        fields,
        recorded=recorded,
        profiled=profiled,
    )
    progress(f"the plan takes {len(chosen)} of {len(snapshot.documents)} documents over")
    return Loaded(
        snapshot=snapshot,
        plan=plan,
        document=document,
        directory=directory,
        names=names,
        selected=chosen,
        expected=expected,
        fields=fields,
        actions=actions,
        outdated=outdated(plan, snapshot, directory),
        ours=ours,
    )


def unmanaged(state: State) -> set[str]:
    """Fields the alignment leaves alone: the notes field of migrations before the plan."""
    return {
        str(o["lekto_id"])
        for o in state.objects("field")
        if o["source_id"] == "notes" and o["lekto_id"] is not None
    }
