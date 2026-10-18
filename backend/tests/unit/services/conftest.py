import pytest

from tests.unit.services.support import World


@pytest.fixture
def world() -> World:
    return World()
