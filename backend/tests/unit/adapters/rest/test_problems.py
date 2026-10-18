"""Every domain error a request can raise answers with a status of its own, not 500 (M13 review
A-06)."""

from papiq.adapters.inbound.rest.problems import NOT_FROM_REQUESTS, STATUSES
from papiq.core.domain import errors
from papiq.core.domain.errors import DomainError


def _domain_errors() -> set[type[DomainError]]:
    found: set[type[DomainError]] = set()
    stack: list[type[DomainError]] = [DomainError]
    while stack:
        for kind in stack.pop().__subclasses__():
            if kind not in found:
                found.add(kind)
                stack.append(kind)
    return found


def test_every_domain_error_has_a_status_or_never_reaches_a_route() -> None:
    every = {
        kind
        for kind in vars(errors).values()
        if isinstance(kind, type) and issubclass(kind, DomainError) and kind is not DomainError
    }
    assert every <= _domain_errors()
    mapped = [kind for kind, _ in STATUSES]
    unmapped = {
        kind
        for kind in every
        if not any(issubclass(kind, base) for base in mapped) and kind not in NOT_FROM_REQUESTS
    }
    assert unmapped == set()
    assert not any(issubclass(kind, base) for kind in NOT_FROM_REQUESTS for base in mapped)
