"""base64url, the PKCE challenge and a URL's query parameters."""

import pytest

from papiq.core.domain.encoding import (
    base64url,
    from_base64url,
    pkce_challenge,
    query_parameters,
)


def test_base64url_has_no_padding_and_reads_back() -> None:
    for data in (b"", b"\xfb", b"\xfb\xff", b"\xfb\xff\xbf"):
        text = base64url(data)
        assert "=" not in text and "+" not in text and "/" not in text
        assert from_base64url(text) == data
    assert base64url(b"\xfb\xff") == "-_8"


def test_base64url_of_a_wrong_length_is_refused() -> None:
    with pytest.raises(ValueError):
        from_base64url("a")


def test_the_pkce_challenge_is_rfc_7636s() -> None:
    # The example of RFC 7636, appendix B.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_the_query_parameters_of_a_url_with_their_first_values() -> None:
    url = "https://idp.test/authorize?state=s&scope=openid+email&state=t&empty="
    assert query_parameters(url) == {"state": "s", "scope": "openid email"}
