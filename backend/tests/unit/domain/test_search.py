import itertools

import pytest

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.permissions import Reach, can_read_document, in_reach
from lekto.core.domain.pipeline import Lane
from lekto.core.domain.search import (
    PROCESSING,
    EmbeddingStamp,
    Visibility,
    lane_value,
)
from lekto.core.domain.spaces import SpaceRole
from tests import builders

LANES = [None, Lane.GREEN, Lane.YELLOW, Lane.RED]


def test_lane_values() -> None:
    assert [lane_value(lane) for lane in LANES] == [PROCESSING, "green", "yellow", "red"]


@pytest.mark.parametrize(
    ("lane", "role", "admin"),
    list(itertools.product(LANES, [None, *SpaceRole], [False, True])),
)
def test_visibility_is_the_read_rule_of_permissions(
    lane: Lane | None, role: SpaceRole | None, admin: bool
) -> None:
    """`Visibility.allows` agrees with `in_reach` for every combination of lane, role in the
    space and role of the user; and with `can_read_document` for an admin who searches
    everything."""
    reader = builders.admin("reader") if admin else builders.user("reader")
    other = builders.user("other")
    space = builders.space(other)
    if role is not None:
        space.set_member(reader.id, role)
    document = builders.document(other, space)
    document.lane = lane

    visibility = Visibility.of(Reach.of(reader.id, [space]))
    index_document = builders.index_document(id=document.id, space_id=space.id, lane=lane)

    assert visibility.allows(index_document) == in_reach(reader, document, space)
    if admin:
        everything = Visibility(visibility.edits, visibility.reads, everything=True)
        assert everything.allows(index_document) == can_read_document(reader, document, space)


def test_no_spaces_leave_nothing() -> None:
    visibility = Visibility(frozenset())
    assert not visibility.allows(builders.index_document(lane=None))
    assert not visibility.allows(builders.index_document())


def test_vectors_need_a_stamp_and_one_length() -> None:
    stamp = EmbeddingStamp("model", "digest")
    builders.index_document(vectors=((1.0, 2.0), (3.0, 4.0)), embedding=stamp)
    with pytest.raises(ValidationError, match="stamp"):
        builders.index_document(vectors=((1.0,),))
    with pytest.raises(ValidationError, match="one length"):
        builders.index_document(vectors=((1.0,), (1.0, 2.0)), embedding=stamp)
    with pytest.raises(ValidationError, match="one length"):
        builders.index_document(vectors=((),), embedding=stamp)


def test_kept_vectors_keep_their_stamp() -> None:
    assert builders.index_document(vectors=None).vectors is None
    with pytest.raises(ValidationError, match="keep their stamp"):
        builders.index_document(vectors=None, embedding=EmbeddingStamp("m", "d"))
