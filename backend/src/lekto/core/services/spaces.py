from collections.abc import Iterable, Mapping

from lekto.core.domain.documents import UNSET, Unset
from lekto.core.domain.errors import ConflictError, NotFoundError, PermissionDeniedError
from lekto.core.domain.ids import SpaceId, UserId
from lekto.core.domain.permissions import can_choose_members, can_manage_space
from lekto.core.domain.reasons import Action, ReasonCode, because
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import User
from lekto.core.ports.clock import Clock
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_actor, load_lister, visible_space
from lekto.core.services.rules.references import disable_rules, refers_to


class SpaceService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def list_spaces(self, actor: UserId, all_users: bool = False) -> list[Space]:
        """The spaces the user is a member of, admins too; with `all_users` (admins only)
        every space. An admin's rights reach every space either way; the list follows the
        reach the admin chose, as the lists of documents, inboxes and rules do (Tobi,
        22.10.2026)."""
        async with self._uow() as uow:
            await load_lister(uow, actor, all_users, Action.LIST_ALL_SPACES)
            if all_users:
                return await uow.spaces.list_all()
            return await uow.spaces.list_accessible(actor)

    async def members(self, actor: UserId, spaces: Iterable[Space]) -> dict[UserId, User]:
        """The members of `spaces`, which the service gave the caller, by id: their names,
        and whether they are active, which the users list does not show others than admins
        (a deactivated member keeps their place until an editor removes them)."""
        wanted = {member for space in spaces for member in space.members}
        async with self._uow() as uow:
            await load_actor(uow, actor)
            users = await uow.users.list_all()
        return {user.id: user for user in users if user.id in wanted}

    async def get(self, actor: UserId, id: SpaceId) -> Space:
        """A space the user is a member of, any space for admins; NotFoundError otherwise."""
        async with self._uow() as uow:
            return await visible_space(uow, await load_actor(uow, actor), id)

    async def delete(self, actor: UserId, id: SpaceId) -> None:
        """Editors and admins; never a personal space, and only while it holds no documents.
        Its rules go with it; other rules that file into it are disabled."""
        async with self._uow() as uow:
            space = await _managed_space(uow, await load_actor(uow, actor), id)
            if space.is_personal:
                raise ConflictError(because(ReasonCode.PERSONAL_SPACE_UNDELETABLE))
            if await uow.documents.exists(space=id):
                raise ConflictError(because(ReasonCode.SPACE_NOT_EMPTY, space=space.name))
            await uow.spaces.remove(id)
            await disable_rules(
                uow,
                self._clock.now(),
                because(ReasonCode.RULE_DISABLED_DELETED, kind="space", name=space.name),
                refers_to(lambda refs: refs.spaces, id),
            )
            await uow.commit()

    async def create(
        self,
        actor: UserId,
        name: str,
        *,
        members: Mapping[UserId, SpaceRole] | None = None,
        description: str | None = None,
    ) -> Space:
        """A space the caller edits, shared with `members`. An admin may give the members
        alone (without being one), as long as one of them edits; everyone else is always an
        editor of what they create. Members are active users."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            chosen = dict(members or {})
            if not user.is_active_admin or not chosen:
                chosen[user.id] = SpaceRole.EDIT
            for member in chosen:
                await _active_user(uow, member)
            space = Space.create(
                name=name, members=chosen, now=self._clock.now(), description=description
            )
            await _check_name_free(uow, space)
            await uow.spaces.add(space)
            await uow.commit()
        return space

    async def rename(self, actor: UserId, id: SpaceId, name: str) -> Space:
        return await self.change(actor, id, name=name)

    async def change(
        self,
        actor: UserId,
        id: SpaceId,
        *,
        name: str | None = None,
        description: str | Unset | None = UNSET,
    ) -> Space:
        """Rename (not a personal space) or describe a space: editors and admins; a personal
        space's description its user (and admins), as its members. None (name) or UNSET
        (description) leaves it; None or empty removes the description."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            space = await _managed_space(uow, user, id)
            if (
                space.is_personal
                and not isinstance(description, Unset)
                and not can_choose_members(user, space)
            ):
                raise PermissionDeniedError(because(ReasonCode.PERSONAL_SPACE_DESCRIBE, id=str(id)))
            if name is not None:
                space.rename(name)
                await _check_name_free(uow, space)
            if not isinstance(description, Unset):
                space.describe(description)
            await uow.spaces.update(space)
            await uow.commit()
        return space

    async def set_member(
        self, actor: UserId, id: SpaceId, member: UserId, role: SpaceRole
    ) -> Space:
        """Add `member` or change their role: editors and admins; in a personal space its user
        and admins. The member is an active user."""
        async with self._uow() as uow:
            space = await _members_space(uow, await load_actor(uow, actor), id)
            await _active_user(uow, member)
            space.set_member(member, role)
            await uow.spaces.update(space)
            await uow.commit()
        return space

    async def remove_member(self, actor: UserId, id: SpaceId, member: UserId) -> Space:
        """As `set_member`; and every member leaves a space themselves, a reader too. A space
        keeps one editor; the user of a personal space stays."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            if member == user.id and (found := await uow.spaces.find(id)) is not None:
                space = found if found.role_of(user.id) is not None else None
            else:
                space = None
            if space is None:
                space = await _members_space(uow, user, id)
            space.remove_member(member)
            await uow.spaces.update(space)
            await uow.commit()
        return space


async def _managed_space(uow: UnitOfWork, user: User, id: SpaceId) -> Space:
    space = await visible_space(uow, user, id)
    if not can_manage_space(user, space):
        raise PermissionDeniedError(because(ReasonCode.SPACE_MANAGE, id=str(id)))
    return space


async def _members_space(uow: UnitOfWork, user: User, id: SpaceId) -> Space:
    space = await visible_space(uow, user, id)
    if not can_choose_members(user, space):
        code = ReasonCode.SPACE_MEMBERS_PERSONAL if space.is_personal else ReasonCode.SPACE_MEMBERS
        raise PermissionDeniedError(because(code, id=str(id)))
    return space


async def _active_user(uow: UnitOfWork, id: UserId) -> User:
    user = await uow.users.find(id)
    if user is None or not user.active:
        # As in the user list: deactivated users are not there for others.
        raise NotFoundError("user", id)
    return user


async def _check_name_free(uow: UnitOfWork, space: Space) -> None:
    """Names of the spaces that are nobody's personal one are unique. The repository holds
    that rule too (`core.ports.repository`); this look-up gives the message."""
    if space.is_personal:
        return
    other = await uow.spaces.find_by_name(space.name)
    if other is not None and other.id != space.id:
        raise ConflictError(because(ReasonCode.SPACE_NAME_TAKEN, space=space.name))
