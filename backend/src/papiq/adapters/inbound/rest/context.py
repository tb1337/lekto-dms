"""The context of the API as a FastAPI dependency, and the services the API works without as
dependencies: search and classifier answer 503 while they are not configured, the identity
provider 404."""

from typing import Annotated

from fastapi import Depends, Request

from papiq.adapters.inbound.context import ApiContext, HealthCheck
from papiq.core.domain.errors import (
    ClassifierUnavailableError,
    NotFoundError,
    SearchUnavailableError,
)
from papiq.core.services.classifier import ClassifierService
from papiq.core.services.indexing import IndexingService
from papiq.core.services.oidc import OidcService
from papiq.core.services.search import SearchService

__all__ = ["ApiContext", "Classifier", "Context", "HealthCheck", "Indexing", "Oidc", "Search"]


def _context(request: Request) -> ApiContext:
    context: ApiContext = request.app.state.context
    return context


Context = Annotated[ApiContext, Depends(_context)]


def _search(context: Context) -> SearchService:
    if context.search is None:
        raise SearchUnavailableError("search is not configured")
    return context.search


def _indexing(context: Context) -> IndexingService:
    if context.indexing is None:
        raise SearchUnavailableError("search is not configured")
    return context.indexing


def _classifier(context: Context) -> ClassifierService:
    if context.classifier is None:
        raise ClassifierUnavailableError("no classifier is configured")
    return context.classifier


def _oidc(context: Context) -> OidcService:
    if context.oidc is None:
        raise NotFoundError("identity provider", "oidc")
    return context.oidc


Search = Annotated[SearchService, Depends(_search)]
Indexing = Annotated[IndexingService, Depends(_indexing)]
Classifier = Annotated[ClassifierService, Depends(_classifier)]
Oidc = Annotated[OidcService, Depends(_oidc)]
