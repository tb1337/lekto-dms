"""Rights by the members of a space

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-21 23:00:00.000000

Rights hang on spaces alone (Tobi, 21.10.2026): a space has members who read or edit it, and a
document has no owner any more, only who uploaded it.

- Every user's default space becomes their personal space (`spaces.personal_of`, stored name
  "Personal"); a user without one gets one. The owner of every other space becomes an editor
  of it, a share `read` a reader, a share `read_write` an editor (`space_members` replaces
  `space_shares`). Names were
  unique per owner and are unique among the spaces that are nobody's personal one now: of
  spaces with the same name, the oldest keeps it, the others get " (<owner's username>)"
  (shortened to fit, never a name another space keeps).
- `documents.owner_id` becomes `uploaded_by` (cleared with the user's account). Every file
  exists once per installation (Tobi, 22.10.2026): the original is unique, no longer per
  owner. Two documents of two owners with the same file stop the revision at the index; it
  does not sort them out.
- A user rule becomes a rule of its owner's personal space (`rules.space_id`, scope `space`).
- A document that is new stays new for who uploaded it; the other editors of its space, in
  whose inbox it stands now, have seen it.
- The variable `owner` in templates becomes `uploaded_by` (rules and title patterns), as 0024
  renamed `drawer`; a template that uses `uploaded_by` otherwise stops the revision. The scope
  of rule reports in the processing log becomes `space`.

Postgres changes the tables in place. On SQLite `spaces`, `documents` and `rules` are built
anew without a rename (as 0024 and 0027 did): `migrate` turns foreign keys off meanwhile.

The downgrade goes back as far as the data allow: a personal space becomes the default space
of its user, any other space is owned by its oldest editor and shared with the rest (edit as
`read_write`); a document is owned by who uploaded it while they are a member of its space,
otherwise by its space's owner; a space rule is a user rule of its space's owner. It stops if
that gives an owner the same file twice, and where 0.4 could not load the data: a shared
personal space, a global rule that does more than tag, set fields and force a review.
"""

import os
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from liquid import parse
from liquid.exceptions import LiquidError

from lekto.adapters.outbound.sql import types

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERSONAL = "Personal"
_DEFAULT = "Default"
_MAX_NAME = 200  # as `domain.validation.MAX_NAME`


def name_key(name: str) -> str:
    """As `domain.validation.name_key` has it (the revision keeps its own)."""
    return name.strip().casefold()


_users = sa.table(
    "users",
    sa.column("id", sa.Uuid()),
    sa.column("username", sa.Text()),
    sa.column("created_at", types.UtcDateTime()),
)
_old_spaces = sa.table(
    "spaces",
    sa.column("id", sa.Uuid()),
    sa.column("owner_id", sa.Uuid()),
    sa.column("name", sa.Text()),
    sa.column("name_key", sa.Text()),
    sa.column("is_default", sa.Boolean()),
    sa.column("created_at", types.UtcDateTime()),
    sa.column("version", sa.Integer()),
)
_new_spaces = sa.table(
    "spaces",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.Text()),
    sa.column("name_key", sa.Text()),
    sa.column("personal_of", sa.Uuid()),
    sa.column("created_at", types.UtcDateTime()),
    sa.column("version", sa.Integer()),
)
_shares = sa.table(
    "space_shares",
    sa.column("space_id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("level", sa.Text()),
)
_members = sa.table(
    "space_members",
    sa.column("space_id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("role", sa.Text()),
)
_old_documents = sa.table(
    "documents",
    sa.column("id", sa.Uuid()),
    sa.column("owner_id", sa.Uuid()),
    sa.column("space_id", sa.Uuid()),
    sa.column("sha256", sa.String()),
)
_new_documents = sa.table(
    "documents",
    sa.column("id", sa.Uuid()),
    sa.column("uploaded_by", sa.Uuid()),
    sa.column("space_id", sa.Uuid()),
    sa.column("sha256", sa.String()),
)
_old_rules = sa.table("rules", sa.column("id", sa.Uuid()), sa.column("owner_id", sa.Uuid()))
_new_rules = sa.table("rules", sa.column("id", sa.Uuid()), sa.column("space_id", sa.Uuid()))


@dataclass
class _Space:
    id: UUID
    name: str
    created_at: Any
    version: int
    owner: UUID | None = None  # the old model
    default: bool = False
    personal_of: UUID | None = None  # the new model
    members: dict[UUID, str] | None = None
    created: bool = False  # a personal space the revision adds


def upgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    if sqlite and connection.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError(
            "revision 0033 builds tables anew on SQLite: run it with foreign keys off "
            "(as migrate does), or the rows that refer to them go too"
        )
    usernames = {row.id: row.username for row in connection.execute(sa.select(_users))}
    spaces = _spaces_up(connection, usernames)
    if not sqlite:
        _add_missing_defaults(connection, spaces, usernames)
    defaults = {space.owner: space.id for space in spaces if space.default}
    rule_owners = {row.id: row.owner_id for row in connection.execute(sa.select(_old_rules))}
    if sqlite:
        _rebuild_up(spaces, rule_owners, defaults)
    else:
        _alter_up(spaces, rule_owners, defaults)
    _keep_new_as_it_was(connection, spaces)
    _rename_stored("owner", "uploaded_by")
    _rename_scopes("user", "space")


def downgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    if sqlite and connection.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError(
            "revision 0033 builds tables anew on SQLite: run it with foreign keys off "
            "(as migrate does), or the rows that refer to them go too"
        )
    users = {row.id: row for row in connection.execute(sa.select(_users))}
    spaces = _spaces_down(connection, users)
    _check_way_back(connection, spaces, users)
    owners = {space.id: space.owner for space in spaces}
    members = {space.id: space.members or {} for space in spaces}
    document_owners: dict[UUID, UUID] = {}
    for row in connection.execute(sa.select(_new_documents).order_by(_new_documents.c.id)):
        # Who uploaded it owns it again while they are a member of its space; one who left
        # it, or handed the document over, does not get it back: its space's owner does.
        member = row.uploaded_by in members[row.space_id]
        owner = row.uploaded_by if member else owners[row.space_id]
        assert owner is not None
        document_owners[row.id] = owner
    rule_spaces = {row.id: row.space_id for row in connection.execute(sa.select(_new_rules))}
    rule_owners = {
        rule: None if space is None else owners[space] for rule, space in rule_spaces.items()
    }
    _rename_stored("uploaded_by", "owner")
    _rename_scopes("space", "user")
    if sqlite:
        _rebuild_down(spaces, document_owners, rule_owners)
    else:
        _alter_down(spaces, document_owners, rule_owners)


# --- the data ---------------------------------------------------------------------------------


def _spaces_up(connection: sa.Connection, usernames: dict[UUID, str]) -> list[_Space]:
    """The spaces with their members and new names."""
    spaces = [
        _Space(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            version=row.version,
            owner=row.owner_id,
            default=bool(row.is_default),
        )
        for row in connection.execute(sa.select(_old_spaces))
    ]
    shares: dict[UUID, dict[UUID, str]] = defaultdict(dict)
    for row in connection.execute(sa.select(_shares)):
        shares[row.space_id][row.user_id] = "edit" if row.level == "read_write" else "read"
    with_default = {space.owner for space in spaces if space.default}
    for user in usernames:
        if user not in with_default:
            spaces.append(
                _Space(
                    id=_new_id(),
                    name=_PERSONAL,
                    created_at=datetime.now(UTC),
                    version=1,
                    owner=user,
                    default=True,
                    created=True,
                )
            )
    ordered = sorted(spaces, key=lambda item: (item.created_at, str(item.id)))
    taken: set[str] = set()
    renamed: list[_Space] = []
    for space in ordered:
        assert space.owner is not None
        space.members = {**shares[space.id], space.owner: "edit"}
        if space.default:
            space.personal_of, space.name = space.owner, _PERSONAL
        elif name_key(space.name) in taken:
            renamed.append(space)
        else:
            taken.add(name_key(space.name))
    # The oldest space of a name keeps it, and no name a person chose gives way to one the
    # revision makes up.
    for space in renamed:
        assert space.owner is not None
        space.name = _free_name(space.name, str(usernames.get(space.owner, space.owner)), taken)
        taken.add(name_key(space.name))
    return spaces


def _free_name(name: str, username: str, taken: set[str]) -> str:
    """`name` with " (<username>)" (and a number) that no other space has, within the length
    of a name (the name is shortened to make room)."""
    number = 1
    while True:
        suffix = f" ({username})" if number == 1 else f" ({username} {number})"
        candidate = f"{name[: max(1, _MAX_NAME - len(suffix))].rstrip()}{suffix}"[:_MAX_NAME]
        if name_key(candidate) not in taken:
            return candidate
        number += 1


def _add_missing_defaults(
    connection: sa.Connection, spaces: list[_Space], usernames: dict[UUID, str]
) -> None:
    """Postgres changes `spaces` in place: the personal spaces the revision adds are stored as
    default spaces first."""
    for space in spaces:
        if space.created:
            connection.execute(
                _old_spaces.insert().values(
                    id=space.id,
                    owner_id=space.owner,
                    name=f"{_PERSONAL} {space.id}",  # renamed below; no name of theirs
                    name_key=name_key(f"{_PERSONAL} {space.id}"),
                    is_default=True,
                    created_at=space.created_at,
                    version=space.version,
                )
            )


def _new_id() -> uuid.UUID:
    """A UUIDv7, as `lekto.core.domain.ids.new_id` makes it today (a revision keeps its own
    copy)."""
    milliseconds = time.time_ns() // 1_000_000 & ((1 << 48) - 1)
    random = int.from_bytes(os.urandom(10))
    value = milliseconds << 80 | random
    value = value & ~(0xF << 76) | 0x7 << 76  # version 7
    value = value & ~(0x3 << 62) | 0x2 << 62  # variant RFC 9562
    return uuid.UUID(int=value)


_seen = sa.table(
    "inbox_seen",
    sa.column("user_id", sa.Uuid()),
    sa.column("document_id", sa.Uuid()),
    sa.column("seen_at", types.UtcDateTime()),
)
_new_documents_at = sa.table(
    "documents",
    sa.column("id", sa.Uuid()),
    sa.column("space_id", sa.Uuid()),
    sa.column("uploaded_by", sa.Uuid()),
    sa.column("new_at", types.UtcDateTime()),
)


def _keep_new_as_it_was(connection: sa.Connection, spaces: Iterable[_Space]) -> None:
    """Until 0.5 a document stood in its owner's inbox only; now in the inbox of every editor
    of its space. What was new for its owner stays new for them; for the other editors (a
    space's owner, a sharer with `read_write`) nothing old turns up as new: they have seen it."""
    editors = {
        space.id: {user for user, role in (space.members or {}).items() if role == "edit"}
        for space in spaces
    }
    marked = {
        (row.user_id, row.document_id)
        for row in connection.execute(sa.select(_seen.c.user_id, _seen.c.document_id))
    }
    now = datetime.now(UTC)
    rows = [
        {"user_id": user, "document_id": row.id, "seen_at": now}
        for row in connection.execute(
            sa.select(_new_documents_at).where(_new_documents_at.c.new_at.is_not(None))
        )
        for user in sorted(editors.get(row.space_id, ()), key=str)
        if user != row.uploaded_by and (user, row.id) not in marked
    ]
    if rows:
        connection.execute(_seen.insert(), rows)


def _spaces_down(connection: sa.Connection, users: dict[UUID, Any]) -> list[_Space]:
    spaces = [
        _Space(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            version=row.version,
            personal_of=row.personal_of,
        )
        for row in connection.execute(sa.select(_new_spaces))
    ]
    members: dict[UUID, dict[UUID, str]] = defaultdict(dict)
    for row in connection.execute(sa.select(_members)):
        members[row.space_id][row.user_id] = row.role
    names: dict[UUID, set[str]] = defaultdict(set)
    for space in sorted(spaces, key=lambda item: item.personal_of is None):
        space.members = members[space.id]
        if space.personal_of is not None:
            space.owner, space.default, space.name = space.personal_of, True, _DEFAULT
        else:
            editors = [user for user, role in space.members.items() if role == "edit"]
            space.owner = min(editors, key=lambda user: (users[user].created_at, str(user)))
            name = space.name
            number = 2
            while name_key(name) in names[space.owner]:
                name = f"{space.name} {number}"
                number += 1
            space.name = name
        names[space.owner].add(name_key(space.name))
    return spaces


# What a global rule could do before 0.5 (`check_scope` of 0.4), and the rule of a title
# pattern besides.
_GLOBAL_ACTIONS = frozenset({"add_tags", "remove_tags", "set_field", "force_review"})
_rule_versions = sa.table(
    "rule_versions",
    sa.column("rule_id", sa.Uuid()),
    sa.column("number", sa.Integer()),
    sa.column("name", sa.Text()),
    sa.column("actions", types.json_type()),
)
_scoped_rules = sa.table(
    "rules",
    sa.column("id", sa.Uuid()),
    sa.column("scope", sa.Text()),
    sa.column("current_version", sa.Integer()),
)
_title_rules = sa.table("title_pattern_rules", sa.column("rule_id", sa.Uuid()))


def _check_way_back(
    connection: sa.Connection, spaces: list[_Space], users: dict[UUID, Any]
) -> None:
    """Stop the downgrade where 0.4 could not load what 0.5 stored: a shared personal space (a
    default space was never shared) and a global rule that does more than tag, set fields and
    force a review."""
    problems = [
        f"the personal space of {users[space.personal_of].username} is shared; remove its "
        "other members first"
        for space in spaces
        if space.personal_of is not None and set(space.members or {}) - {space.personal_of}
    ]
    managed = {row.rule_id for row in connection.execute(sa.select(_title_rules))}
    current = (
        sa.select(_scoped_rules.c.id, _rule_versions.c.name, _rule_versions.c.actions)
        .join(
            _rule_versions,
            (_rule_versions.c.rule_id == _scoped_rules.c.id)
            & (_rule_versions.c.number == _scoped_rules.c.current_version),
        )
        .where(_scoped_rules.c.scope == "global")
    )
    for row in connection.execute(current):
        allowed = _GLOBAL_ACTIONS | ({"set_title"} if row.id in managed else set())
        beyond = sorted({action["type"] for action in row.actions} - allowed)
        if beyond:
            problems.append(
                f"the global rule '{row.name}' ({row.id}) does {', '.join(beyond)}, which a "
                "global rule could not before 0.5; change or delete it first"
            )
    if problems:
        raise RuntimeError("revision 0033 cannot go back: " + "; ".join(problems))


def _shares_down(spaces: Iterable[_Space]) -> list[dict[str, Any]]:
    return [
        {"space_id": space.id, "user_id": user, "level": "read_write" if role == "edit" else "read"}
        for space in spaces
        for user, role in (space.members or {}).items()
        if user != space.owner
    ]


def _members_up(spaces: Iterable[_Space]) -> list[dict[str, Any]]:
    return [
        {"space_id": space.id, "user_id": user, "role": role}
        for space in spaces
        for user, role in (space.members or {}).items()
    ]


# --- Postgres: in place -----------------------------------------------------------------------


def _alter_up(
    spaces: list[_Space],
    rule_owners: dict[UUID, UUID | None],
    defaults: dict[UUID | None, UUID],
) -> None:
    connection = op.get_bind()
    _create_members()
    if members := _members_up(spaces):
        connection.execute(_members.insert(), members)
    op.add_column("spaces", sa.Column("personal_of", sa.Uuid(), nullable=True))
    spaces_table = sa.table(
        "spaces",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.Text()),
        sa.column("name_key", sa.Text()),
        sa.column("personal_of", sa.Uuid()),
    )
    # The names are unique per owner until here; the new names may not be.
    op.drop_index("uq_spaces_default_owner_id", table_name="spaces")
    op.drop_index("ix_spaces_owner_id_name_key", table_name="spaces")
    for space in spaces:
        connection.execute(
            spaces_table.update()
            .where(spaces_table.c.id == space.id)
            .values(name=space.name, name_key=name_key(space.name), personal_of=space.personal_of)
        )
    op.drop_constraint("fk_spaces_owner_id_users", "spaces", type_="foreignkey")
    op.drop_column("spaces", "owner_id")
    op.drop_column("spaces", "is_default")
    op.create_foreign_key(
        op.f("fk_spaces_personal_of_users"), "spaces", "users", ["personal_of"], ["id"]
    )
    op.create_unique_constraint(op.f("uq_spaces_personal_of"), "spaces", ["personal_of"])
    _create_name_index()
    op.drop_table("space_shares")

    op.drop_index("ix_documents_owner_id_sha256", table_name="documents")
    op.drop_constraint("fk_documents_owner_id_users", "documents", type_="foreignkey")
    op.alter_column("documents", "owner_id", new_column_name="uploaded_by", nullable=True)
    op.create_foreign_key(
        op.f("fk_documents_uploaded_by_users"),
        "documents",
        "users",
        ["uploaded_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_documents_uploaded_by"), "documents", ["uploaded_by"])
    op.create_index(op.f("ix_documents_sha256"), "documents", ["sha256"], unique=True)

    op.add_column("rules", sa.Column("space_id", sa.Uuid(), nullable=True))
    _fill_rule_spaces(rule_owners, defaults)
    op.drop_index("ix_rules_owner_id", table_name="rules")
    op.drop_constraint("fk_rules_owner_id_users", "rules", type_="foreignkey")
    op.drop_column("rules", "owner_id")
    op.create_foreign_key(
        op.f("fk_rules_space_id_spaces"),
        "rules",
        "spaces",
        ["space_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_rules_space_id"), "rules", ["space_id"])


def _alter_down(
    spaces: list[_Space],
    document_owners: dict[UUID, UUID],
    rule_owners: dict[UUID, UUID | None],
) -> None:
    connection = op.get_bind()
    op.add_column("spaces", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.add_column("spaces", sa.Column("is_default", sa.Boolean(), nullable=True))
    # The names are unique among shared spaces until here; per owner they may not be.
    op.drop_index("uq_spaces_name_key", table_name="spaces")
    for space in spaces:
        connection.execute(
            _old_spaces.update()
            .where(_old_spaces.c.id == space.id)
            .values(
                owner_id=space.owner,
                is_default=space.default,
                name=space.name,
                name_key=name_key(space.name),
            )
        )
    op.alter_column("spaces", "owner_id", nullable=False)
    op.alter_column("spaces", "is_default", nullable=False)
    op.drop_constraint("uq_spaces_personal_of", "spaces", type_="unique")
    op.drop_constraint("fk_spaces_personal_of_users", "spaces", type_="foreignkey")
    op.drop_column("spaces", "personal_of")
    op.create_foreign_key(op.f("fk_spaces_owner_id_users"), "spaces", "users", ["owner_id"], ["id"])
    _create_owner_indexes()
    _create_shares()
    if shares := _shares_down(spaces):
        connection.execute(_shares.insert(), shares)
    op.drop_table("space_members")

    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_index("ix_documents_uploaded_by", table_name="documents")
    op.drop_constraint("fk_documents_uploaded_by_users", "documents", type_="foreignkey")
    op.alter_column("documents", "uploaded_by", new_column_name="owner_id")
    _fill_document_owners(document_owners)
    op.alter_column("documents", "owner_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_documents_owner_id_users"), "documents", "users", ["owner_id"], ["id"]
    )
    op.create_index(
        op.f("ix_documents_owner_id_sha256"), "documents", ["owner_id", "sha256"], unique=True
    )

    op.add_column("rules", sa.Column("owner_id", sa.Uuid(), nullable=True))
    rules = sa.table(
        "rules",
        sa.column("id", sa.Uuid()),
        sa.column("owner_id", sa.Uuid()),
        sa.column("scope", sa.Text()),
    )
    for rule, owner in rule_owners.items():
        if owner is not None:
            connection.execute(
                rules.update().where(rules.c.id == rule).values(owner_id=owner, scope="user")
            )
    op.drop_index("ix_rules_space_id", table_name="rules")
    op.drop_constraint("fk_rules_space_id_spaces", "rules", type_="foreignkey")
    op.drop_column("rules", "space_id")
    op.create_foreign_key(op.f("fk_rules_owner_id_users"), "rules", "users", ["owner_id"], ["id"])
    op.create_index(op.f("ix_rules_owner_id"), "rules", ["owner_id"])


# --- SQLite: built anew -----------------------------------------------------------------------

# The columns `documents` keeps, as `tables.py` has them since 0032.
_DOCUMENT_COLUMNS = (
    "id",
    "space_id",
    "sha256",
    "title",
    "title_key",
    "original_filename",
    "media_type",
    "contact_id",
    "document_type_id",
    "topic_id",
    "document_date",
    "channel",
    "lane",
    "processing_status",
    "processing_run",
    "processing_nodes",
    "processing_vision",
    "processing_baseline",
    "processing_decided",
    "page_count",
    "confirmed_at",
    "new_at",
    "created_at",
    "updated_at",
    "version",
)
_RULE_COLUMNS = (
    "id",
    "current_version",
    "enabled",
    "disabled_reason",
    "deleted_at",
    "created_at",
    "updated_at",
    "version",
)


def _rebuild_up(
    spaces: list[_Space],
    rule_owners: dict[UUID, UUID | None],
    defaults: dict[UUID | None, UUID],
) -> None:
    connection = op.get_bind()
    op.drop_table("space_shares")
    op.drop_table("spaces")
    _create_spaces(personal=True)
    _create_members()
    if spaces:
        connection.execute(
            _new_spaces.insert(),
            [
                {
                    "id": space.id,
                    "name": space.name,
                    "name_key": name_key(space.name),
                    "personal_of": space.personal_of,
                    "created_at": space.created_at,
                    "version": space.version,
                }
                for space in spaces
            ],
        )
    if members := _members_up(spaces):
        connection.execute(_members.insert(), members)

    count = _copy_aside("documents")
    op.drop_table("documents")
    _create_documents(uploaded=True)
    columns = ", ".join(_DOCUMENT_COLUMNS)
    op.execute(
        f"INSERT INTO documents ({columns}, uploaded_by) "
        f"SELECT {columns}, owner_id FROM _documents_0033"
    )
    _put_back("documents", count)

    count = _copy_aside("rules")
    op.drop_table("rules")
    _create_rules(space=True)
    columns = ", ".join(_RULE_COLUMNS)
    op.execute(
        f"INSERT INTO rules ({columns}, scope) "
        f"SELECT {columns}, CASE scope WHEN 'user' THEN 'space' ELSE scope END FROM _rules_0033"
    )
    _put_back("rules", count)
    _fill_rule_spaces(rule_owners, defaults)


def _rebuild_down(
    spaces: list[_Space],
    document_owners: dict[UUID, UUID],
    rule_owners: dict[UUID, UUID | None],
) -> None:
    connection = op.get_bind()
    op.drop_table("space_members")
    op.drop_table("spaces")
    _create_spaces(personal=False)
    _create_shares()
    if spaces:
        connection.execute(
            _old_spaces.insert(),
            [
                {
                    "id": space.id,
                    "owner_id": space.owner,
                    "name": space.name,
                    "name_key": name_key(space.name),
                    "is_default": space.default,
                    "created_at": space.created_at,
                    "version": space.version,
                }
                for space in spaces
            ],
        )
    if shares := _shares_down(spaces):
        connection.execute(_shares.insert(), shares)

    count = _copy_aside("documents")
    temporary = sa.table(
        "_documents_0033", sa.column("id", sa.Uuid()), sa.column("uploaded_by", sa.Uuid())
    )
    for document, owner in document_owners.items():
        connection.execute(
            temporary.update().where(temporary.c.id == document).values(uploaded_by=owner)
        )
    op.drop_table("documents")
    _create_documents(uploaded=False)
    columns = ", ".join(_DOCUMENT_COLUMNS)
    op.execute(
        f"INSERT INTO documents ({columns}, owner_id) "
        f"SELECT {columns}, uploaded_by FROM _documents_0033"
    )
    _put_back("documents", count)

    count = _copy_aside("rules")
    op.drop_table("rules")
    _create_rules(space=False)
    columns = ", ".join(_RULE_COLUMNS)
    op.execute(
        f"INSERT INTO rules ({columns}, scope) "
        f"SELECT {columns}, CASE scope WHEN 'space' THEN 'user' ELSE scope END FROM _rules_0033"
    )
    _put_back("rules", count)
    rules = sa.table("rules", sa.column("id", sa.Uuid()), sa.column("owner_id", sa.Uuid()))
    for rule, rule_owner in rule_owners.items():
        if rule_owner is not None:
            connection.execute(rules.update().where(rules.c.id == rule).values(owner_id=rule_owner))


def _copy_aside(table: str) -> int:
    connection = op.get_bind()
    count = int(connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar() or 0)
    op.execute(f"CREATE TEMP TABLE _{table}_0033 AS SELECT * FROM {table}")
    return count


def _put_back(table: str, count: int) -> None:
    connection = op.get_bind()
    op.execute(f"DROP TABLE _{table}_0033")
    copied = connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar()
    if copied != count:
        raise RuntimeError(f"revision 0033 copied {copied} of {count} rows of {table}")


def _fill_rule_spaces(
    rule_owners: dict[UUID, UUID | None], defaults: dict[UUID | None, UUID]
) -> None:
    connection = op.get_bind()
    rules = sa.table(
        "rules",
        sa.column("id", sa.Uuid()),
        sa.column("scope", sa.Text()),
        sa.column("space_id", sa.Uuid()),
    )
    for rule, owner in rule_owners.items():
        if owner is not None:
            connection.execute(
                rules.update()
                .where(rules.c.id == rule)
                .values(space_id=defaults[owner], scope="space")
            )


def _fill_document_owners(document_owners: dict[UUID, UUID]) -> None:
    connection = op.get_bind()
    documents = sa.table("documents", sa.column("id", sa.Uuid()), sa.column("owner_id", sa.Uuid()))
    for document, owner in document_owners.items():
        connection.execute(
            documents.update().where(documents.c.id == document).values(owner_id=owner)
        )


# --- the tables -------------------------------------------------------------------------------


def _create_spaces(*, personal: bool) -> None:
    if personal:
        op.create_table(
            "spaces",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("name_key", sa.Text(), nullable=False),
            sa.Column("personal_of", sa.Uuid(), nullable=True),
            sa.Column("created_at", types.UtcDateTime(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["personal_of"], ["users.id"], name=op.f("fk_spaces_personal_of_users")
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_spaces")),
            sa.UniqueConstraint("personal_of", name=op.f("uq_spaces_personal_of")),
        )
        _create_name_index()
        return
    op.create_table(
        "spaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", types.UtcDateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_spaces_owner_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spaces")),
    )
    _create_owner_indexes()


def _create_name_index() -> None:
    op.create_index(
        "uq_spaces_name_key",
        "spaces",
        ["name_key"],
        unique=True,
        sqlite_where=sa.text("personal_of IS NULL"),
        postgresql_where=sa.text("personal_of IS NULL"),
    )


def _create_owner_indexes() -> None:
    op.create_index(
        op.f("ix_spaces_owner_id_name_key"), "spaces", ["owner_id", "name_key"], unique=True
    )
    op.create_index(
        "uq_spaces_default_owner_id",
        "spaces",
        ["owner_id"],
        unique=True,
        sqlite_where=sa.text("is_default"),
        postgresql_where=sa.text("is_default"),
    )


def _create_members() -> None:
    op.create_table(
        "space_members",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name=op.f("fk_space_members_space_id_spaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_space_members_user_id_users")
        ),
        sa.PrimaryKeyConstraint("space_id", "user_id", name=op.f("pk_space_members")),
    )
    op.create_index(op.f("ix_space_members_user_id"), "space_members", ["user_id"])


def _create_shares() -> None:
    op.create_table(
        "space_shares",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name=op.f("fk_space_shares_space_id_spaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_space_shares_user_id_users")
        ),
        sa.PrimaryKeyConstraint("space_id", "user_id", name=op.f("pk_space_shares")),
    )
    op.create_index(op.f("ix_space_shares_user_id"), "space_shares", ["user_id"])


def _create_documents(*, uploaded: bool) -> None:
    person: list[sa.Column[Any] | sa.Constraint]
    if uploaded:
        person = [
            sa.Column("uploaded_by", sa.Uuid(), nullable=True),
            sa.ForeignKeyConstraint(
                ["uploaded_by"],
                ["users.id"],
                name=op.f("fk_documents_uploaded_by_users"),
                ondelete="SET NULL",
            ),
        ]
    else:
        person = [
            sa.Column("owner_id", sa.Uuid(), nullable=False),
            sa.ForeignKeyConstraint(
                ["owner_id"], ["users.id"], name=op.f("fk_documents_owner_id_users")
            ),
        ]
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("document_type_id", sa.Uuid(), nullable=True),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=False, server_default="api"),
        sa.Column("lane", sa.Text(), nullable=True),
        sa.Column("processing_status", sa.Text(), nullable=False),
        sa.Column("processing_run", sa.Integer(), nullable=False),
        sa.Column("processing_nodes", types.json_type(), nullable=False, server_default="{}"),
        sa.Column("processing_vision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_baseline", sa.Text(), nullable=True),
        sa.Column("processing_decided", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", types.UtcDateTime(), nullable=True),
        sa.Column("new_at", types.UtcDateTime(), nullable=True),
        sa.Column("created_at", types.UtcDateTime(), nullable=False),
        sa.Column("updated_at", types.UtcDateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *person,
        sa.ForeignKeyConstraint(
            ["space_id"], ["spaces.id"], name=op.f("fk_documents_space_id_spaces")
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name=op.f("fk_documents_contact_id_contacts")
        ),
        sa.ForeignKeyConstraint(
            ["document_type_id"],
            ["document_types.id"],
            name=op.f("fk_documents_document_type_id_document_types"),
        ),
        sa.ForeignKeyConstraint(["topic_id"], ["tags.id"], name=op.f("fk_documents_topic_id_tags")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_space_id"), "documents", ["space_id"])
    if uploaded:
        op.create_index(op.f("ix_documents_uploaded_by"), "documents", ["uploaded_by"])
        op.create_index(op.f("ix_documents_sha256"), "documents", ["sha256"], unique=True)
    else:
        op.create_index(
            op.f("ix_documents_owner_id_sha256"), "documents", ["owner_id", "sha256"], unique=True
        )
    op.create_index(op.f("ix_documents_lane"), "documents", ["lane"])
    op.create_index(op.f("ix_documents_contact_id"), "documents", ["contact_id"])
    op.create_index(op.f("ix_documents_document_type_id"), "documents", ["document_type_id"])
    op.create_index(op.f("ix_documents_topic_id"), "documents", ["topic_id"])
    op.create_index(op.f("ix_documents_confirmed_at"), "documents", ["confirmed_at"])
    op.create_index(op.f("ix_documents_document_date_id"), "documents", ["document_date", "id"])
    op.create_index(op.f("ix_documents_title_key_id"), "documents", ["title_key", "id"])
    op.create_index(op.f("ix_documents_created_at_id"), "documents", ["created_at", "id"])


def _create_rules(*, space: bool) -> None:
    if space:
        holder = [
            sa.Column("space_id", sa.Uuid(), nullable=True),
            sa.ForeignKeyConstraint(
                ["space_id"],
                ["spaces.id"],
                name=op.f("fk_rules_space_id_spaces"),
                ondelete="CASCADE",
            ),
        ]
    else:
        holder = [
            sa.Column("owner_id", sa.Uuid(), nullable=True),
            sa.ForeignKeyConstraint(
                ["owner_id"], ["users.id"], name=op.f("fk_rules_owner_id_users")
            ),
        ]
    op.create_table(
        "rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("deleted_at", types.UtcDateTime(), nullable=True),
        sa.Column("created_at", types.UtcDateTime(), nullable=False),
        sa.Column("updated_at", types.UtcDateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *holder,
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rules")),
    )
    column = "space_id" if space else "owner_id"
    op.create_index(op.f(f"ix_rules_{column}"), "rules", [column])


# --- stored names -----------------------------------------------------------------------------


def _rename_stored(old: str, new: str) -> None:
    """The variable in the templates of rules (titles, values of text fields, reasons of
    reviews) and of title patterns."""
    connection = op.get_bind()
    fields = sa.table("field_definitions", sa.column("id", sa.Uuid()), sa.column("data_type"))
    texts = {
        str(row.id)
        for row in connection.execute(sa.select(fields).where(fields.c.data_type == "text"))
    }
    versions = sa.table(
        "rule_versions",
        sa.column("rule_id", sa.Uuid()),
        sa.column("number", sa.Integer()),
        sa.column("actions", types.json_type()),
    )
    for row in connection.execute(sa.select(versions)).mappings().all():
        actions = [_action(action, texts, old, new) for action in row["actions"]]
        if actions != row["actions"]:
            connection.execute(
                versions.update()
                .where(versions.c.rule_id == row["rule_id"], versions.c.number == row["number"])
                .values(actions=actions)
            )
    types_ = sa.table(
        "document_types", sa.column("id", sa.Uuid()), sa.column("title_pattern", sa.Text())
    )
    query = sa.select(types_).where(types_.c.title_pattern.is_not(None))
    for kind in connection.execute(query).all():
        pattern = _template(kind.title_pattern, old, new)
        if pattern != kind.title_pattern:
            connection.execute(
                types_.update().where(types_.c.id == kind.id).values(title_pattern=pattern)
            )


def _action(action: dict[str, Any], texts: set[str], old: str, new: str) -> dict[str, Any]:
    match action.get("type"):
        case "set_title":
            return {**action, "template": _template(action["template"], old, new)}
        case "set_field" if action.get("field_id") in texts and isinstance(action["value"], str):
            return {**action, "value": _template(action["value"], old, new)}
        case "force_review":
            return {**action, "reason": _template(action["reason"], old, new)}
    return action


def _template(template: str, old: str, new: str) -> str:
    """`template` with the global variable `old` named `new`, by the places Liquid's analysis
    gives; text, strings and raw blocks stay. RuntimeError if `new` means something else in it
    already."""
    try:
        places = sorted(variable.span.index for variable in _globals(template).get(old, []))
    except LiquidError:
        return template  # never saved like this (templates are checked); leave it as it is
    if not places:
        return template
    pieces, start, expected = [], 0, []
    for number, place in enumerate(places):
        if template.startswith(old, place):
            at = place
        elif template.startswith((f"['{old}']", f'["{old}"]'), place):
            at = place + 2
        else:
            raise RuntimeError(f"revision 0033 cannot read '{old}' in the template {template!r}")
        pieces += [template[start:at], new]
        start = at + len(old)
        expected.append(place + number * (len(new) - len(old)))
    renamed = "".join([*pieces, template[start:]])
    found = sorted(variable.span.index for variable in _globals(renamed).get(new, []))
    if found != expected or _globals(renamed).get(old):
        raise RuntimeError(
            f"the template {template!r} uses '{new}' already; rename it there before upgrading"
        )
    return renamed


def _globals(template: str) -> dict[str, Any]:
    return dict(parse(template).analyze().globals)


def _rename_scopes(old: str, new: str) -> None:
    """The scope of the rules' reports in the log entries of rule runs."""
    connection = op.get_bind()
    log = sa.table(
        "processing_log",
        sa.column("seq", sa.Integer()),
        sa.column("output", types.json_type()),
    )
    mentions = sa.cast(log.c.output, sa.Text).like(f'%"scope"%"{old}"%')
    for row in connection.execute(sa.select(log).where(mentions)).mappings().all():
        output = _scoped(row["output"], old, new)
        if output != row["output"]:
            connection.execute(log.update().where(log.c.seq == row["seq"]).values(output=output))


def _scoped(value: Any, old: str, new: str) -> Any:
    if isinstance(value, dict):
        if "rule_id" in value and value.get("scope") == old:
            value = {**value, "scope": new}
        return {key: _scoped(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_scoped(item, old, new) for item in value]
    return value
