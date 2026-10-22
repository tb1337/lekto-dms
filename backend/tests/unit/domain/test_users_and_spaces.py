from datetime import UTC, datetime

import pytest

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.ids import UserId, new_id
from lekto.core.domain.spaces import PERSONAL_SPACE_NAME, Space, SpaceRole
from lekto.core.domain.users import Role, User

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def test_user_has_a_role() -> None:
    admin = User.create(username=" alice ", role=Role.ADMIN, now=NOW)
    user = User.create(username="bob", role=Role.USER, now=NOW)
    assert admin.username == "alice"
    assert admin.is_admin
    assert not user.is_admin


def test_user_needs_a_name_and_utc_time() -> None:
    with pytest.raises(ValidationError):
        User.create(username=" ", role=Role.USER, now=NOW)
    with pytest.raises(ValidationError):
        User.create(username="bob", role=Role.USER, now=datetime(2026, 1, 1))


def test_a_personal_space_is_its_users_and_may_be_shared() -> None:
    user, other = UserId(new_id()), UserId(new_id())
    space = Space.create_personal(user=user, now=NOW)
    assert space.is_personal and space.personal_of == user
    assert (space.name, space.members) == (PERSONAL_SPACE_NAME, {user: SpaceRole.EDIT})
    space.set_member(other, SpaceRole.READ)
    assert space.members == {user: SpaceRole.EDIT, other: SpaceRole.READ}
    with pytest.raises(ValidationError, match="always edits"):
        space.set_member(user, SpaceRole.READ)
    with pytest.raises(ValidationError, match="always edits"):
        space.remove_member(user)
    with pytest.raises(ValidationError, match="keeps its name"):
        space.rename("Mine")


def test_members_are_added_changed_and_removed() -> None:
    editor, other = UserId(new_id()), UserId(new_id())
    space = Space.create(name="Household", members={editor: SpaceRole.EDIT}, now=NOW)
    assert not space.is_personal and space.personal_of is None
    space.set_member(other, SpaceRole.READ)
    space.set_member(other, SpaceRole.EDIT)
    assert space.members == {editor: SpaceRole.EDIT, other: SpaceRole.EDIT}
    assert space.editors == {editor, other}
    assert space.role_of(other) is SpaceRole.EDIT
    space.remove_member(other)
    space.remove_member(UserId(new_id()))  # no member: nothing to do
    assert space.members == {editor: SpaceRole.EDIT}
    assert space.role_of(other) is None


def test_a_shared_space_keeps_an_editor() -> None:
    editor, reader = UserId(new_id()), UserId(new_id())
    with pytest.raises(ValidationError, match="one editor"):
        Space.create(name="Household", members={reader: SpaceRole.READ}, now=NOW)
    space = Space.create(
        name="Household", members={editor: SpaceRole.EDIT, reader: SpaceRole.READ}, now=NOW
    )
    with pytest.raises(ValidationError, match="one editor"):
        space.remove_member(editor)
    with pytest.raises(ValidationError, match="one editor"):
        space.set_member(editor, SpaceRole.READ)
    assert space.members == {editor: SpaceRole.EDIT, reader: SpaceRole.READ}


def test_space_invariants_hold_on_construction() -> None:
    user, other = UserId(new_id()), UserId(new_id())
    with pytest.raises(ValidationError):
        Space(
            id=Space.create_personal(user=user, now=NOW).id,
            name="Personal",
            personal_of=user,
            members={other: SpaceRole.EDIT},
            created_at=NOW,
        )


def test_moving_widens_when_the_target_has_someone_new() -> None:
    a, b, c = UserId(new_id()), UserId(new_id()), UserId(new_id())
    home = Space.create_personal(user=a, now=NOW)
    household = Space.create(name="H", members={a: SpaceRole.EDIT, b: SpaceRole.READ}, now=NOW)
    assert home.widens(household)
    assert not household.widens(home)
    assert not household.widens(
        Space.create(name="I", members={a: SpaceRole.READ, b: SpaceRole.EDIT}, now=NOW)
    )
    assert household.widens(Space.create(name="J", members={c: SpaceRole.EDIT}, now=NOW))


def test_space_rename_requires_a_name() -> None:
    space = Space.create(name="Household", members={UserId(new_id()): SpaceRole.EDIT}, now=NOW)
    space.rename(" Taxes ")
    assert space.name == "Taxes"
    with pytest.raises(ValidationError):
        space.rename("")


def test_space_role_edit() -> None:
    assert SpaceRole.EDIT.can_edit
    assert not SpaceRole.READ.can_edit
