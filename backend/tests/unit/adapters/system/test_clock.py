import pytest

from lekto.adapters.outbound.system import SystemClock
from lekto.core.ports.clock import Clock
from tests.contracts.clock import ClockContract


@pytest.fixture
def clock() -> Clock:
    return SystemClock()


class TestSystemClock(ClockContract):
    pass
