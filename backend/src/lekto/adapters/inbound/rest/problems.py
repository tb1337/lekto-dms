"""Domain errors map to HTTP statuses here, as problem details (RFC 9457); every endpoint
documents the problems it can return."""

import logging
import math
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from lekto.adapters.inbound.problems import (
    PROBLEM_JSON,
    PROBLEMS,
    InputErrorOut,
    Problem,
    blocking_space_out,
    problem,
    problem_responses,
)
from lekto.adapters.inbound.rest.upload import MalformedUploadError, UploadTooLargeError
from lekto.adapters.inbound.schemas import ReasonOut
from lekto.core.domain.errors import (
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
from lekto.core.domain.reasons import ReasonCode, because
from lekto.core.domain.users import UserDeletionBlockedError

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
        detail = str(error)
        coded = _reason_of(error)
        if isinstance(error, DuplicateDocumentError):
            return problem(409, detail, reason=coded, existing_document_id=error.existing)
        if isinstance(error, SpaceWriteDeniedError):
            return problem(403, detail, reason=coded, space_id=error.space_id)
        if isinstance(error, UserDeletionBlockedError):
            spaces = [blocking_space_out(item) for item in error.spaces]
            return problem(409, detail, reason=coded, blocking_spaces=spaces)
        if isinstance(error, OpenFieldsError):
            return problem(422, detail, reason=coded, open_fields=list(error.fields))
        if isinstance(error, SecondFactorRequiredError):
            return problem(401, detail, reason=coded, second_factor_required=True)
        if isinstance(error, AuthenticationError):
            return problem(401, detail, reason=coded, headers={"WWW-Authenticate": "Bearer"})
        if isinstance(error, TooManyAttemptsError):
            seconds = max(1, math.ceil(error.retry_after.total_seconds()))
            return problem(429, detail, reason=coded, headers={"Retry-After": str(seconds)})
        return problem(status_of(error), detail, reason=coded)

    async def validation_error(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, RequestValidationError)
        errors = [_input_error(item) for item in error.errors()]
        details = "; ".join(f"{item.field}: {item.message}" for item in errors)
        return problem(422, details, errors=errors)

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


def _reason_of(error: Exception) -> ReasonOut | None:
    """The code of a domain error that has one of its own; None for one raised with a text."""
    if not isinstance(error, DomainError) or error.reason.code is ReasonCode.ERROR:
        return None
    return ReasonOut.of(error.reason)


# Pydantic's error types (`ErrorDetails.type`) by the reason a client translates, with the
# context values the reason names.
_INPUT: dict[str, tuple[ReasonCode, dict[str, str]]] = {
    "missing": (ReasonCode.INPUT_MISSING, {}),
    "string_too_short": (ReasonCode.INPUT_TOO_SHORT, {"min": "min_length"}),
    "string_too_long": (ReasonCode.INPUT_TOO_LONG, {"max": "max_length"}),
    "too_short": (ReasonCode.INPUT_TOO_FEW, {"min": "min_length"}),
    "too_long": (ReasonCode.INPUT_TOO_MANY, {"max": "max_length"}),
    "greater_than_equal": (ReasonCode.INPUT_TOO_SMALL, {"min": "ge"}),
    "greater_than": (ReasonCode.INPUT_ABOVE, {"min": "gt"}),
    "less_than_equal": (ReasonCode.INPUT_TOO_LARGE, {"max": "le"}),
    "less_than": (ReasonCode.INPUT_BELOW, {"max": "lt"}),
    "enum": (ReasonCode.INPUT_CHOICE, {}),
    "literal_error": (ReasonCode.INPUT_CHOICE, {}),
    "uuid_parsing": (ReasonCode.INPUT_NOT_ID, {}),
    "uuid_type": (ReasonCode.INPUT_NOT_ID, {}),
    "uuid_version": (ReasonCode.INPUT_NOT_ID, {}),
    "date_parsing": (ReasonCode.INPUT_NOT_DATE, {}),
    "date_type": (ReasonCode.INPUT_NOT_DATE, {}),
    "date_from_datetime_parsing": (ReasonCode.INPUT_NOT_DATE, {}),
    "date_from_datetime_inexact": (ReasonCode.INPUT_NOT_DATE, {}),
    "datetime_parsing": (ReasonCode.INPUT_NOT_DATETIME, {}),
    "datetime_type": (ReasonCode.INPUT_NOT_DATETIME, {}),
    "datetime_from_date_parsing": (ReasonCode.INPUT_NOT_DATETIME, {}),
    "timezone_aware": (ReasonCode.INPUT_NOT_DATETIME, {}),
    "int_parsing": (ReasonCode.INPUT_NOT_INTEGER, {}),
    "int_type": (ReasonCode.INPUT_NOT_INTEGER, {}),
    "int_from_float": (ReasonCode.INPUT_NOT_INTEGER, {}),
    "float_parsing": (ReasonCode.INPUT_NOT_NUMBER, {}),
    "float_type": (ReasonCode.INPUT_NOT_NUMBER, {}),
    "decimal_parsing": (ReasonCode.INPUT_NOT_NUMBER, {}),
    "decimal_type": (ReasonCode.INPUT_NOT_NUMBER, {}),
    "bool_parsing": (ReasonCode.INPUT_NOT_BOOLEAN, {}),
    "bool_type": (ReasonCode.INPUT_NOT_BOOLEAN, {}),
    "string_type": (ReasonCode.INPUT_NOT_TEXT, {}),
    "list_type": (ReasonCode.INPUT_NOT_LIST, {}),
    "dict_type": (ReasonCode.INPUT_NOT_OBJECT, {}),
    "model_type": (ReasonCode.INPUT_NOT_OBJECT, {}),
    "model_attributes_type": (ReasonCode.INPUT_NOT_OBJECT, {}),
    "extra_forbidden": (ReasonCode.INPUT_UNKNOWN, {}),
    "string_pattern_mismatch": (ReasonCode.INPUT_PATTERN, {}),
}


def _input_error(item: Mapping[str, Any]) -> InputErrorOut:
    """One of Pydantic's errors with the reason a client translates; its message where its
    type has none (`INPUT_INVALID`)."""
    field = ".".join(str(part) for part in item["loc"][1:]) or "body"
    message = str(item["msg"])
    code, names = _INPUT.get(str(item["type"]), (ReasonCode.INPUT_INVALID, {}))
    context = item.get("ctx") or {}
    params = {name: context.get(key) for name, key in names.items()}
    if code is ReasonCode.INPUT_INVALID or any(value is None for value in params.values()):
        reason = because(ReasonCode.INPUT_INVALID, detail=message)
    else:
        reason = because(code, **params)
    return InputErrorOut(field=field, message=message, reason=ReasonOut.of(reason))
