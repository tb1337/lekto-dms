"""The context of the API as a FastAPI dependency, and the services the API works without as
dependencies (`ApiContext.require_search`, ...): search and classifier answer 503 while they
are not configured, the identity provider 404."""

from typing import Annotated

from fastapi import Depends, Request

from papiq.adapters.inbound.context import ApiContext, HealthCheck
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
    return context.require_search()


def _indexing(context: Context) -> IndexingService:
    return context.require_indexing()


def _classifier(context: Context) -> ClassifierService:
    return context.require_classifier()


def _oidc(context: Context) -> OidcService:
    return context.require_oidc()


Search = Annotated[SearchService, Depends(_search)]
Indexing = Annotated[IndexingService, Depends(_indexing)]
Classifier = Annotated[ClassifierService, Depends(_classifier)]
Oidc = Annotated[OidcService, Depends(_oidc)]
