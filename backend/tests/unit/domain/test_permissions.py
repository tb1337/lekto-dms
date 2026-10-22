import pytest

from lekto.core.domain.permissions import (
    Reach,
    can_choose_members,
    can_edit_document,
    can_file_into,
    can_hand_over,
    can_manage_space,
    can_move_document,
    can_read_document,
    document_access,
    in_reach,
    member_role,
    reach_access,
    space_role,
    within_reach,
)
from lekto.core.domain.pipeline import Lane, Node, NodeResult
from lekto.core.domain.spaces import Space, SpaceRole
from lekto.core.domain.users import User
from tests import builders
from tests.builders import FAILED, UNCERTAIN


@pytest.fixture
def editor() -> User:
    return builders.user("editor")


@pytest.fixture
def reader() -> User:
    return builders.user("reader")


@pytest.fixture
def other_editor() -> User:
    return builders.user("other_editor")


@pytest.fixture
def stranger() -> User:
    return builders.user("stranger")


@pytest.fixture
def shared(editor: User, reader: User, other_editor: User) -> Space:
    return builders.space(editor, "Household", readers=[reader], editors=[other_editor])


def test_space_role(
    editor: User, reader: User, other_editor: User, stranger: User, shared: Space
) -> None:
    assert space_role(editor, shared) is SpaceRole.EDIT
    assert space_role(other_editor, shared) is SpaceRole.EDIT
    assert space_role(reader, shared) is SpaceRole.READ
    assert space_role(stranger, shared) is None
    assert space_role(builders.admin(), shared) is SpaceRole.EDIT
    assert member_role(builders.admin(), shared) is None


def test_green_documents_are_read_by_readers_and_edited_by_editors(
    editor: User, reader: User, other_editor: User, stranger: User, shared: Space
) -> None:
    document = builders.processed(reader, shared)
    assert document.lane is Lane.GREEN
    assert document_access(editor, document, shared) is SpaceRole.EDIT
    assert document_access(other_editor, document, shared) is SpaceRole.EDIT
    assert document_access(reader, document, shared) is SpaceRole.READ
    assert document_access(stranger, document, shared) is None
    assert can_read_document(reader, document, shared)
    assert not can_edit_document(reader, document, shared)
    assert can_edit_document(other_editor, document, shared)


@pytest.mark.parametrize(
    "results",
    [{Node.JUDGE: UNCERTAIN}, {Node.OCR: FAILED}, "processing"],
    ids=["yellow", "red", "processing"],
)
def test_editors_see_every_lane_readers_only_green(
    editor: User,
    reader: User,
    other_editor: User,
    shared: Space,
    results: dict[Node, NodeResult] | str,
) -> None:
    if results == "processing":
        document = builders.document(editor, shared)
    else:
        assert isinstance(results, dict)
        document = builders.processed(editor, shared, results)
    assert document.lane is not Lane.GREEN
    assert document_access(editor, document, shared) is SpaceRole.EDIT
    assert document_access(other_editor, document, shared) is SpaceRole.EDIT
    assert document_access(reader, document, shared) is None


def test_uploading_gives_no_rights(editor: User, stranger: User, shared: Space) -> None:
    """Who uploaded a document has no rights for it: only the space counts."""
    document = builders.processed(stranger, shared)
    assert document.uploaded_by == stranger.id
    assert document_access(stranger, document, shared) is None
    assert document_access(editor, document, shared) is SpaceRole.EDIT


def test_access_needs_the_documents_space(editor: User, shared: Space) -> None:
    document = builders.processed(editor, shared)
    with pytest.raises(ValueError, match="not in space"):
        document_access(editor, document, builders.space(editor))
    with pytest.raises(ValueError, match="not in space"):
        reach_access(editor, document, builders.space(editor))


def test_filing_needs_edit_rights_on_the_space(
    editor: User, reader: User, other_editor: User, stranger: User, shared: Space
) -> None:
    assert can_file_into(editor, shared)
    assert can_file_into(other_editor, shared)
    assert not can_file_into(reader, shared)
    assert not can_file_into(stranger, shared)
    assert can_file_into(builders.admin(), shared)


def test_editors_and_admins_manage_a_space(
    editor: User, reader: User, other_editor: User, stranger: User, shared: Space
) -> None:
    for user in (editor, other_editor, builders.admin()):
        assert can_manage_space(user, shared)
        assert can_choose_members(user, shared)
    for user in (reader, stranger):
        assert not can_manage_space(user, shared)
        assert not can_choose_members(user, shared)


def test_only_its_user_chooses_the_members_of_a_personal_space(editor: User, reader: User) -> None:
    personal = builders.personal_space(editor)
    personal.set_member(reader.id, SpaceRole.EDIT)
    assert can_choose_members(editor, personal)
    assert can_choose_members(builders.admin(), personal)
    assert not can_choose_members(reader, personal)  # edits its documents, not its members
    assert can_manage_space(reader, personal)


def test_moving_needs_edit_rights_on_both_spaces_or_hands_over(
    editor: User, reader: User, other_editor: User, stranger: User, shared: Space
) -> None:
    document = builders.processed(editor, shared)
    own = builders.personal_space(editor)
    theirs = builders.personal_space(stranger)
    read_only = builders.space(stranger, readers=[editor])
    assert can_move_document(editor, document, shared, own)
    assert can_move_document(editor, document, shared, theirs)  # handing over
    assert can_hand_over(editor, theirs)
    assert not can_hand_over(editor, own)  # their own: they edit it anyway
    assert not can_hand_over(editor, read_only)
    assert not can_move_document(editor, document, shared, read_only)
    assert not can_move_document(reader, document, shared, builders.personal_space(reader))
    assert not can_move_document(stranger, document, shared, theirs)
    assert can_move_document(builders.admin(), document, shared, read_only)


@pytest.mark.parametrize(
    "results",
    [None, {Node.JUDGE: UNCERTAIN}, {Node.OCR: FAILED}, "processing"],
    ids=["green", "yellow", "red", "processing"],
)
def test_admins_have_every_right_on_documents_and_spaces(
    editor: User, shared: Space, results: dict[Node, NodeResult] | str | None
) -> None:
    """Tobi, 08.10.2026: admins have every right and see everything."""
    if results == "processing":
        document = builders.document(editor, shared)
    else:
        assert not isinstance(results, str)
        document = builders.processed(editor, shared, results)
    admin = builders.admin()
    assert document_access(admin, document, shared) is SpaceRole.EDIT
    assert can_edit_document(admin, document, shared)
    assert not in_reach(admin, document, shared)  # not as a member
    assert reach_access(admin, document, shared) is None


def test_deactivated_users_have_no_rights(editor: User, shared: Space) -> None:
    document = builders.processed(editor, shared)
    admin = builders.admin()
    for user in (editor, admin):
        user.active = False
        assert space_role(user, shared) is None
        assert document_access(user, document, shared) is None
        assert not can_file_into(user, shared)
        assert not can_manage_space(user, shared)
        assert not can_choose_members(user, builders.personal_space(user))
        assert not can_hand_over(user, builders.personal_space(builders.user()))


def test_reach_is_every_document_edited_and_the_green_ones_read(
    editor: User, reader: User, shared: Space
) -> None:
    own = builders.personal_space(reader)
    reach = Reach.of(reader.id, [shared, own, builders.space(editor)])
    assert reach == Reach(frozenset({own.id}), frozenset({shared.id}))
    assert reach.spaces == {own.id, shared.id}
    green = builders.processed(editor, shared)
    yellow = builders.processed(editor, shared, {Node.JUDGE: UNCERTAIN})
    mine = builders.processed(reader, own, {Node.JUDGE: UNCERTAIN})
    assert reach.allows(green) and in_reach(reader, green, shared)
    assert not reach.allows(yellow) and not in_reach(reader, yellow, shared)
    assert reach.allows(mine)
    assert within_reach([own.id], [shared.id], green)
    assert not within_reach([], [], green)
