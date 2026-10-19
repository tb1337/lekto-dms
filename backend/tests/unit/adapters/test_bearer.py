"""The bearer token parsing shared by the REST API and the MCP endpoint."""

import pytest

from lekto.adapters.inbound.bearer import bearer_token
from lekto.core.domain.errors import AuthenticationError


@pytest.mark.parametrize("header", ["Bearer lekto_abc", "bearer lekto_abc", "Bearer  lekto_abc "])
def test_the_token_follows_the_scheme(header: str) -> None:
    assert bearer_token(header) == "lekto_abc"


@pytest.mark.parametrize("header", ["", "Bearer", "Bearer ", "Basic lekto_abc", "lekto_abc"])
def test_anything_else_is_refused(header: str) -> None:
    with pytest.raises(AuthenticationError):
        bearer_token(header)
