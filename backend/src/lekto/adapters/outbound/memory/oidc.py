"""A stand-in identity provider for tests: the test decides who signs in."""

import hmac
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

from lekto.core.domain.encoding import pkce_challenge, query_parameters
from lekto.core.domain.errors import AuthenticationError
from lekto.core.domain.identity import OidcIdentity


@dataclass(frozen=True)
class _Grant:
    challenge: str
    nonce: str
    identity: OidcIdentity


class FakeOidcProvider:
    """`authorization_url` points to an imaginary provider; `consent` plays the user signing in
    there and returns the code the browser would bring back."""

    def __init__(self, issuer: str = "https://idp.test") -> None:
        self._issuer = issuer
        self._grants: dict[str, _Grant] = {}

    @property
    def issuer(self) -> str:
        return self._issuer

    async def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        query = {
            "response_type": "code",
            "client_id": "lekto",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        return f"{self._issuer}/authorize?{urlencode(query)}"

    def consent(
        self,
        url: str,
        subject: str,
        *,
        username: str | None = None,
        name: str | None = None,
        email: str | None = None,
    ) -> str:
        query = query_parameters(url)
        code = secrets.token_urlsafe(16)
        self._grants[code] = _Grant(
            challenge=query["code_challenge"],
            nonce=query["nonce"],
            identity=OidcIdentity(
                issuer=self._issuer, subject=subject, username=username, email=email, name=name
            ),
        )
        return code

    async def authenticate(self, *, code: str, code_verifier: str, nonce: str) -> OidcIdentity:
        grant = self._grants.pop(code, None)
        if (
            grant is None
            or not hmac.compare_digest(grant.challenge, pkce_challenge(code_verifier))
            or not hmac.compare_digest(grant.nonce, nonce)
        ):
            raise AuthenticationError("the identity provider refused the sign-in")
        return grant.identity
