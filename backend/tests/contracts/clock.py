from datetime import UTC

from lekto.core.ports.clock import Clock


class ClockContract:
    def test_now_is_utc(self, clock: Clock) -> None:
        assert clock.now().tzinfo is UTC

    def test_time_does_not_run_backwards(self, clock: Clock) -> None:
        first = clock.now()
        assert clock.now() >= first
