"""Tuning of webhooks."""

from dataclasses import dataclass
from datetime import timedelta

TEST_REQUESTS = 10
TEST_WINDOW = timedelta(minutes=1)
"""Test requests a user may send per window: they go out at once, to any address."""


@dataclass(frozen=True, kw_only=True)
class WebhookPolicy:
    """The fields without a value are configuration: the composition sets them from the
    settings, whose defaults are the one source. The others are constants (README)."""

    per_user: int  # webhooks a user may have
    secret_grace: timedelta  # the old secret still signs after renewing
    max_attempts: int  # attempts per delivery
    retry_delay: timedelta  # before the second attempt, then doubling
    max_retry_delay: timedelta = timedelta(hours=1)
    disable_after: int  # deliveries given up in a row until the webhook is switched off
    timeout: timedelta  # per attempt
    test_requests: int = TEST_REQUESTS
    test_window: timedelta = TEST_WINDOW

    def __post_init__(self) -> None:
        if min(self.per_user, self.max_attempts, self.disable_after, self.test_requests) < 1:
            raise ValueError("limits must be at least 1")
