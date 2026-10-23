"""Accounts: created and managed by admins; the first admin comes from configuration.

The last active admin can be neither demoted, deactivated nor deleted. Two admins demoting
each other at the same time must not both succeed: a change that takes away admin rights also
writes the other active admins (version check), so one of two such transactions fails.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from lekto.core.domain.identity import Credential, ExternalIdentity, check_new_password
from lekto.core.domain.ids import DocumentId, SpaceId, UserId
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.rules import Rule
from lekto.core.domain.sorting import sort_key
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import (
    BlockingSpace,
    Role,
    Settle,
    Settlement,
    User,
    UserDeletionBlockedError,
    display_name_of,
)
from lekto.core.ports.clock import Clock
from lekto.core.ports.identity import PasswordHasher
from lekto.core.ports.repository import DocumentFilter, DocumentPosition
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_actor, require_admin
from lekto.core.services._moves import move_by_person
from lekto.core.services.profiles import USER_NAMES_LOCK, check_display_name, check_username
from lekto.core.services.rules.changes import ChangeRules
from lekto.core.services.rules.references import disable_rules, refers_to
from lekto.core.services.rules.running import Prepared

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Account:
    """A user with the state of their sign-in methods, for admins."""

    user: User
    has_password: bool
    totp_enabled: bool
    external_identities: list[ExternalIdentity]


class UserService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        hasher: PasswordHasher | None = None,
        *,
        rules: ChangeRules | None = None,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._hasher = hasher
        self._rules = rules  # logs the moves of deleting a user, as `DocumentService.move`

    # --- reading --------------------------------------------------------------------------------

    async def list_users(self, actor: UserId) -> list[User]:
        """Admins see all users; others see the active ones (to share spaces with them)."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            users = await uow.users.list_all()
        visible = users if user.is_active_admin else [u for u in users if u.active]
        return sorted(visible, key=lambda u: sort_key(u.label))

    async def get(self, actor: UserId, id: UserId) -> User:
        """Like `list_users`: a deactivated user is not found for others than admins."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            found = await uow.users.find(id)
        if found is None or not (found.active or user.is_active_admin):
            raise NotFoundError("user", id)
        return found

    async def personal_spaces(self, actor: UserId) -> dict[UserId, SpaceId]:
        """The personal space of every user, by user: where a document is handed over to them
        (`DocumentService.move`). Every signed-in user may know them."""
        async with self._uow() as uow:
            await load_actor(uow, actor)
            return await uow.spaces.personal_ids()

    async def own_account(self, actor: UserId) -> Account:
        """The caller's own account."""
        async with self._uow() as uow:
            return await _account(uow, await load_actor(uow, actor))

    async def account(self, actor: UserId, id: UserId) -> Account:
        """Admins only."""
        async with self._uow() as uow:
            await require_admin(uow, actor, "manage users")
            return await _account(uow, await uow.users.get(id))

    # --- changes by admins ----------------------------------------------------------------------

    async def create_user(
        self,
        actor: UserId,
        username: str,
        role: Role,
        password: str | None = None,
        *,
        session: bool = True,
        display_name: str | None = None,
    ) -> User:
        """Admins only. Creates the user together with their personal space and, if
        given, a password (which must meet the policy) and a display name (ConflictError if it
        is another user's name).

        `session`: whether the caller is signed in with a session. With an API token (as a
        migration uses) only a user with the role `user` and no password can be created: a
        password or the role `admin` would turn a leaked token into a sign-in with more
        rights than the token was meant to give (see `update`)."""
        if not session and (password is not None or role is not Role.USER):
            raise PermissionDeniedError(
                "this needs a signed-in session: an API token can only create users with the "
                "role 'user' and no password"
            )
        password_hash = await self._hash(username, password)
        now = self._clock.now()
        async with self._uow() as uow:
            await require_admin(uow, actor, "manage users")
            user = await add_user(uow, username, role, now, display_name=display_name)
            if password_hash is not None:
                await uow.credentials.add(
                    Credential(
                        user_id=user.id, password_hash=password_hash, password_changed_at=now
                    )
                )
            await uow.commit()
        log.info("user created", extra={"user_id": str(user.id), "role": role.value})
        return user

    async def update(
        self,
        actor: UserId,
        id: UserId,
        *,
        role: Role | None = None,
        active: bool | None = None,
        session: bool = True,
    ) -> User:
        """Admins only; role and state in one transaction. Rights follow the role at once,
        since every request reads the user anew; sessions and tokens stay. Deactivating ends
        the user's sessions; their API tokens are refused while the account is inactive.

        `session`: whether the caller is signed in with a session. An API token (a leaked one
        above all) must not make anyone an admin, since that account then signs in with a
        session and has everything the token was not meant to give; nor may it deactivate the
        admins. A token only deactivates and reactivates users, as a migration does."""
        async with self._uow() as uow:
            await require_admin(uow, actor, "manage users")
            user = await uow.users.get(id)
            if not session and (
                (role is not None and role is not user.role)
                or (user.is_admin and active is not None and active is not user.active)
            ):
                raise PermissionDeniedError(
                    "this needs a signed-in session: an API token cannot change a role or the "
                    "state of an admin"
                )
            new_role = user.role if role is None else role
            new_active = user.active if active is None else active
            if (new_role, new_active) != (user.role, user.active):
                if user.is_active_admin and not (new_active and new_role is Role.ADMIN):
                    await _keep_an_admin(uow, user)
                user.role, user.active = new_role, new_active
                await uow.users.update(user)
                if not new_active:
                    await uow.sessions.remove_for_user(id)
                await uow.commit()
                log.info(
                    "account changed",
                    extra={"user_id": str(id), "role": user.role.value, "active": user.active},
                )
        return user

    async def reset_password(
        self, actor: UserId, id: UserId, password: str, *, revoke_tokens: bool = False
    ) -> None:
        """Admins only, not for their own account (that is `AuthService.change_password`, which
        needs the current password). All sessions of the user end; API tokens stay unless
        `revoke_tokens`."""
        _not_own(actor, id, "reset their own password here")
        async with self._uow() as uow:
            await require_admin(uow, actor, "manage users")
            user = await uow.users.get(id)
        password_hash = await self._hash(user.username, password)
        assert password_hash is not None
        now = self._clock.now()
        async with self._uow() as uow:
            await require_admin(uow, actor, "manage users")
            credential = await uow.credentials.find(id)
            if credential is None:
                await uow.credentials.add(
                    Credential(user_id=id, password_hash=password_hash, password_changed_at=now)
                )
            else:
                credential.password_hash = password_hash
                credential.password_changed_at = now
                await uow.credentials.update(credential)
            await uow.sessions.remove_for_user(id)
            if revoke_tokens:
                await uow.api_tokens.remove_for_user(id)
            await uow.commit()
        log.info("password reset", extra={"user_id": str(id), "tokens_revoked": revoke_tokens})

    async def disable_totp(self, actor: UserId, id: UserId) -> None:
        """Admins only, for a user who lost their authenticator and recovery codes; not for
        their own account (that is `AuthService.disable_totp`, which needs a code)."""
        _not_own(actor, id, "turn off their own TOTP here")
        async with self._uow() as uow:
            await require_admin(uow, actor, "manage users")
            await uow.users.get(id)
            credential = await uow.credentials.find(id)
            if credential is not None and credential.totp is not None:
                credential.totp = None
                credential.recovery_codes = set()
                await uow.credentials.update(credential)
                await uow.commit()
                log.info("TOTP turned off by an admin", extra={"user_id": str(id)})

    async def unlink_external_identities(self, actor: UserId, id: UserId) -> int:
        """Admins only: remove the user's links to identity providers."""
        async with self._uow() as uow:
            await require_admin(uow, actor, "manage users")
            await uow.users.get(id)
            removed = await uow.external_identities.remove_for_user(id)
            await uow.commit()
        return removed

    async def removal(self, actor: UserId, id: UserId) -> list[BlockingSpace]:
        """Admins: the spaces that stop deleting the user until the deletion settles them
        (`delete_user`); empty if nothing does."""
        async with self._uow() as uow:
            await require_admin(uow, actor, "manage users")
            await uow.users.get(id)
            return [blocking for blocking, _ in await _blocking(uow, id)]

    async def delete_user(
        self,
        actor: UserId,
        id: UserId,
        settle: Mapping[SpaceId, Settlement] | None = None,
    ) -> None:
        """Admins only. A space that would stop it needs a decision in `settle` (Tobi,
        22.10.2026; `removal` lists them, UserDeletionBlockedError names those left open): the
        user's personal space while it holds documents moves them into another space
        (`move_to`); a shared space the user alone edits goes with the user if it is empty
        (`remove`), moves its documents (`move_to`) and goes, or gets another editor
        (`editor`) and stays. Documents move as an admin moves them by hand. All at once:
        nothing happens if one fails.

        Removes the personal space with its rules, the user's memberships of other spaces,
        their webhooks, lenses and applications of rules, all their sign-in data and what they
        saw in the inbox; the documents they uploaded keep no uploader. Rules that file into a
        space that goes are disabled."""
        chosen = dict(settle or {})
        prepared = await self._arrivals(chosen)
        async with self._uow() as uow:
            admin = await require_admin(uow, actor, "manage users")
            user = await uow.users.get(id)
            if user.is_active_admin:
                await _keep_an_admin(uow, user)
            blocking = await _blocking(uow, id)
            spaces = {space.id: space for _, space in blocking}
            unknown = sorted(set(chosen) - set(spaces), key=str)
            if unknown:
                raise ValidationError(f"spaces: {unknown[0]} does not stop deleting the user")
            if open_ := [item for item, _ in blocking if item.id not in chosen]:
                raise UserDeletionBlockedError(tuple(open_))
            leaving = {
                space.id
                for space in await uow.spaces.list_accessible(id)
                if space.personal_of == id
            }
            leaving |= {key for key, item in chosen.items() if item.how is not Settle.EDITOR}
            now = self._clock.now()
            for item, space in blocking:
                settlement = chosen[item.id]
                if settlement.how not in item.choices:
                    raise ValidationError(
                        f"spaces: '{space.name}' cannot be settled by {settlement.how.value}"
                    )
                if settlement.move_to is not None:
                    target = await _move_target(uow, settlement.move_to, leaving)
                    for document in await _documents_in(uow, space.id):
                        await move_by_person(
                            uow,
                            document,
                            space,
                            target,
                            by=admin,
                            now=now,
                            rules=self._rules,
                            prepared=prepared.get(document.id),
                        )
                elif settlement.editor is not None:
                    editor = await uow.users.find(settlement.editor)
                    if editor is None or not editor.active or editor.id == id:
                        raise NotFoundError("user", settlement.editor)
                    space.set_member(editor.id, SpaceRole.EDIT)
                    await uow.spaces.update(space)
            for space in await uow.spaces.list_accessible(id):
                if space.id not in leaving:
                    space.remove_member(id)
                    await uow.spaces.update(space)
            for space_id in sorted(leaving, key=str):
                gone = await uow.spaces.get(space_id)
                await uow.spaces.remove(space_id)
                await disable_rules(
                    uow,
                    now,
                    f"the personal space of '{user.username}' was deleted"
                    if gone.personal_of == id
                    else f"space '{gone.name}' was deleted",
                    refers_to(lambda refs: refs.spaces, space_id),
                )
            await uow.rules.remove_applications_by(id)
            await uow.webhooks.remove_for_owner(id)
            await uow.lenses.remove_for_owner(id)
            await uow.sessions.remove_for_user(id)
            await uow.api_tokens.remove_for_user(id)
            await uow.external_identities.remove_for_user(id)
            await uow.credentials.remove(id)
            await uow.inbox.remove_for_user(id)
            await uow.users.remove(id)
            await uow.commit()
        log.info("user deleted", extra={"user_id": str(id)})

    async def _arrivals(self, chosen: Mapping[SpaceId, Settlement]) -> dict[DocumentId, Prepared]:
        """Outside a transaction: for each document a deletion moves, what the rules of the
        space it moves into need (`ChangeRules.arrival_rules`, as `DocumentService.move`)."""
        if self._rules is None:
            return {}
        arriving: list[tuple[Document, list[Rule]]] = []
        async with self._uow() as uow:
            for space, settlement in chosen.items():
                target = (
                    None
                    if settlement.move_to is None
                    else await uow.spaces.find(settlement.move_to)
                )
                if target is None:
                    continue  # the deletion refuses it
                for document in await _documents_in(uow, space):
                    arriving.append(
                        (document, await self._rules.arrival_rules(uow, document, target))
                    )
        return {
            document.id: await self._rules.prepare(rules, document) for document, rules in arriving
        }

    # --- first admin ----------------------------------------------------------------------------

    async def bootstrap_admin(self, username: str, password: str) -> User | None:
        """Create the first admin, if there is no active admin; otherwise do nothing and return
        None (an existing account is never changed, also not a deactivated admin: the operator
        names a new one to get back in). ConflictError if the name is taken (`add_user`)."""
        async with self._uow() as uow:
            if any(user.is_active_admin for user in await uow.users.list_all()):
                return None
        password_hash = await self._hash(username, password)
        assert password_hash is not None
        now = self._clock.now()
        async with self._uow() as uow:
            if any(user.is_active_admin for user in await uow.users.list_all()):
                return None
            user = await add_user(uow, username, Role.ADMIN, now)
            await uow.credentials.add(
                Credential(user_id=user.id, password_hash=password_hash, password_changed_at=now)
            )
            await uow.commit()
        log.info("first admin created", extra={"user_id": str(user.id)})
        return user

    async def _hash(self, username: str, password: str | None) -> str | None:
        if password is None:
            return None
        if self._hasher is None:
            raise RuntimeError("UserService needs a password hasher to set passwords")
        return await self._hasher.hash(check_new_password(password, username))


def _not_own(actor: UserId, id: UserId, what: str) -> None:
    if actor == id:
        raise PermissionDeniedError(f"admins cannot {what}")


async def add_user(
    uow: UnitOfWork, username: str, role: Role, now: datetime, *, display_name: str | None = None
) -> User:
    """Add a user with their personal space; ConflictError if the name is taken (looked up for
    the message; the repository's rule catches two requests at once, `core.ports.repository`),
    is another user's display name, or the display name is another user's name. Takes
    `USER_NAMES_LOCK`: the unit must not have written yet."""
    user = User.create(username=username, role=role, now=now)
    user.display_name = display_name_of(display_name)
    await uow.lock(USER_NAMES_LOCK)
    if await uow.users.find_by_username(user.username) is not None:
        raise ConflictError(because(ReasonCode.USERNAME_TAKEN, username=user.username))
    await check_username(uow, user.username)
    await check_display_name(uow, user.id, user.display_name)
    await uow.users.add(user)
    await uow.spaces.add(Space.create_personal(user=user.id, now=user.created_at))
    return user


async def _blocking(uow: UnitOfWork, id: UserId) -> list[tuple[BlockingSpace, Space]]:
    """The spaces that stop deleting the user (`UserService.delete_user`), by name."""
    found: list[tuple[BlockingSpace, Space]] = []
    for space in await uow.spaces.list_accessible(id):
        personal = space.personal_of == id
        if not personal and space.editors != {id}:
            continue
        documents = len(await _documents_in(uow, space.id))
        if personal and not documents:
            continue  # goes with the user
        if personal:
            choices: tuple[Settle, ...] = (Settle.MOVE_TO,)
        elif documents:
            choices = (Settle.MOVE_TO, Settle.EDITOR)
        else:
            choices = (Settle.REMOVE, Settle.EDITOR)
        found.append((BlockingSpace(space.id, space.name, personal, documents, choices), space))
    return sorted(found, key=lambda pair: (not pair[0].personal, sort_key(pair[0].name)))


async def _documents_in(uow: UnitOfWork, space: SpaceId) -> list[Document]:
    """Every document in the space, whoever may read it."""
    found: list[Document] = []
    within = DocumentFilter(spaces=frozenset({space}))
    while True:
        page = await uow.documents.query(
            within,
            after=DocumentPosition.after(found[-1].id if found else None),
            limit=_PAGE,
        )
        found.extend(page)
        if len(page) < _PAGE:
            return found


_PAGE = 500


async def _move_target(uow: UnitOfWork, id: SpaceId, leaving: set[SpaceId]) -> Space:
    """The space documents of a deleted user's space move into: one that stays, and no
    deactivated user's personal space (as a move by hand)."""
    target = await uow.spaces.find(id)
    if target is None or target.id in leaving:
        raise NotFoundError("space", id)
    if target.personal_of is not None:
        receiver = await uow.users.find(target.personal_of)
        if receiver is None or not receiver.active:
            raise NotFoundError("space", id)
    return target


async def _keep_an_admin(uow: UnitOfWork, leaving: User) -> None:
    """ConflictError unless another active admin remains. Writes the remaining ones, so a
    concurrent change that relies on them fails its version check."""
    others = [
        user
        for user in await uow.users.list_all()
        if user.is_active_admin and user.id != leaving.id
    ]
    if not others:
        raise ConflictError(because(ReasonCode.LAST_ADMIN))
    for other in others:
        await uow.users.update(other)


async def _account(uow: UnitOfWork, user: User) -> Account:
    credential = await uow.credentials.find(user.id)
    return Account(
        user=user,
        has_password=credential is not None and credential.password_hash is not None,
        totp_enabled=credential is not None and credential.totp_enabled,
        external_identities=await uow.external_identities.list_for(user.id),
    )
