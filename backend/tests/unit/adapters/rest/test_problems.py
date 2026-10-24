"""Every domain error a request can raise answers with a status of its own, not 500 (M13 review
A-06)."""

from uuid import UUID

from lekto.adapters.inbound.rest import PREFIX
from lekto.adapters.inbound.rest.problems import NOT_FROM_REQUESTS, STATUSES
from lekto.core.domain import errors
from lekto.core.domain.errors import DomainError
from tests.api import auth
from tests.unit.adapters.rest.support import Api, post


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


async def test_a_refusal_names_its_code_beside_the_text(api: Api) -> None:
    a = auth(await api.admin())
    await post(api, "/document-types", {"name": "Invoice"}, a)
    taken = await api.client.post(f"{PREFIX}/document-types", json={"name": "Invoice"}, headers=a)
    assert taken.status_code == 409
    assert taken.json()["detail"] == "'Invoice' already exists"
    assert taken.json()["reason"] == {"code": "name_taken", "params": {"name": "Invoice"}}
    # An error raised with a text only has no code: its detail stands as it is.
    missing = await api.client.get(f"{PREFIX}/contacts/{UUID(int=1)}", headers=a)
    assert missing.status_code == 404 and "reason" not in missing.json()


async def test_a_request_that_does_not_fit_names_each_part_with_its_code(api: Api) -> None:
    a = auth(await api.admin())
    response = await api.client.post(
        f"{PREFIX}/document-types", json={"name": "x" * 201, "icon": 7, "extra": 1}, headers=a
    )
    assert response.status_code == 422
    body = response.json()
    by_field = {item["field"]: item["reason"] for item in body["errors"]}
    assert by_field["name"]["code"] == "input_too_long"
    assert by_field["name"]["params"] == {"max": 200}
    assert by_field["icon"]["code"] == "input_not_text"
    assert by_field["extra"]["code"] == "input_unknown"
    assert body["detail"].startswith("name: String should have at most 200 characters")
