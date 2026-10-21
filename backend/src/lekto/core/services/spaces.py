from collections.abc import Mapping

from lekto.core.domain.errors import ConflictError, NotFoundError, PermissionDeniedError
from lekto.core.domain.ids import SpaceId, UserId
from lekto.core.domain.permissions import can_choose_members, can_manage_space
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import User
from lekto.core.ports.clock import Clock
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import load_actor, visible_space
from lekto.core.services.rules.references import disable_rules, refers_to


class SpaceService:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def list_spaces(self, actor: UserId) -> list[Space]:
        """The spaces the user is a member of; every space for admins."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            if user.is_active_admin:
                return await uow.spaces.list_all()
            return await uow.spaces.list_accessible(actor)

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
                raise ConflictError("a personal space cannot be deleted")
            if await uow.documents.exists(space=id):
                raise ConflictError(f"space '{space.name}' is not empty")
            await uow.spaces.remove(id)
            await disable_rules(
                uow,
                self._clock.now(),
                f"space '{space.name}' was deleted",
                refers_to(lambda refs: refs.spaces, id),
            )
            await uow.commit()

    async def create(
        self, actor: UserId, name: str, *, members: Mapping[UserId, SpaceRole] | None = None
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
            space = Space.create(name=name, members=chosen, now=self._clock.now())
            await _check_name_free(uow, space)
            await uow.spaces.add(space)
            await uow.commit()
        return space

    async def rename(self, actor: UserId, id: SpaceId, name: str) -> Space:
        async with self._uow() as uow:
            space = await _managed_space(uow, await load_actor(uow, actor), id)
            space.rename(name)
            await _check_name_free(uow, space)
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
        """As `set_member`. A space keeps one editor; the user of a personal space stays."""
        async with self._uow() as uow:
            space = await _members_space(uow, await load_actor(uow, actor), id)
            space.remove_member(member)
            await uow.spaces.update(space)
            await uow.commit()
        return space


async def _managed_space(uow: UnitOfWork, user: User, id: SpaceId) -> Space:
    space = await visible_space(uow, user, id)
    if not can_manage_space(user, space):
        raise PermissionDeniedError(f"only editors and admins manage space {id}")
    return space


async def _members_space(uow: UnitOfWork, user: User, id: SpaceId) -> Space:
    space = await visible_space(uow, user, id)
    if not can_choose_members(user, space):
        who = "its user" if space.is_personal else "editors"
        raise PermissionDeniedError(f"only {who} and admins choose the members of space {id}")
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
        raise ConflictError(f"space '{space.name}' already exists")
