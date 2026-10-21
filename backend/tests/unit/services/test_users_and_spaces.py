import pytest

from lekto.core.domain.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from lekto.core.domain.ids import SpaceId, UserId, new_id
from lekto.core.domain.spaces import PERSONAL_SPACE_NAME, SpaceRole
from lekto.core.domain.users import Role
from tests.builders import incoming
from tests.unit.services.support import World


async def test_admin_creates_user_with_personal_space(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    user = await world.users.create_user(admin.id, "dana", Role.USER)
    async with world.uow() as uow:
        assert await uow.users.get(user.id) == user
        personal = await uow.spaces.get_personal(user.id)
    assert personal.personal_of == user.id
    assert personal.name == PERSONAL_SPACE_NAME
    assert personal.members == {user.id: SpaceRole.EDIT}


async def test_only_admins_create_users(world: World) -> None:
    user = await world.user()
    with pytest.raises(PermissionDeniedError):
        await world.users.create_user(user.id, "eve", Role.USER)


async def test_usernames_are_unique(world: World) -> None:
    admin = await world.user("root", role=Role.ADMIN)
    with pytest.raises(ConflictError):
        await world.users.create_user(admin.id, "ROOT", Role.USER)


async def test_unknown_or_deactivated_actor_is_not_authenticated(world: World) -> None:
    with pytest.raises(AuthenticationError):
        await world.users.create_user(UserId(new_id()), "x", Role.USER)
    admin = await world.user(role=Role.ADMIN)
    async with world.uow() as uow:
        stored = await uow.users.get(admin.id)
        stored.active = False
        await uow.users.update(stored)
        await uow.commit()
    with pytest.raises(AuthenticationError):
        await world.users.create_user(admin.id, "x", Role.USER)


async def test_a_creator_edits_renames_and_shares_spaces(world: World) -> None:
    creator, other = await world.user(), await world.user()
    space = await world.spaces.create(creator.id, "Household")
    assert space.members == {creator.id: SpaceRole.EDIT}
    renamed = await world.spaces.rename(creator.id, space.id, "Home")
    assert renamed.name == "Home"
    shared = await world.spaces.set_member(creator.id, space.id, other.id, SpaceRole.READ)
    assert shared.members == {creator.id: SpaceRole.EDIT, other.id: SpaceRole.READ}
    assert {d.id for d in await world.spaces.list_spaces(other.id)} == {
        space.id,
        (await world.personal_space(other)).id,
    }
    unshared = await world.spaces.remove_member(creator.id, space.id, other.id)
    assert unshared.members == {creator.id: SpaceRole.EDIT}


async def test_a_space_is_created_with_members(world: World) -> None:
    admin = await world.user(role=Role.ADMIN)
    creator, reader, editor = await world.user(), await world.user(), await world.user()
    space = await world.spaces.create(creator.id, "Household", members={reader.id: SpaceRole.READ})
    assert space.members == {creator.id: SpaceRole.EDIT, reader.id: SpaceRole.READ}
    # An admin gives the members alone (the migration client creates spaces so).
    theirs = await world.spaces.create(
        admin.id, "Theirs", members={editor.id: SpaceRole.EDIT, reader.id: SpaceRole.READ}
    )
    assert theirs.members == {editor.id: SpaceRole.EDIT, reader.id: SpaceRole.READ}
    with pytest.raises(ValidationError, match="one editor"):
        await world.spaces.create(admin.id, "Nobody edits", members={reader.id: SpaceRole.READ})
    mine = await world.spaces.create(admin.id, "Mine")
    assert mine.members == {admin.id: SpaceRole.EDIT}
    with pytest.raises(NotFoundError):
        await world.spaces.create(creator.id, "Ghost", members={UserId(new_id()): SpaceRole.READ})


async def test_names_of_shared_spaces_are_unique(world: World) -> None:
    owner, other = await world.user(), await world.user()
    first = await world.spaces.create(owner.id, "Taxes")
    with pytest.raises(ConflictError):
        await world.spaces.create(other.id, "taxes")
    second = await world.spaces.create(owner.id, "Insurance")
    with pytest.raises(ConflictError):
        await world.spaces.rename(owner.id, second.id, "TAXES")
    assert (await world.spaces.rename(owner.id, first.id, "TAXES")).name == "TAXES"
    # The personal spaces share their stored name and are apart.
    assert (await world.spaces.create(owner.id, "Personal")).name == "Personal"


async def test_editors_manage_a_space_readers_do_not(world: World) -> None:
    creator, editor, reader = await world.user(), await world.user(), await world.user()
    stranger = await world.user()
    space = await world.spaces.create(creator.id, "Household")
    await world.spaces.set_member(creator.id, space.id, editor.id, SpaceRole.EDIT)
    await world.spaces.set_member(creator.id, space.id, reader.id, SpaceRole.READ)
    assert (await world.spaces.rename(editor.id, space.id, "Ours")).name == "Ours"
    await world.spaces.set_member(editor.id, space.id, stranger.id, SpaceRole.READ)
    await world.spaces.remove_member(editor.id, space.id, stranger.id)
    with pytest.raises(PermissionDeniedError):
        await world.spaces.rename(reader.id, space.id, "Mine")
    with pytest.raises(PermissionDeniedError):
        await world.spaces.set_member(reader.id, space.id, stranger.id, SpaceRole.READ)
    with pytest.raises(NotFoundError):
        await world.spaces.rename(stranger.id, space.id, "Mine")
    with pytest.raises(NotFoundError):
        await world.spaces.rename(creator.id, SpaceId(new_id()), "Mine")
    # A space keeps an editor.
    await world.spaces.remove_member(editor.id, space.id, creator.id)
    with pytest.raises(ValidationError, match="one editor"):
        await world.spaces.remove_member(editor.id, space.id, editor.id)


async def test_a_personal_space_is_shared_by_its_user(world: World) -> None:
    user, other, third = await world.user(), await world.user(), await world.user()
    personal = await world.personal_space(user)
    shared = await world.spaces.set_member(user.id, personal.id, other.id, SpaceRole.EDIT)
    assert shared.members == {user.id: SpaceRole.EDIT, other.id: SpaceRole.EDIT}
    # Who edits it does not choose its members, nor rename or delete it.
    with pytest.raises(PermissionDeniedError, match="its user"):
        await world.spaces.set_member(other.id, personal.id, third.id, SpaceRole.READ)
    with pytest.raises(ValidationError, match="keeps its name"):
        await world.spaces.rename(user.id, personal.id, "Mine")
    with pytest.raises(ConflictError):
        await world.spaces.delete(user.id, personal.id)
    with pytest.raises(ValidationError, match="always edits"):
        await world.spaces.remove_member(user.id, personal.id, user.id)
    await world.spaces.remove_member(user.id, personal.id, other.id)


async def test_spaces_are_read_and_deleted(world: World) -> None:
    owner, reader, stranger = await world.user(), await world.user(), await world.user()
    space = await world.spaces.create(owner.id, "Archive")
    await world.spaces.set_member(owner.id, space.id, reader.id, SpaceRole.READ)
    assert (await world.spaces.get(reader.id, space.id)).id == space.id
    with pytest.raises(NotFoundError):
        await world.spaces.get(stranger.id, space.id)
    with pytest.raises(PermissionDeniedError):
        await world.spaces.delete(reader.id, space.id)
    with pytest.raises(NotFoundError):
        await world.spaces.delete(stranger.id, space.id)
    with pytest.raises(ConflictError):
        await world.spaces.delete(owner.id, (await world.personal_space(owner)).id)
    await world.pipeline().receive(
        owner.id, incoming(b"%PDF-1.7 x"), filename="x.pdf", space=space.id
    )
    with pytest.raises(ConflictError):
        await world.spaces.delete(owner.id, space.id)
    empty = await world.spaces.create(owner.id, "Empty")
    await world.spaces.delete(owner.id, empty.id)
    with pytest.raises(NotFoundError):
        await world.spaces.get(owner.id, empty.id)


async def test_deactivated_users_become_no_members(world: World) -> None:
    """M4-10: a membership would take effect unnoticed when the user is activated again."""
    admin, owner, gone = await world.user(role=Role.ADMIN), await world.user(), await world.user()
    space = await world.spaces.create(owner.id, "Household")
    await world.users.update(admin.id, gone.id, active=False)
    with pytest.raises(NotFoundError):
        await world.spaces.set_member(owner.id, space.id, gone.id, SpaceRole.READ)
    with pytest.raises(NotFoundError):
        await world.spaces.set_member(owner.id, space.id, UserId(new_id()), SpaceRole.READ)
