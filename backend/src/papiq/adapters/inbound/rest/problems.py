"""Domain errors map to HTTP statuses here, as problem details (RFC 9457); every endpoint
documents the problems it can return."""

import logging
import math

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from papiq.adapters.inbound.problems import (
    PROBLEM_JSON,
    PROBLEMS,
    Problem,
    problem,
    problem_responses,
)
from papiq.adapters.inbound.rest.upload import MalformedUploadError, UploadTooLargeError
from papiq.core.domain.errors import (
    AuthenticationError,
    ClassifierError,
    ClassifierUnavailableError,
    ConflictError,
    DomainError,
    DuplicateDocumentError,
    EmbeddingsError,
    IdentityProviderError,
    InvalidTransitionError,
    LanguageModelError,
    LogoFetchDisabledError,
    LogoFetchError,
    MissingValueError,
    NotFoundError,
    OpenFieldsError,
    PatternTimeoutError,
    PermissionDeniedError,
    SearchError,
    SecondFactorRequiredError,
    SpaceWriteDeniedError,
    TooManyAttemptsError,
    UnprocessableDocumentError,
    UnsupportedMediaTypeError,
    ValidationError,
)

__all__ = [
    "NOT_FROM_REQUESTS",
    "PROBLEM_JSON",
    "STATUSES",
    "Problem",
    "install",
    "problem",
    "problem_responses",
]

log = logging.getLogger(__name__)


def install(app: FastAPI) -> None:
    """Register the handlers that turn errors into problems."""

    def status_of(error: Exception) -> int:
        for kind, status in STATUSES:
            if isinstance(error, kind):
                return status
        raise error

    async def domain_error(request: Request, error: Exception) -> JSONResponse:
        if isinstance(error, DuplicateDocumentError):
            return problem(409, str(error), existing_document_id=error.existing)
        if isinstance(error, SpaceWriteDeniedError):
            return problem(403, str(error), space_id=error.space_id)
        if isinstance(error, OpenFieldsError):
            return problem(422, str(error), open_fields=list(error.fields))
        if isinstance(error, SecondFactorRequiredError):
            return problem(401, str(error), second_factor_required=True)
        if isinstance(error, AuthenticationError):
            return problem(401, str(error), headers={"WWW-Authenticate": "Bearer"})
        if isinstance(error, TooManyAttemptsError):
            seconds = max(1, math.ceil(error.retry_after.total_seconds()))
            return problem(429, str(error), headers={"Retry-After": str(seconds)})
        return problem(status_of(error), str(error))

    async def validation_error(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, RequestValidationError)
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'][1:]) or 'body'}: {item['msg']}"
            for item in error.errors()
        )
        return problem(422, details)

    async def http_error(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, HTTPException)
        return problem(error.status_code, str(error.detail), headers=error.headers)

    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        # Details stay in the server log; the client learns only that something broke.
        log.error("request failed", exc_info=error)
        return problem(500, PROBLEMS[500][1])

    for kind, _ in STATUSES:
        app.add_exception_handler(kind, domain_error)
    app.add_exception_handler(Exception, unexpected_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(HTTPException, http_error)


# Most specific first.
STATUSES: list[tuple[type[Exception], int]] = [
    (AuthenticationError, 401),
    (TooManyAttemptsError, 429),
    (IdentityProviderError, 502),
    (UnsupportedMediaTypeError, 415),
    (ValidationError, 422),
    (NotFoundError, 404),
    (PermissionDeniedError, 403),
    (InvalidTransitionError, 409),
    (ConflictError, 409),
    (UploadTooLargeError, 413),
    (MalformedUploadError, 400),
    (SearchError, 503),
    (ClassifierUnavailableError, 503),
    (LogoFetchDisabledError, 503),
]

NOT_FROM_REQUESTS: frozenset[type[DomainError]] = frozenset(
    {
        UnprocessableDocumentError,  # fails a node in the worker; the facts tab notes it
        LanguageModelError,  # a classification node's, in the worker: the node runs again
        EmbeddingsError,  # the search falls back to words, the index and signals note it
        ClassifierError,  # training in the worker or the command; the signal abstains
        LogoFetchError,  # fetching in the worker: the contact keeps no logo
        PatternTimeoutError,  # the rules skip the pattern and note it
        MissingValueError,  # a template's: the rules skip the action and note it
    }
)
"""Domain errors no request lets through: the services catch them, or they arise in the worker
only. One that reached a route would answer 500; a test holds every other one to a status."""
