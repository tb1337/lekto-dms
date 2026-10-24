"""Who calls the API: a session cookie (web UI) or `Authorization: Bearer <API token>`.

- With a Bearer header, only the token counts; a cookie in the same request is ignored.
- Requests that change something (any method but GET, HEAD, OPTIONS) need, with a session, the
  header `X-CSRF-Token` with the session's CSRF token (`GET /auth/me`, sign-in answer), and,
  with a token, the scope `read_write`.
- Every protected router depends on `authenticate`, so a route cannot be added without it. It
  runs before the parameters are checked: without credentials the answer is always 401.
- Managing one's own sign-in (password, TOTP, tokens, sessions, links) needs a session; an API
  token cannot be used to take over an account.
"""

from typing import Annotated, Literal, TypedDict

from fastapi import Depends, Request, Response

from lekto.adapters.inbound.bearer import bearer_token
from lekto.adapters.inbound.rest.context import ApiContext, Context
from lekto.core.domain.errors import AuthenticationError, PermissionDeniedError
from lekto.core.domain.identity import csrf_matches
from lekto.core.domain.ids import UserId
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.services.auth import Principal, SignedIn
from lekto.core.services.oidc import FLOW_LIFETIME

SECURE_SESSION_COOKIE = "__Host-lekto_session"
SESSION_COOKIE = "lekto_session"  # without `Secure`, for development over plain HTTP
SECURE_FLOW_COOKIE = "__Host-lekto_oidc"
FLOW_COOKIE = "lekto_oidc"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Security schemes of the OpenAPI document; `app.openapi` sets them per operation from the
# dependencies of its route.
SECURITY_SCHEMES = {
    "session": {
        "type": "apiKey",
        "in": "cookie",
        "name": SECURE_SESSION_COOKIE,
        "description": (
            "Session cookie from `POST /auth/login` or the OIDC callback (`lekto_session` "
            "when the server runs without `Secure` cookies). Changing requests also need the "
            f"header `{CSRF_HEADER}`."
        ),
    },
    "token": {
        "type": "http",
        "scheme": "bearer",
        "description": "Personal API token (`lekto_…`); scope `read` allows reading only.",
    },
}
SECURITY: list[dict[str, list[str]]] = [{"session": []}, {"token": []}]
SESSION_ONLY: list[dict[str, list[str]]] = [{"session": []}]


def session_cookie_name(context: ApiContext) -> str:
    return SECURE_SESSION_COOKIE if context.cookie_secure else SESSION_COOKIE


def flow_cookie_name(context: ApiContext) -> str:
    return SECURE_FLOW_COOKIE if context.cookie_secure else FLOW_COOKIE


async def authenticate(request: Request, context: Context) -> Principal:
    """The caller, checked once per request; AuthenticationError (401) without valid
    credentials, PermissionDeniedError (403) for a change without CSRF token or with a `read`
    token."""
    cached: Principal | None = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    header = request.headers.get("authorization")
    if header is not None:
        principal = await context.auth.authenticate_token(bearer_token(header))
        if request.method not in SAFE_METHODS and not principal.can_write:
            raise PermissionDeniedError(because(ReasonCode.READ_ONLY_TOKEN))
    else:
        session_token = request.cookies.get(session_cookie_name(context))
        if not session_token:
            raise AuthenticationError(because(ReasonCode.AUTHENTICATION_REQUIRED))
        principal = await context.auth.authenticate_session(session_token)
        if request.method not in SAFE_METHODS and not csrf_matches(
            session_token, request.headers.get(CSRF_HEADER, "")
        ):
            raise PermissionDeniedError(because(ReasonCode.CSRF_MISSING, header=CSRF_HEADER))
    request.state.principal = principal
    return principal


async def still_authenticated(request: Request, context: ApiContext, user: UserId) -> bool:
    """Whether the request's credentials still authenticate `user` (for long requests such as
    event streams: a session may have been revoked, the account deactivated)."""
    request.state.principal = None
    try:
        return (await authenticate(request, context)).id == user
    except (AuthenticationError, PermissionDeniedError):
        return False


async def current_user(principal: Annotated[Principal, Depends(authenticate)]) -> UserId:
    """The authenticated user."""
    return principal.id


async def session_principal(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
    """The caller, who must use a session (not an API token)."""
    if principal.session is None:
        raise PermissionDeniedError(because(ReasonCode.SESSION_NEEDED))
    return principal


Authenticated = Annotated[Principal, Depends(authenticate)]
CurrentUser = Annotated[UserId, Depends(current_user)]
SessionPrincipal = Annotated[Principal, Depends(session_principal)]
PROTECTED = [Depends(authenticate)]


async def optional_session(request: Request, context: Context) -> Principal | None:
    """The user signed in with a session cookie, if any (for the OIDC callback)."""
    token = request.cookies.get(session_cookie_name(context))
    if not token:
        return None
    try:
        return await context.auth.authenticate_session(token)
    except AuthenticationError:
        return None


class _CookieAttributes(TypedDict):
    path: str
    secure: bool
    httponly: bool
    samesite: Literal["lax"]


def _cookie_attributes(context: ApiContext) -> _CookieAttributes:
    """Of the session's and the OIDC flow's cookie: for the whole site, `Secure` unless the
    server runs without, out of reach of scripts, and sent along when a link from elsewhere is
    followed (the provider's redirect back)."""
    return {"path": "/", "secure": context.cookie_secure, "httponly": True, "samesite": "lax"}


def set_session_cookie(response: Response, context: ApiContext, signed_in: SignedIn) -> None:
    response.set_cookie(
        session_cookie_name(context),
        signed_in.token,
        max_age=int(context.auth.session_policy.max_age.total_seconds()),
        **_cookie_attributes(context),
    )


def clear_session_cookie(response: Response, context: ApiContext) -> None:
    response.delete_cookie(session_cookie_name(context), **_cookie_attributes(context))


def set_flow_cookie(response: Response, context: ApiContext, value: str) -> None:
    response.set_cookie(
        flow_cookie_name(context),
        value,
        max_age=int(FLOW_LIFETIME.total_seconds()),
        **_cookie_attributes(context),
    )


def clear_flow_cookie(response: Response, context: ApiContext) -> None:
    response.delete_cookie(flow_cookie_name(context), **_cookie_attributes(context))


def client_address(request: Request) -> str | None:
    """The client's address (behind trusted proxies: from X-Forwarded-For, set by Uvicorn)."""
    return request.client.host if request.client is not None else None
