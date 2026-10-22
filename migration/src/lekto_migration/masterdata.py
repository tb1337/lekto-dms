"""What Lekto needs before the documents come: the users, contacts, document types, tags with
their hierarchy, groups, fields and spaces the plan and the selected documents name. `needs`
works it out (`check` shows it, `run` refuses while anything is open); `prepare` creates it.
A missing object the plan may not create (no `create: true`) is an error of the plan."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lekto_migration.directory import Directory
from lekto_migration.expect import Expected, FieldInfo, targets_of
from lekto_migration.lekto import ApiError, Lekto
from lekto_migration.mapping import EDIT, select_options
from lekto_migration.paperless import Snapshot
from lekto_migration.plan import SECTIONS, TAG_SCOPES, Plan, Target, norm

EXISTS, CREATE, UPDATE, MISSING = "exists", "create", "update", "missing"
CREATED, UPDATED, FAILED = "created", "updated", "failed"
OPEN = (CREATE, UPDATE, MISSING)
PATHS = {"contact": "/contacts", "document_type": "/document-types"}
TITLES = {
    "user": "Users",
    "contact": "Contacts",
    "document_type": "Document types",
    "tag": "Tags",
    "topic": "Topics",
    "contact_group": "Contact groups",
    "type_group": "Document type groups",
    "field": "Fields",
    "choices": "Options of fields",
    "group": "Group members",
    "space": "Spaces",
}
ORDER = tuple(TITLES)


@dataclass
class Action:
    """One thing Lekto needs: it exists, `prepare` creates or changes it, or it is missing
    and the plan may not create it. `data` holds what `prepare` needs to do it."""

    kind: str
    name: str
    status: str
    source: str = ""
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def is_open(actions: Sequence[Action]) -> bool:
    return any(action.status in OPEN for action in actions)


def needs(
    plan: Plan,
    directory: Directory,
    snapshot: Snapshot,
    expected: Sequence[Expected],
    fields: Mapping[str, FieldInfo],
    *,
    recorded: frozenset[str] = frozenset(),
) -> list[Action]:
    """What Lekto needs; `recorded` are the ids of the spaces an earlier `prepare` created
    or completed (from the state)."""
    actions: list[Action] = []
    taken = [item for item in expected if item.skip is None]
    actions += _users(plan, directory, snapshot)
    named, by_value = _named_targets(plan)
    used: dict[str, set[str]] = {kind: set() for kind in ("contact", "document_type", *TAG_SCOPES)}
    for item in taken:
        for kind, value in (
            ("contact", item.contact),
            ("document_type", item.document_type),
            ("topic", item.topic),
        ):
            if value is not None:
                used[kind].add(value)
        used["tag"] |= item.tags
        used["contact_group"] |= item.contact_groups
        used["type_group"] |= item.type_groups
    for kind in ("contact", "document_type", "tag", "topic", "contact_group", "type_group"):
        actions += _objects(kind, named[kind], by_value[kind], used[kind], directory)
    actions += _fields(plan, directory, snapshot, taken, fields)
    actions += _groups(taken, directory)
    actions += _spaces(taken, directory, recorded)
    return sorted(actions, key=lambda a: ORDER.index(a.kind))


def _users(plan: Plan, directory: Directory, snapshot: Snapshot) -> list[Action]:
    inactive = {norm(str(u["username"])) for u in snapshot.users if not u.get("is_active", True)}
    actions: dict[str, Action] = {}
    for entry in plan.entries["users"].values():
        target = next((t for t in entry.targets if t.to == "user"), None)
        if target is None or target.name is None:
            continue
        key = norm(target.name)
        action = actions.get(key)
        if action is None:
            found = directory.find("user", target.name)
            status = EXISTS if found else CREATE if target.create else MISSING
            action = Action("user", target.name, status, f"user '{entry.source}'")
            action.data = {"paperless": [], "id": found["id"] if found else None}
            actions[key] = action
            if found is not None and found.get("active") is False:
                action.notes.append("inactive in Lekto: uploads and gets nothing of the migration")
        action.data["paperless"].append(entry.source)
        if norm(entry.source) in inactive:
            action.data["deactivate"] = plan.settings.deactivate_inactive_users
            if action.status == CREATE and plan.settings.deactivate_inactive_users:
                action.notes.append("inactive in Paperless: deactivated at the end of the run")
    owner = plan.settings.fallback_owner
    if owner is not None and norm(owner) not in actions:
        found = directory.find("user", owner)
        actions[norm(owner)] = Action(
            "user", owner, EXISTS if found else MISSING, "settings.fallback_owner"
        )
    return list(actions.values())


def _named_targets(
    plan: Plan,
) -> tuple[dict[str, dict[str, tuple[Target, str]]], dict[str, bool]]:
    """The objects the plan names, by kind (with the target and where), and whether values
    may name new ones (`by_value` with `create`)."""
    named: dict[str, dict[str, tuple[Target, str]]] = {k: {} for k in TITLES}
    by_value: dict[str, bool] = dict.fromkeys(TITLES, False)
    for section, entry, target in targets_of(plan):
        where = f"{SECTIONS.get(section, 'archive serial number')} '{entry.source}'"
        if target.by_value:
            by_value[target.to] = by_value[target.to] or target.create
        elif target.name is not None and target.to in named:
            current = named[target.to].get(norm(target.name))
            if current is None or (target.create and not current[0].create):
                named[target.to][norm(target.name)] = (target, where)
    return named, by_value


def _objects(
    kind: str,
    named: dict[str, tuple[Target, str]],
    by_value: bool,
    used: set[str],
    directory: Directory,
) -> list[Action]:
    actions: dict[str, Action] = {}
    scope = TAG_SCOPES.get(kind)

    def add(name: str, create: bool, where: str, parent: str | None = None) -> None:
        if norm(name) in actions:
            return
        found = directory.find(kind, name)
        status = EXISTS if found else CREATE if create else MISSING
        action = Action(kind, name, status, where)
        actions[norm(name)] = action
        if scope is not None:
            action.data["scope"] = scope
            if parent is not None:
                action.data["parent"] = parent
                action.detail = f"below {parent}"
                if found is not None:
                    above = directory.by_id(kind, str(found.get("parent_id") or ""))
                    if above is None or norm(above["name"]) != norm(parent):
                        action.notes.append(f"Lekto has it elsewhere; the plan says below {parent}")
                add(parent, create, f"the tag above {name}")

    for target, where in named.values():
        assert target.name is not None
        add(target.name, target.create, where, target.parent)
    for name in sorted(used, key=norm):
        add(name, by_value, "a value of a custom field")
    return _parents_first(list(actions.values()))


def _parents_first(actions: list[Action]) -> list[Action]:
    by_name = {norm(a.name): a for a in actions}

    def depth(action: Action, seen: frozenset[str] = frozenset()) -> int:
        parent = action.data.get("parent")
        if parent is None or norm(parent) in seen or norm(parent) not in by_name:
            return 0
        return 1 + depth(by_name[norm(parent)], seen | {norm(action.name)})

    return sorted(actions, key=depth)


def _fields(
    plan: Plan,
    directory: Directory,
    snapshot: Snapshot,
    taken: Sequence[Expected],
    infos: Mapping[str, FieldInfo],
) -> list[Action]:
    named, _ = _named_targets(plan)
    used: dict[str, set[str]] = {}
    for item in taken:
        for name, value in item.fields.items():
            if isinstance(value, str):
                used.setdefault(norm(name), set()).add(value)
    options: dict[str, list[str]] = {}
    for section, entry, target in targets_of(plan):
        if section != "custom_fields" or target.to != "field" or target.name is None:
            continue
        source = next(
            (f for f in snapshot.custom_fields if norm(str(f["name"])) == norm(entry.source)), None
        )
        if source is not None and source.get("data_type") == "select":
            labels = list(dict.fromkeys(select_options(source).values()))
            options.setdefault(norm(target.name), []).extend(labels)
    actions = []
    for key, info in infos.items():
        named_field = named["field"].get(key)
        where = named_field[1] if named_field else ""
        found = directory.find("field", info.name)
        if found is None:
            create = named_field is not None and named_field[0].create
            action = Action("field", info.name, CREATE if create else MISSING, where)
            action.detail = info.data_type
            action.data = {"data_type": info.data_type}
            if info.data_type == "choice":
                wanted = list(dict.fromkeys([*options.get(key, []), *sorted(used.get(key, ()))]))
                action.data["choices"] = wanted
                action.detail = f"choice: {', '.join(wanted)}"
            actions.append(action)
            continue
        actions.append(Action("field", info.name, EXISTS, where, info.data_type))
        if info.data_type == "choice":
            have = list(found.get("choices") or [])
            missing = [c for c in sorted(used.get(key, ())) if c not in have]
            if missing:
                action = Action("choices", info.name, UPDATE, where, ", ".join(missing))
                action.data = {"id": found["id"], "choices": [*have, *missing]}
                actions.append(action)
    return actions


def _groups(taken: Sequence[Expected], directory: Directory) -> list[Action]:
    """Contacts and types in the groups the documents' objects name."""
    pairs: dict[tuple[str, str, str], None] = {}
    for item in taken:
        if item.contact is not None:
            for group in item.contact_groups:
                pairs[("contact", item.contact, group)] = None
        if item.document_type is not None:
            for group in item.type_groups:
                pairs[("document_type", item.document_type, group)] = None
    actions = []
    for kind, member, group in pairs:
        group_kind = "contact_group" if kind == "contact" else "type_group"
        found, holder = directory.find(kind, member), directory.find(group_kind, group)
        inside = (
            found is not None
            and holder is not None
            and holder["id"] in (found.get("group_ids") or [])
        )
        action = Action("group", f"{member} in {group}", EXISTS if inside else UPDATE)
        action.data = {"kind": kind, "member": member, "group": group}
        actions.append(action)
    return actions


def _spaces(
    taken: Sequence[Expected], directory: Directory, recorded: frozenset[str]
) -> list[Action]:
    """The shared spaces the documents go to, with the members `prepare` adds or raises
    (`members`; edit wins, never fewer) and those the space has afterwards (`after`).

    Every uploader edits the space their documents go to, so they see their own documents,
    in a space the plan names too, whether it exists or not. The members Paperless'
    permissions name join a space the migration has not touched yet; a space an earlier
    `prepare` created or completed (`recorded`, by Lekto id) gets only missing uploaders, so
    a member an editor took out since stays out. The notes say who gains access and who sees
    documents Paperless kept from them."""
    spaces: dict[str, _Space] = {}
    admin = str(directory.admin["username"])
    for item in taken:
        if item.space is None:
            continue
        space = spaces.get(norm(item.space))
        if space is None:
            space = spaces[norm(item.space)] = _Space(item.space, item.sources.get("space", ""))
        uploader = item.uploader or admin
        _join(space.uploaders, uploader, EDIT)
        for name, role in item.members:
            _join(space.permitted, name, role)
        allowed = frozenset({norm(uploader), *(norm(name) for name, _ in item.members)})
        space.documents.append((uploader, allowed))
    return [_space_action(space, directory, recorded) for space in spaces.values()]


@dataclass
class _Space:
    """What the documents planned into a shared space ask of it."""

    name: str
    source: str
    uploaders: dict[str, tuple[str, str]] = field(default_factory=dict)  # norm -> (name, edit)
    permitted: dict[str, tuple[str, str]] = field(default_factory=dict)  # by the permissions
    # (uploader, norm names of those Paperless lets see the document), per document
    documents: list[tuple[str, frozenset[str]]] = field(default_factory=list)


def _space_action(space: _Space, directory: Directory, recorded: frozenset[str]) -> Action:
    action = Action("space", space.name, EXISTS, space.source)
    found = directory.space(space.name)
    have = {} if found is None else members_of(found, directory)
    wanted = dict(space.uploaders)
    if found is None or str(found["id"]) not in recorded:
        for name, role in space.permitted.values():
            _join(wanted, name, role)
    added = [
        (name, role)
        for key, (name, role) in wanted.items()
        if not _covers(have[key][1] if key in have else None, role)
    ]
    after = dict(have)
    for name, role in added:
        after[norm(name)] = (name, role)
    if found is None:
        action.status = CREATE
    else:
        action.data["id"] = found["id"]
        if added:
            action.status = UPDATE
            action.notes.append(
                "gains access: "
                + ", ".join(
                    f"{name} ({have[norm(name)][1]} → {role})"
                    if norm(name) in have
                    else f"{name} ({role})"
                    for name, role in _sorted(added)
                )
            )
    action.data["members"] = _sorted(added)
    action.data["after"] = _sorted(after.values())
    if action.data["after"]:
        action.detail = ", ".join(f"{name}: {role}" for name, role in action.data["after"])
    action.notes += _beyond(space, after)
    return action


def members_of(space: dict[str, Any], directory: Directory) -> dict[str, tuple[str, str]]:
    """The members of a Lekto space by norm(user name): (name, role)."""
    out: dict[str, tuple[str, str]] = {}
    for member in space.get("members") or []:
        user = directory.by_id("user", str(member["user_id"]))
        name = str(user["username"]) if user is not None else str(member["user_id"])
        out[norm(name)] = (name, str(member["role"]))
    return out


def _beyond(space: _Space, after: Mapping[str, tuple[str, str]]) -> list[str]:
    """Who of the members sees documents of an uploader that Paperless kept from them."""
    gains: dict[str, set[str]] = {}  # norm(uploader) -> norm names of members who gain
    names = {key: name for key, (name, _) in after.items()}
    for uploader, allowed in space.documents:
        names.setdefault(norm(uploader), uploader)
        gains.setdefault(norm(uploader), set()).update(k for k in after if k not in allowed)
    notes, told = [], set()
    for owner in sorted(gains):
        for viewer in sorted(gains[owner]):
            if (owner, viewer) in told:
                continue
            if owner in gains.get(viewer, ()):
                first, second = sorted((names[owner], names[viewer]), key=norm)
                notes.append(f"{first} and {second} see each other's documents in '{space.name}'")
                told |= {(owner, viewer), (viewer, owner)}
            else:
                notes.append(
                    f"{names[viewer]} sees documents of {names[owner]} in '{space.name}' "
                    "that Paperless kept from them"
                )
                told.add((owner, viewer))
    return notes


def visible_to(
    item: Expected, actions: Sequence[Action], directory: Directory
) -> tuple[list[tuple[str, str]], list[str]]:
    """Who sees a document in Lekto once `prepare` has run, (name, role), and who of them
    Paperless kept it from."""
    uploader = item.uploader or str(directory.admin["username"])
    if item.space is not None:
        action = next(
            (a for a in actions if a.kind == "space" and norm(a.name) == norm(item.space)), None
        )
        members = list(action.data.get("after", ())) if action is not None else []
    else:
        user = directory.find("user", uploader)
        personal = directory.personal_space(str(user["id"])) if user is not None else None
        found = members_of(personal, directory) if personal is not None else {}
        found.setdefault(norm(uploader), (uploader, EDIT))
        members = _sorted(found.values())
    allowed = {norm(uploader), *(norm(name) for name, _ in item.members)}
    return members, [name for name, _ in members if norm(name) not in allowed]


def _sorted(members: Any) -> list[tuple[str, str]]:
    return sorted(members, key=lambda item: norm(item[0]))


def _join(members: dict[str, tuple[str, str]], name: str, role: str) -> None:
    """Add a member; edit wins over read."""
    if members.get(norm(name), ("", ""))[1] != EDIT:
        members[norm(name)] = (name, role)


def _covers(have: str | None, role: str) -> bool:
    return have in (EDIT, role)


# --- prepare ----------------------------------------------------------------------------------

Progress = Callable[[str], None]


async def prepare(
    actions: Sequence[Action],
    lekto: Lekto,
    directory: Directory,
    *,
    ours: frozenset[str] = frozenset(),
    record: Callable[[Action, str], None] = lambda action, id: None,
    progress: Progress = lambda message: None,
) -> None:
    """Create and change what is open, in order (users, objects with their parents, fields,
    groups, spaces). A failure is noted at its action; the rest goes on.

    Lekto adds only active users to a space: users the migration created (`ours`, by id) and
    deactivated before are active while their spaces are made, and deactivated again at the
    end."""
    woken = await _wake(actions, lekto, directory, ours, progress)
    try:
        for action in actions:
            if action.status not in (CREATE, UPDATE):
                continue
            try:
                id = await _do(action, lekto, directory)
            except ApiError as error:
                progress(f"cannot {action.status} {action.kind} '{action.name}': {error}")
                action.status = FAILED
                action.notes.append(str(error))
                continue
            action.status = CREATED if action.status == CREATE else UPDATED
            if id is not None:
                record(action, id)
    finally:
        for user in woken:
            try:
                await lekto.set_active(str(user["id"]), False)
                user["active"] = False
            except ApiError as error:
                progress(f"cannot deactivate {user['username']} again: {error}")


async def _wake(
    actions: Sequence[Action],
    lekto: Lekto,
    directory: Directory,
    ours: frozenset[str],
    progress: Progress,
) -> list[dict[str, Any]]:
    """Activate the deactivated users of `ours` that become members of a space."""
    woken: list[dict[str, Any]] = []
    for action in actions:
        if action.kind != "space" or action.status not in (CREATE, UPDATE):
            continue
        for name, _ in action.data["members"]:
            user = directory.find("user", name)
            if user is None or user.get("active") is not False or str(user["id"]) not in ours:
                continue
            try:
                await lekto.set_active(str(user["id"]), True)
            except ApiError as error:
                progress(f"cannot activate {name} to make them a member: {error}")
                continue
            user["active"] = True
            woken.append(user)
    return woken


async def _do(action: Action, lekto: Lekto, directory: Directory) -> str | None:
    kind, name = action.kind, action.name
    if kind == "user":
        found = await _created(
            lambda: lekto.create_user(name), lambda: _relist(lekto, "/users", "username", name)
        )
        directory.add("user", found)
        return str(found["id"])
    if kind in PATHS:
        path = PATHS[kind]
        found = await _created(
            lambda: lekto.create_named(path, name), lambda: _relist(lekto, path, "name", name)
        )
        directory.add(kind, found)
        return str(found["id"])
    if kind in TAG_SCOPES:
        scope, parent = action.data["scope"], action.data.get("parent")
        above = directory.find(kind, parent) if parent is not None else None
        if parent is not None and above is None:
            raise ApiError(0, f"the tag above, {parent}, does not exist")
        found = await _created(
            lambda: lekto.create_tag(name, scope, above["id"] if above else None),
            lambda: _relist(lekto, "/tags", "name", name, {"scope": scope}),
        )
        directory.add(kind, found)
        return str(found["id"])
    if kind == "field":
        data_type, choices = action.data["data_type"], tuple(action.data.get("choices", ()))
        found = await _created(
            lambda: lekto.create_field(name, data_type, choices),
            lambda: _relist(lekto, "/fields", "name", name),
        )
        directory.add("field", found)
        return str(found["id"])
    if kind == "choices":
        found = await lekto.set_choices(action.data["id"], action.data["choices"])
        directory.add("field", found)
        return None
    if kind == "group":
        member_kind = action.data["kind"]
        group_kind = "contact_group" if member_kind == "contact" else "type_group"
        member = directory.find(member_kind, action.data["member"])
        group = directory.find(group_kind, action.data["group"])
        if member is None or group is None:
            raise ApiError(0, "the member or the group does not exist")
        groups = [*(member.get("group_ids") or []), group["id"]]
        found = await lekto.set_groups(PATHS[member_kind], member["id"], groups)
        directory.add(member_kind, found)
        return None
    if kind == "space":
        members: dict[str, str] = {}  # user id -> role
        for user_name, role in action.data["members"]:
            user = directory.find("user", user_name)
            if user is None:
                raise ApiError(0, f"the user {user_name} does not exist")
            members[str(user["id"])] = role
        space = directory.space(name)
        if space is None:
            space = await _created(
                lambda: lekto.create_space(name, members), lambda: _relist_space(lekto, name)
            )
            directory.spaces.append(space)
        have = {m["user_id"]: m["role"] for m in space.get("members") or []}
        for user_id, role in members.items():
            if not _covers(have.get(user_id), role):
                await lekto.set_member(space["id"], user_id, role)
                space["members"] = [
                    *(m for m in space.get("members") or [] if m["user_id"] != user_id),
                    {"user_id": user_id, "role": role},
                ]
        return str(space["id"])
    raise AssertionError(kind)


async def _created(create: Any, again: Any) -> dict[str, Any]:
    """Create; a 409 after an earlier attempt whose answer was lost finds it by name."""
    try:
        return dict(await create())
    except ApiError as error:
        if error.status != 409:
            raise
        found = await again()
        if found is None:
            raise
        return dict(found)


async def _relist(
    lekto: Lekto, path: str, key: str, name: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    return next((i for i in await lekto.items(path, params) if norm(i[key]) == norm(name)), None)


async def _relist_space(lekto: Lekto, name: str) -> dict[str, Any] | None:
    """The shared space of this name (a personal space has a fixed name of its own)."""
    return next(
        (
            s
            for s in await lekto.items("/spaces", params={"all_users": "true"})
            if s.get("personal_of") is None and norm(s["name"]) == norm(name)
        ),
        None,
    )
